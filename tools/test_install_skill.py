from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import install_skill
from tools.install_skill import copy_bundle, install_verified, tree_hash


class InstallSkillTests(unittest.TestCase):
    def make_repo(self, root: Path, *, validator_body: str) -> tuple[Path, Path, Path]:
        repo = root / "repo"
        source = repo / "skill/clothing-shop-studio"
        (source / "tests").mkdir(parents=True)
        (repo / "tools").mkdir()
        (source / "SKILL.md").write_text(
            "---\nname: clothing-shop-studio\ndescription: Use when testing an install.\n---\n\n# Skill\n",
            encoding="utf-8",
        )
        passing_test = (
            "import unittest\n\n"
            "class FixtureTest(unittest.TestCase):\n"
            "    def test_fixture(self):\n"
            "        self.assertTrue(True)\n"
        )
        (source / "tests/test_fixture.py").write_text(passing_test, encoding="utf-8")
        (repo / "tools/test_fixture.py").write_text(passing_test, encoding="utf-8")
        validator = repo / "validator.py"
        validator.write_text(validator_body, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
        return repo, source, validator

    def test_copy_excludes_caches_and_install_writes_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            (source / "scripts/__pycache__").mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: test\ndescription: test\n---\n")
            (source / "scripts/main.py").write_text("print('ok')\n")
            (source / "scripts/__pycache__/main.pyc").write_bytes(b"cache")
            stage = root / "work/stage"
            copy_bundle(source, stage)
            self.assertFalse((stage / "scripts/__pycache__").exists())
            self.assertEqual(tree_hash(source), tree_hash(stage))

            target = root / "home/.codex/skills/test"
            result = install_verified(source, target, root / "work", "abc123")
            marker = json.loads((target / "INSTALLED_FROM.json").read_text())
            self.assertEqual(marker["source_commit"], "abc123")
            self.assertEqual(marker["bundle_tree_sha256"], result["bundle_tree_sha256"])
            self.assertEqual(tree_hash(source), tree_hash(target))

    def test_clean_source_gate_rejects_untracked_skill_files(self):
        with tempfile.TemporaryDirectory() as folder:
            repo, source, _ = self.make_repo(Path(folder), validator_body="raise SystemExit(0)\n")
            (source / "untracked.txt").write_text("not in the named commit\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "uncommitted"):
                install_skill.require_clean_source(repo, source)

    def test_verification_falls_back_when_validator_only_lacks_pyyaml(self):
        with tempfile.TemporaryDirectory() as folder:
            repo, source, validator = self.make_repo(
                Path(folder), validator_body="raise ModuleNotFoundError(\"No module named 'yaml'\")\n"
            )
            commit = install_skill.verify_source(repo, source, validator)
            expected = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            self.assertEqual(commit, expected)

    def test_verification_does_not_hide_other_validator_failures(self):
        with tempfile.TemporaryDirectory() as folder:
            repo, source, validator = self.make_repo(
                Path(folder), validator_body="raise SystemExit('invalid skill')\n"
            )
            with self.assertRaisesRegex(RuntimeError, "invalid skill"):
                install_skill.verify_source(repo, source, validator)

    def test_verification_can_select_the_fallback_validator_explicitly(self):
        with tempfile.TemporaryDirectory() as folder:
            repo, source, _ = self.make_repo(Path(folder), validator_body="raise SystemExit(1)\n")
            commit = install_skill.verify_source(repo, source, "fallback")
            expected = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            self.assertEqual(commit, expected)

    def test_failed_post_install_hash_check_restores_previous_target(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            (source / "SKILL.md").write_text("new skill\n", encoding="utf-8")
            target = root / "home/.codex/skills/test"
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("old skill\n", encoding="utf-8")
            source_hash = tree_hash(source)
            with mock.patch(
                "tools.install_skill.tree_hash",
                side_effect=[source_hash, source_hash, "wrong-installed-hash"],
            ):
                with self.assertRaisesRegex(RuntimeError, "installed skill differs"):
                    install_verified(source, target, root / "work", "abc123")
            self.assertEqual((target / "SKILL.md").read_text("utf-8"), "old skill\n")
            self.assertFalse((root / "work/install-staging/test").exists())

    def test_failed_backup_move_preserves_previous_target(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            (source / "SKILL.md").write_text("new skill\n", encoding="utf-8")
            target = root / "home/.codex/skills/test"
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("old skill\n", encoding="utf-8")

            with mock.patch("tools.install_skill.os.replace", side_effect=OSError("backup move failed")):
                with self.assertRaisesRegex(OSError, "backup move failed"):
                    install_verified(source, target, root / "work", "abc123")

            self.assertTrue(target.is_dir(), "the previous install must survive a failed backup move")
            self.assertEqual((target / "SKILL.md").read_text("utf-8"), "old skill\n")
            self.assertFalse((root / "work/install-staging/test").exists())

    def test_failed_backup_cleanup_keeps_verified_new_target(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            (source / "SKILL.md").write_text("new skill\n", encoding="utf-8")
            target = root / "home/.codex/skills/test"
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("old skill\n", encoding="utf-8")
            work = root / "work"
            real_rmtree = shutil.rmtree

            def fail_partway_through_backup_cleanup(path, *args, **kwargs):
                path = Path(path)
                if path.parent == work.resolve() / "install-backups":
                    (path / "SKILL.md").unlink()
                    raise OSError("backup cleanup failed")
                return real_rmtree(path, *args, **kwargs)

            with mock.patch(
                "tools.install_skill.shutil.rmtree",
                side_effect=fail_partway_through_backup_cleanup,
            ):
                result = install_verified(source, target, work, "abc123")

            self.assertEqual((target / "SKILL.md").read_text("utf-8"), "new skill\n")
            self.assertEqual(result["bundle_tree_sha256"], tree_hash(source))
            marker = json.loads((target / "INSTALLED_FROM.json").read_text("utf-8"))
            self.assertEqual(marker["source_commit"], "abc123")


if __name__ == "__main__":
    unittest.main()
