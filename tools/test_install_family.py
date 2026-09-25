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


def complete_tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


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

    def run_family_install(self, skills_dir: Path, *, adopt_unmarked: bool = False) -> dict:
        with mock.patch(
            "tools.install_skill.verify_family_source", return_value="abc123"
        ):
            return install_skill.install_family(
                REPO,
                skills_dir,
                self.manifest,
                "fallback",
                adopt_unmarked=adopt_unmarked,
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

    def test_default_install_recovers_before_preflight_then_stages_and_commits(self):
        with tempfile.TemporaryDirectory() as folder:
            skills = Path(folder) / "skills"
            events = []

            class Lock:
                def __enter__(self):
                    events.append("lock")

                def __exit__(self, *_args):
                    events.append("unlock")

            staged = [{
                "name": "clothing-shop-studio",
                "backup": skills.parent / ".clothing-shop-studio-install/backups/run/clothing-shop-studio",
            }]
            with mock.patch(
                "tools.install_skill.install_transaction.install_lock",
                side_effect=lambda _path: Lock(),
            ), mock.patch(
                "tools.install_skill.install_transaction.recover_uncommitted",
                side_effect=lambda _path: events.append("recover"),
            ), mock.patch(
                "tools.install_skill.verify_family_source",
                side_effect=lambda *_args: events.append("preflight") or "abc123",
            ), mock.patch(
                "tools.install_skill.install_transaction.stage_members",
                side_effect=lambda *_args: events.append("stage") or staged,
            ), mock.patch(
                "tools.install_skill.install_transaction.commit_staged",
                side_effect=lambda *_args, **kwargs: (
                    events.append("commit"),
                    kwargs["verify"](),
                    {"committed": True, "members": []},
                )[-1],
            ), mock.patch(
                "tools.install_skill.family_drift",
                side_effect=lambda *_args, **_kwargs: events.append("verify") or [],
            ):
                result = install_skill.install_family(REPO, skills, self.manifest, "fallback")

            self.assertTrue(result["committed"])
            self.assertEqual(
                events,
                ["lock", "recover", "preflight", "stage", "commit", "verify", "unlock"],
            )

    def test_fresh_family_install_is_core_first_idempotent_and_checkable(self):
        with tempfile.TemporaryDirectory() as folder:
            skills = Path(folder) / "skills"
            orders = []
            real_commit = install_skill.install_transaction.commit_staged

            def record_order(skills_dir, staged, obsolete, **kwargs):
                orders.append([entry["name"] for entry in staged])
                return real_commit(skills_dir, staged, obsolete, **kwargs)

            with mock.patch(
                "tools.install_skill.install_transaction.commit_staged", side_effect=record_order
            ):
                self.run_family_install(skills)
                self.run_family_install(skills)
            expected = [member["name"] for member in ordered_members(REPO, self.manifest)]
            self.assertEqual(orders, [expected, expected])
            self.assertEqual(orders[0][0], "clothing-shop-studio")
            self.assertEqual(install_skill.family_drift(REPO, skills, self.manifest), [])

    def test_legacy_core_upgrades_without_adoption(self):
        with tempfile.TemporaryDirectory() as folder:
            skills = Path(folder) / "skills"
            core = skills / "clothing-shop-studio"
            install_skill.copy_bundle(REPO / "skill/clothing-shop-studio", core)
            (core / "INSTALLED_FROM.json").write_text(
                json.dumps({"source_commit": "old", "bundle_tree_sha256": install_skill.tree_hash(core)}),
                encoding="utf-8",
            )
            self.run_family_install(skills)
            marker = json.loads((core / "INSTALLED_FROM.json").read_text("utf-8"))
            self.assertEqual(marker["family"], "clothing-shop-studio")

    def test_unmarked_collision_is_refused_unless_explicitly_adopted(self):
        with tempfile.TemporaryDirectory() as folder:
            skills = Path(folder) / "skills"
            for name in ("clothing-shop-studio", "clothing-new"):
                target = skills / name
                target.mkdir(parents=True)
                (target / "owner.txt").write_text("unrelated", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "unrelated existing skill"):
                self.run_family_install(skills)
            self.assertEqual((skills / "clothing-new/owner.txt").read_text("utf-8"), "unrelated")
            self.run_family_install(skills, adopt_unmarked=True)
            self.assertFalse((skills / "clothing-new/owner.txt").exists())
            self.assertTrue((skills / "clothing-new/INSTALLED_FROM.json").is_file())

    def test_marked_obsolete_member_is_removed_but_unmarked_name_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            skills = Path(folder) / "skills"
            obsolete = skills / "clothing-retired"
            obsolete.mkdir(parents=True)
            (obsolete / "INSTALLED_FROM.json").write_text(
                json.dumps({"family": "clothing-shop-studio", "role": "wrapper"}),
                encoding="utf-8",
            )
            unrelated = skills / "clothing-unrelated"
            unrelated.mkdir()
            (unrelated / "keep.txt").write_text("keep", encoding="utf-8")
            self.run_family_install(skills)
            self.assertFalse(obsolete.exists())
            self.assertEqual((unrelated / "keep.txt").read_text("utf-8"), "keep")

    def test_core_only_refuses_family_wrappers_and_exact_target_is_honoured(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            skills = root / "skills"
            wrapper = skills / "clothing-new"
            wrapper.mkdir(parents=True)
            (wrapper / "INSTALLED_FROM.json").write_text(
                json.dumps({"family": "clothing-shop-studio", "role": "wrapper"}),
                encoding="utf-8",
            )
            with mock.patch("tools.install_skill.verify_source", return_value="abc123"):
                with self.assertRaisesRegex(RuntimeError, "family wrapper"):
                    install_skill.install_core(
                        REPO,
                        REPO / "skill/clothing-shop-studio",
                        skills / "clothing-shop-studio",
                        self.manifest,
                        "fallback",
                    )
            shutil.rmtree(wrapper)
            exact = root / "claude-skills/clothing-shop-studio"
            with mock.patch("tools.install_skill.verify_source", return_value="abc123"):
                install_skill.install_core(
                    REPO,
                    REPO / "skill/clothing-shop-studio",
                    exact,
                    self.manifest,
                    "fallback",
                )
            self.assertTrue((exact / "INSTALLED_FROM.json").is_file())

    def test_failure_after_wrapper_swap_restores_entire_previous_family(self):
        with tempfile.TemporaryDirectory() as folder:
            skills = Path(folder) / "skills"
            self.install_fixture(skills)
            before = {
                member["name"]: complete_tree_snapshot(skills / member["name"])
                for member in ordered_members(REPO, self.manifest)
            }
            real_commit = install_skill.install_transaction.commit_staged

            def fail_second(skills_dir, staged, obsolete, **kwargs):
                second = staged[1]["name"]
                return real_commit(
                    skills_dir,
                    staged,
                    obsolete,
                    hook=lambda point, entry: (_ for _ in ()).throw(RuntimeError("wrapper failed"))
                    if point == "after_swap" and entry["name"] == second else None,
                    **kwargs,
                )

            with mock.patch(
                "tools.install_skill.install_transaction.commit_staged", side_effect=fail_second
            ):
                with self.assertRaisesRegex(RuntimeError, "wrapper failed"):
                    self.run_family_install(skills)
            after = {
                name: complete_tree_snapshot(skills / name)
                for name in before
            }
            self.assertEqual(after, before)

    def test_cli_rejects_incompatible_modes_before_mutation(self):
        cases = (
            ["--check", "--core-only"],
            ["--check", "--target", "somewhere"],
            ["--check", "--adopt-unmarked"],
            ["--core-only", "--target", "somewhere"],
        )
        for arguments in cases:
            with self.subTest(arguments=arguments), mock.patch(
                "tools.install_skill.install_transaction.transaction_root"
            ) as transaction_root, mock.patch(
                "tools.install_skill.verify_source",
                side_effect=AssertionError("mode validation must precede verification"),
            ):
                self.assertEqual(install_skill.main(arguments), 1)
                transaction_root.assert_not_called()

    def test_family_mode_rejects_legacy_work_root(self):
        with mock.patch("tools.install_skill.install_transaction.transaction_root") as transaction_root:
            self.assertEqual(install_skill.main(["--work-root", "legacy-work"]), 1)
            transaction_root.assert_not_called()


if __name__ == "__main__":
    unittest.main()
