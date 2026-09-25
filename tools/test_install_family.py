from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from tools import install_skill
from tools.family_manifest import load_manifest, ordered_members


REPO = Path(__file__).resolve().parents[1]


class InstallFamilyTests(unittest.TestCase):
    def setUp(self):
        self.manifest = load_manifest(REPO)

    def test_member_markers_have_role_specific_interfaces(self):
        members = ordered_members(REPO, self.manifest)
        core = install_skill.member_marker(members[0], "a" * 64, "abc123", self.manifest)
        self.assertEqual(
            core,
            {
                "bundle_tree_sha256": "a" * 64,
                "family": "clothing-shop-studio",
                "family_interface": 1,
                "family_version": 1,
                "role": "core",
                "source_commit": "abc123",
            },
        )
        wrapper = install_skill.member_marker(members[1], "b" * 64, "abc123", self.manifest)
        self.assertEqual(wrapper["role"], "wrapper")
        self.assertEqual(wrapper["core_interface_min"], 1)
        self.assertEqual(wrapper["core_interface_max"], 1)
        self.assertNotIn("family_interface", wrapper)

    def test_legacy_core_marker_is_exactly_the_old_two_key_shape(self):
        legacy = {"source_commit": "abc", "bundle_tree_sha256": "0" * 64}
        self.assertTrue(install_skill.is_legacy_core_marker("clothing-shop-studio", legacy))
        self.assertFalse(install_skill.is_legacy_core_marker("clothing-new", legacy))
        self.assertFalse(install_skill.is_legacy_core_marker("clothing-shop-studio", {**legacy, "extra": 1}))

    def install_fixture(self, skills_dir: Path) -> None:
        for member in ordered_members(REPO, self.manifest):
            target = skills_dir / member["name"]
            install_skill.copy_bundle(member["source"], target)
            source_hash = install_skill.tree_hash(member["source"])
            marker = install_skill.member_marker(member, source_hash, "old-commit-is-allowed", self.manifest)
            (target / "INSTALLED_FROM.json").write_text(
                json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

    def test_family_drift_is_empty_for_matching_family_and_ignores_source_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            skills = Path(folder) / "skills"
            self.install_fixture(skills)
            self.assertEqual(install_skill.family_drift(REPO, skills, self.manifest), [])

    def test_family_drift_reports_content_marker_membership_and_journal_in_order(self):
        with tempfile.TemporaryDirectory() as folder:
            skills = Path(folder) / "skills"
            self.install_fixture(skills)
            (skills / "clothing-new/SKILL.md").write_text("changed", encoding="utf-8")
            marker_path = skills / "clothing-resume/INSTALLED_FROM.json"
            marker = json.loads(marker_path.read_text("utf-8"))
            marker["family_version"] = 99
            marker_path.write_text(json.dumps(marker), encoding="utf-8")
            shutil.rmtree(skills / "clothing-options")
            obsolete = skills / "clothing-old"
            obsolete.mkdir()
            (obsolete / "INSTALLED_FROM.json").write_text(
                json.dumps({"family": "clothing-shop-studio", "role": "wrapper"}), encoding="utf-8"
            )
            transaction = skills.parent / ".clothing-shop-studio-install"
            transaction.mkdir()
            (transaction / "journal.json").write_text(
                json.dumps({"committed": False, "members": []}), encoding="utf-8"
            )
            drift = install_skill.family_drift(REPO, skills, self.manifest)
            self.assertEqual(drift, sorted(drift))
            joined = "\n".join(drift)
            for text in ("uncommitted journal", "clothing-new", "clothing-options", "clothing-resume", "clothing-old"):
                self.assertIn(text, joined)

    def test_check_mode_is_read_only_and_uses_deterministic_exit_codes(self):
        with tempfile.TemporaryDirectory() as folder:
            skills = Path(folder) / "skills"
            output = StringIO()
            with redirect_stdout(output):
                code = install_skill.main(["--check", "--skills-dir", str(skills)])
            self.assertEqual(code, 1)
            self.assertIn("DRIFT clothing-ai-models: missing", output.getvalue())
            self.assertFalse(skills.exists())
            self.assertFalse((skills.parent / ".clothing-shop-studio-install").exists())

            self.install_fixture(skills)
            output = StringIO()
            with redirect_stdout(output):
                code = install_skill.main(["--check", "--skills-dir", str(skills)])
            self.assertEqual(code, 0)
            self.assertEqual(output.getvalue(), "")

    def test_family_preflight_validates_every_member_and_checks_generated_sources(self):
        members = ordered_members(REPO, self.manifest)
        with mock.patch("tools.install_skill.require_clean_paths") as clean, mock.patch(
            "tools.install_skill._run"
        ) as run, mock.patch(
            "tools.install_skill.validate_skill_without_pyyaml"
        ) as validate, mock.patch(
            "tools.install_skill.build_wrappers.build", return_value=[]
        ) as wrapper_check, mock.patch(
            "tools.install_skill.subprocess.check_output", return_value="abc123\n"
        ):
            result = install_skill.verify_family_source(REPO, self.manifest, "fallback")

        self.assertEqual(result, "abc123")
        checked_paths = {Path(path).resolve() for path in clean.call_args.args[1]}
        for member in members:
            self.assertIn(Path(member["source"]).resolve(), checked_paths)
        for relative in ("tools/wrappers.json", "tools/family_manifest.py", "tools/build_wrappers.py"):
            self.assertIn((REPO / relative).resolve(), checked_paths)
        self.assertEqual(validate.call_count, len(members))
        self.assertEqual(run.call_count, 2)
        wrapper_check.assert_called_once_with(REPO.resolve(), check=True)


if __name__ == "__main__":
    unittest.main()
