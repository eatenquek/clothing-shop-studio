from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tools import install_transaction


REPO = Path(__file__).resolve().parents[1]


def marker(member: dict, source_hash: str) -> dict:
    return {"family": "clothing-shop-studio", "role": "core", "bundle_tree_sha256": source_hash}


class InstallTransactionTests(unittest.TestCase):
    def source_member(self, root: Path) -> dict:
        source = root / "source/clothing-shop-studio"
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text("new\n", encoding="utf-8")
        return {"name": "clothing-shop-studio", "source": source}

    def old_target(self, skills: Path) -> Path:
        target = skills / "clothing-shop-studio"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("old\n", encoding="utf-8")
        return target

    def test_transaction_root_and_stage_are_on_destination_filesystem(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            skills = root / "home/.codex/skills"
            member = self.source_member(root)
            staged = install_transaction.stage_members([member], skills, marker)
            self.assertEqual(
                install_transaction.transaction_root(skills),
                skills.parent.resolve() / ".clothing-shop-studio-install",
            )
            self.assertEqual(staged[0]["source_hash"], staged[0]["staged_hash"])
            self.assertEqual(staged[0]["stage"].stat().st_dev, skills.parent.stat().st_dev)

    def test_commit_replaces_existing_target_and_cleans_journal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            skills = root / "home/.codex/skills"
            target = self.old_target(skills)
            staged = install_transaction.stage_members([self.source_member(root)], skills, marker)
            result = install_transaction.commit_staged(skills, staged, [])
            self.assertEqual((target / "SKILL.md").read_text("utf-8"), "new\n")
            self.assertTrue(result["committed"])
            self.assertFalse((install_transaction.transaction_root(skills) / "journal.json").exists())

    def test_failures_at_every_mutation_boundary_restore_previous_target(self):
        labels = (
            "before_backup_intent", "after_backup_intent", "after_backup_move", "after_backed_up",
            "before_swap_intent", "after_swap_intent", "after_swap", "after_swapped",
            "before_verify", "after_verified",
        )
        for label in labels:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                skills = root / "home/.codex/skills"
                target = self.old_target(skills)
                staged = install_transaction.stage_members([self.source_member(root)], skills, marker)

                def fail(point: str, _entry: dict) -> None:
                    if point == label:
                        raise RuntimeError(f"injected {label}")

                with self.assertRaisesRegex(RuntimeError, "injected"):
                    install_transaction.commit_staged(skills, staged, [], hook=fail)
                self.assertEqual((target / "SKILL.md").read_text("utf-8"), "old\n")
                install_transaction.recover_uncommitted(skills)
                self.assertEqual((target / "SKILL.md").read_text("utf-8"), "old\n")

    def test_failed_new_member_is_removed_by_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            skills = root / "home/.codex/skills"
            staged = install_transaction.stage_members([self.source_member(root)], skills, marker)

            def fail(point: str, _entry: dict) -> None:
                if point == "after_swap":
                    raise RuntimeError("stop")

            with self.assertRaisesRegex(RuntimeError, "stop"):
                install_transaction.commit_staged(skills, staged, [], hook=fail)
            self.assertFalse((skills / "clothing-shop-studio").exists())

    def test_family_verifier_runs_before_commit_and_failure_rolls_back(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            skills = root / "home/.codex/skills"
            target = self.old_target(skills)
            staged = install_transaction.stage_members([self.source_member(root)], skills, marker)

            def reject_family():
                raise RuntimeError("family does not agree")

            with self.assertRaisesRegex(RuntimeError, "family does not agree"):
                install_transaction.commit_staged(skills, staged, [], verify=reject_family)
            self.assertEqual((target / "SKILL.md").read_text("utf-8"), "old\n")

    def test_cleanup_failure_after_commit_keeps_verified_new_target(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            skills = root / "home/.codex/skills"
            target = self.old_target(skills)
            staged = install_transaction.stage_members([self.source_member(root)], skills, marker)
            backup = staged[0]["backup"]
            real_remove = install_transaction._remove_path

            def fail_backup_cleanup(path: Path) -> None:
                if Path(path) == backup:
                    raise OSError("cleanup failed")
                real_remove(path)

            with mock.patch(
                "tools.install_transaction._remove_path", side_effect=fail_backup_cleanup
            ):
                result = install_transaction.commit_staged(skills, staged, [])
            self.assertTrue(result["committed"])
            self.assertEqual((target / "SKILL.md").read_text("utf-8"), "new\n")

    def test_recovery_failure_retains_actionable_journal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            skills = root / "home/.codex/skills"
            target = self.old_target(skills)
            transaction = install_transaction.transaction_root(skills)
            backup = transaction / "backups/run/clothing-shop-studio"
            backup.parent.mkdir(parents=True)
            target.rename(backup)
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("new\n", encoding="utf-8")
            journal = {
                "family": "clothing-shop-studio", "committed": False,
                "members": [{
                    "name": "clothing-shop-studio", "existed_before": True,
                    "target": str(target), "backup": str(backup), "stage": str(transaction / "stage"),
                    "source_hash": "0" * 64, "staged_hash": install_transaction.tree_hash(target),
                    "state": "swapped", "remove": False,
                }],
            }
            install_transaction.write_journal(transaction / "journal.json", journal)
            with mock.patch("tools.install_transaction.os.replace", side_effect=OSError("restore failed")):
                with self.assertRaisesRegex(RuntimeError, "clothing-shop-studio"):
                    install_transaction.recover_uncommitted(skills)
            self.assertTrue((transaction / "journal.json").is_file())

    def test_process_death_at_each_mutation_boundary_is_recovered(self):
        labels = (
            "before_backup_intent", "after_backup_intent", "after_backup_move", "after_backed_up",
            "before_swap_intent", "after_swap_intent", "after_swap", "after_swapped",
            "before_verify", "after_verified",
        )
        for label in labels:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                skills = root / "home/.codex/skills"
                target = self.old_target(skills)
                source = self.source_member(root)["source"]
                code = (
                    "import os\n"
                    "from pathlib import Path\n"
                    "from tools import install_transaction as tx\n"
                    f"skills=Path({str(skills)!r})\nsource=Path({str(source)!r})\n"
                    "staged=tx.stage_members([{'name':'clothing-shop-studio','source':source}], skills, "
                    "lambda m,h:{'family':'clothing-shop-studio','role':'core','bundle_tree_sha256':h})\n"
                    f"tx.commit_staged(skills, staged, [], hook=lambda point,entry: os._exit(91) if point=={label!r} else None)\n"
                )
                completed = subprocess.run([sys.executable, "-c", code], cwd=REPO, check=False)
                self.assertEqual(completed.returncode, 91)
                install_transaction.recover_uncommitted(skills)
                install_transaction.recover_uncommitted(skills)
                self.assertEqual((target / "SKILL.md").read_text("utf-8"), "old\n")

    def test_exclusive_lock_blocks_a_second_process(self):
        with tempfile.TemporaryDirectory() as folder:
            skills = Path(folder) / "home/.codex/skills"
            code = (
                "import time\nfrom pathlib import Path\nfrom tools.install_transaction import install_lock\n"
                f"skills=Path({str(skills)!r})\n"
                "with install_lock(skills):\n print('locked', flush=True); time.sleep(0.4)\n"
            )
            child = subprocess.Popen(
                [sys.executable, "-c", code], cwd=REPO, text=True, stdout=subprocess.PIPE
            )
            self.assertEqual(child.stdout.readline().strip(), "locked")
            started = time.monotonic()
            with install_transaction.install_lock(skills):
                elapsed = time.monotonic() - started
            child.wait(timeout=2)
            child.stdout.close()
            self.assertGreaterEqual(elapsed, 0.2)


if __name__ == "__main__":
    unittest.main()
