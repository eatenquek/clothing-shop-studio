from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import run_codex_family_eval
from tools.family_manifest import load_manifest


REPO = Path(__file__).resolve().parents[1]


class CodexFamilyEvalIsolationTests(unittest.TestCase):
    def test_environment_nests_codex_and_studio_under_throwaway_home(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder) / "workspace"
            env, codex_home, studio_root = run_codex_family_eval.evaluation_environment(
                workspace,
                {"HOME": "real-home", "CODEX_HOME": "real-codex", "KEEP": "yes"},
            )
            self.assertEqual(Path(env["HOME"]), workspace.resolve() / "home")
            self.assertEqual(Path(env["CODEX_HOME"]), workspace.resolve() / "home/.codex")
            self.assertEqual(codex_home, Path(env["CODEX_HOME"]))
            self.assertEqual(
                studio_root,
                workspace.resolve() / "home/Documents/Clothing-Shop-Studio",
            )
            self.assertEqual(env["KEEP"], "yes")

    def test_real_boundary_snapshot_hashes_only_six_studio_data_folders(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            studio = home / "Documents/Clothing-Shop-Studio"
            (studio / "projects/demo").mkdir(parents=True)
            (studio / "projects/demo/state.json").write_text("one", encoding="utf-8")
            (studio / "source").mkdir()
            (studio / "source/ignored.txt").write_text("ignored", encoding="utf-8")
            (home / ".codex/skills/example").mkdir(parents=True)
            before = run_codex_family_eval.real_boundary_snapshot(home)
            (studio / "source/ignored.txt").write_text("changed", encoding="utf-8")
            self.assertEqual(run_codex_family_eval.real_boundary_snapshot(home), before)
            (studio / "projects/demo/state.json").write_text("two", encoding="utf-8")
            self.assertNotEqual(run_codex_family_eval.real_boundary_snapshot(home), before)

    def test_real_boundary_snapshot_detects_empty_root_and_data_folder_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            before = run_codex_family_eval.real_boundary_snapshot(home)
            studio = home / "Documents/Clothing-Shop-Studio"
            studio.mkdir(parents=True)
            after_root = run_codex_family_eval.real_boundary_snapshot(home)
            self.assertNotEqual(after_root, before)
            for name in run_codex_family_eval.STUDIO_DATA_FOLDERS:
                with self.subTest(folder=name):
                    previous = run_codex_family_eval.real_boundary_snapshot(home)
                    (studio / name).mkdir()
                    self.assertNotEqual(
                        run_codex_family_eval.real_boundary_snapshot(home), previous
                    )

    def test_prepare_auth_requires_environment_key_without_subprocess(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch(
            "tools.run_codex_family_eval.subprocess.run"
        ) as run:
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
                run_codex_family_eval.prepare_auth({}, "codex", Path(folder))
            run.assert_not_called()

    def test_prepare_auth_prefers_environment_only_success(self):
        completed = mock.Mock(returncode=0, stdout="ok", stderr="")
        with tempfile.TemporaryDirectory() as folder, mock.patch(
            "tools.run_codex_family_eval.subprocess.run", return_value=completed
        ) as run:
            mechanism = run_codex_family_eval.prepare_auth(
                {"OPENAI_API_KEY": "test-secret"}, "codex", Path(folder)
            )
            self.assertEqual(mechanism, "environment")
            self.assertEqual(run.call_count, 1)
            self.assertNotIn("test-secret", " ".join(run.call_args.args[0]))

    def test_prepare_auth_falls_back_to_throwaway_login_only_for_auth_failure(self):
        unauthenticated = mock.Mock(returncode=1, stdout="", stderr="not logged in")
        logged_in = mock.Mock(returncode=0, stdout="login ok", stderr="")
        retry = mock.Mock(returncode=0, stdout="ok", stderr="")
        with tempfile.TemporaryDirectory() as folder, mock.patch(
            "tools.run_codex_family_eval.subprocess.run",
            side_effect=[unauthenticated, logged_in, retry],
        ) as run:
            mechanism = run_codex_family_eval.prepare_auth(
                {"OPENAI_API_KEY": "test-secret"}, "codex", Path(folder)
            )
            self.assertEqual(mechanism, "throwaway-auth-json")
            self.assertEqual(run.call_args_list[1].kwargs["input"], "test-secret\n")

    def test_prepare_auth_reports_login_failure_without_exposing_key(self):
        unauthenticated = mock.Mock(returncode=1, stdout="", stderr="unauthorized")
        failed = mock.Mock(returncode=1, stdout="", stderr="login failed")
        with tempfile.TemporaryDirectory() as folder, mock.patch(
            "tools.run_codex_family_eval.subprocess.run",
            side_effect=[unauthenticated, failed],
        ):
            with self.assertRaisesRegex(RuntimeError, "throwaway Codex login failed") as caught:
                run_codex_family_eval.prepare_auth(
                    {"OPENAI_API_KEY": "test-secret"}, "codex", Path(folder)
                )
            self.assertNotIn("test-secret", str(caught.exception))

    def test_redaction_removes_exact_and_key_shaped_secrets(self):
        text = "OPENAI_API_KEY=test-secret token sk-example1234567890"
        redacted = run_codex_family_eval.redact(text, ["test-secret"])
        self.assertNotIn("test-secret", redacted)
        self.assertNotIn("sk-example", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_seed_fixture_uses_studio_commands_in_throwaway_home(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder) / "workspace"
            env, _codex_home, studio = run_codex_family_eval.evaluation_environment(
                workspace, dict(os.environ)
            )
            fixture = workspace / "fixture.json"
            fixture.parent.mkdir(parents=True, exist_ok=True)
            fixture.write_text(json.dumps({"commands": [
                {"command": "create_project", "payload": {
                    "root": "${STUDIO_ROOT}/projects", "name": "Fixture Project"
                }},
                {"command": "record_answer", "payload": {
                    "project_dir": "${STUDIO_ROOT}/projects/fixture-project",
                    "field": "reference_image", "value": None
                }},
            ]}), encoding="utf-8")
            scenario = {"fixture": str(fixture)}
            project = run_codex_family_eval.seed_fixture(
                scenario, env, REPO / "skill/clothing-shop-studio"
            )
            self.assertEqual(project, studio / "projects/fixture-project")
            self.assertTrue((project / "metadata/state.json").is_file())

    def test_checked_in_family_fixtures_seed_approved_and_reference_state(self):
        cases = (
            ("approved-owned-project.json", "approved-owned-garment", "approvals"),
            ("presentation-project.json", "presentation-project", "files"),
        )
        for filename, slug, populated_key in cases:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as folder:
                workspace = Path(folder) / "workspace"
                env, _codex_home, _studio = run_codex_family_eval.evaluation_environment(
                    workspace, dict(os.environ)
                )
                scenario = {
                    "fixture": str(REPO / "evals/fixtures/family" / filename)
                }
                project = run_codex_family_eval.seed_fixture(
                    scenario, env, REPO / "skill/clothing-shop-studio"
                )
                self.assertEqual(project.name, slug)
                state = json.loads((project / "metadata/state.json").read_text("utf-8"))
                self.assertTrue(state[populated_key])

    def test_main_missing_key_leaves_no_output_or_auth_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scenario = root / "scenario.json"
            out = root / "out/evidence.md"
            scenario.write_text(json.dumps({
                "id": "missing-key", "skill": "clothing-resume", "query": "test",
                "seed": [], "followups": [], "assertions": []
            }), encoding="utf-8")
            with mock.patch.dict(os.environ, {"HOME": str(root / "real-home")}, clear=True):
                self.assertEqual(run_codex_family_eval.main([str(scenario), "--out", str(out)]), 1)
            self.assertFalse(out.exists())
            self.assertFalse(any(path.name == "auth.json" for path in root.rglob("auth.json")))

    def test_run_isolated_removes_throwaway_workspace_on_success_and_failure(self):
        scenario = {
            "id": "cleanup", "skill": "clothing-resume", "query": "test",
            "seed": [], "followups": [], "assertions": [],
        }
        for failure in (False, True):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                source = Path(folder) / "Clothing-Shop-Studio/source"
                work = source.parent / ".work"
                source.mkdir(parents=True)
                install = mock.Mock(returncode=0, stdout="installed", stderr="")
                def turn_effect(*_args, **_kwargs):
                    if failure:
                        raise RuntimeError("turn failed")
                    return {"thread_id": "thread", "text": "done", "tools": []}
                with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-secret"}, clear=True), mock.patch.object(
                    run_codex_family_eval, "REPO_ROOT", source
                ), mock.patch(
                    "tools.run_codex_family_eval.subprocess.run", return_value=install
                ), mock.patch(
                    "tools.run_codex_family_eval.prepare_auth", return_value="environment"
                ), mock.patch(
                    "tools.run_codex_family_eval.seed_fixture", return_value=Path("project")
                ), mock.patch(
                    "tools.run_codex_family_eval.run_codex_turn", side_effect=turn_effect
                ), mock.patch(
                    "tools.run_codex_family_eval._installed_hashes", return_value={"clothing-shop-studio": "hash"}
                ):
                    if failure:
                        with self.assertRaisesRegex(RuntimeError, "turn failed"):
                            run_codex_family_eval.run_isolated(scenario, "codex", Path(folder))
                    else:
                        transcript = run_codex_family_eval.run_isolated(scenario, "codex", Path(folder))
                        self.assertIn("Authentication: `environment`", transcript)
                self.assertEqual(list(work.iterdir()), [])

    def test_main_success_writes_only_explicit_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scenario = root / "scenario.json"
            out = root / "evidence/result.md"
            scenario.write_text(json.dumps({
                "id": "success", "skill": "clothing-resume", "query": "Use $clothing-resume",
                "seed": [], "followups": [], "assertions": []
            }), encoding="utf-8")
            with mock.patch.dict(
                os.environ,
                {"HOME": str(root / "real-home"), "OPENAI_API_KEY": "test-secret"},
                clear=True,
            ), mock.patch(
                "tools.run_codex_family_eval.real_boundary_snapshot", return_value={"same": True}
            ), mock.patch(
                "tools.run_codex_family_eval.run_isolated", return_value="evidence\n"
            ):
                self.assertEqual(
                    run_codex_family_eval.main([str(scenario), "--out", str(out)]), 0
                )
            self.assertEqual(out.read_text("utf-8"), "evidence\n")
            self.assertEqual(
                sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()),
                ["evidence/result.md", "scenario.json"],
            )


class CodexFamilyScenarioTests(unittest.TestCase):
    def test_all_six_scenarios_validate_against_the_family_manifest(self):
        manifest = load_manifest(REPO)
        scenario_dir = REPO / "evals/family"
        expected = {
            "approve-requires-reply.json",
            "extract-requires-consent.json",
            "resume-lists-canonical-projects.json",
            "try-on-refuses-shopper-garment.json",
            "listing-refuses-price-publish.json",
            "visual-notice-one-question.json",
        }
        self.assertEqual({path.name for path in scenario_dir.glob("*.json")}, expected)
        for path in sorted(scenario_dir.glob("*.json")):
            scenario = run_codex_family_eval._resolve_scenario(path)
            run_codex_family_eval.validate_scenario(scenario, manifest)

    def test_scenario_validation_rejects_unknown_skill_and_assertion(self):
        manifest = load_manifest(REPO)
        base = {
            "id": "bad", "skill": "clothing-unknown", "query": "Use $clothing-unknown",
            "seed": [], "followups": [], "assertions": [],
        }
        with self.assertRaisesRegex(RuntimeError, "unknown family skill"):
            run_codex_family_eval.validate_scenario(base, manifest)
        base["skill"] = "clothing-resume"
        base["query"] = "Use $clothing-resume"
        base["assertions"] = [{"type": "invented", "value": "x"}]
        with self.assertRaisesRegex(RuntimeError, "unknown assertion"):
            run_codex_family_eval.validate_scenario(base, manifest)

    def test_all_assertion_types_are_evaluated(self):
        scenario = {
            "assertions": [
                {"type": "contains", "value": "consent"},
                {"type": "not_contains", "value": "forbidden"},
                {"type": "tool_called", "value": "studio.py extract"},
                {"type": "tool_not_called", "value": "imagegen"},
                {"type": "exactly_one_question"},
                {
                    "type": "seller_notice_after_visual",
                    "visual": "Option W",
                    "notice": "Singapore seller note",
                },
            ]
        }
        turns = [{
            "text": "Option W\nSingapore seller note\nDo you consent?",
            "tools": ["python studio.py extract"],
        }]
        results = run_codex_family_eval.evaluate_assertions(scenario, turns)
        self.assertTrue(all(item["passed"] for item in results), results)

    def test_scenario_prompts_cannot_supply_approval_or_consent(self):
        manifest = load_manifest(REPO)
        for prompt in (
            "Use $clothing-approve. Yes, approved.",
            "Use $clothing-extract and I consent to sending it.",
            "Use $clothing-approve, go ahead.",
        ):
            scenario = {
                "id": "bad", "skill": prompt.split("$")[1].split()[0].rstrip(",."),
                "query": prompt, "seed": [], "followups": [], "assertions": [],
            }
            with self.subTest(prompt=prompt):
                with self.assertRaisesRegex(RuntimeError, "approval or consent"):
                    run_codex_family_eval.validate_scenario(scenario, manifest)
        followup = {
            "id": "bad", "skill": "clothing-resume", "query": "Use $clothing-resume",
            "seed": [], "followups": ["yes"], "assertions": [],
        }
        with self.assertRaisesRegex(RuntimeError, "approval or consent"):
            run_codex_family_eval.validate_scenario(followup, manifest)

    def test_scenario_must_name_its_own_skill_entry(self):
        manifest = load_manifest(REPO)
        scenario = {
            "id": "bad", "skill": "clothing-resume", "query": "continue my design",
            "seed": [], "followups": [], "assertions": [],
        }
        with self.assertRaisesRegex(RuntimeError, r"\$clothing-resume"):
            run_codex_family_eval.validate_scenario(scenario, manifest)

    def test_every_scenario_seeds_deterministically_in_throwaway_home(self):
        for path in sorted((REPO / "evals/family").glob("*.json")):
            with self.subTest(scenario=path.name), tempfile.TemporaryDirectory() as folder:
                env, _codex_home, studio = run_codex_family_eval.evaluation_environment(
                    Path(folder) / "workspace", dict(os.environ)
                )
                scenario = run_codex_family_eval._resolve_scenario(path)
                run_codex_family_eval.seed_fixture(
                    scenario, env, REPO / "skill/clothing-shop-studio"
                )
                self.assertTrue(any((studio / "projects").iterdir()))

    def test_resume_fixture_has_two_projects_and_approve_fixture_is_unapproved(self):
        with tempfile.TemporaryDirectory() as folder:
            env, _codex_home, studio = run_codex_family_eval.evaluation_environment(
                Path(folder) / "workspace", dict(os.environ)
            )
            run_codex_family_eval.seed_fixture(
                run_codex_family_eval._resolve_scenario(
                    REPO / "evals/family/resume-lists-canonical-projects.json"
                ),
                env, REPO / "skill/clothing-shop-studio",
            )
            self.assertEqual(
                sorted(p.name for p in (studio / "projects").iterdir()),
                ["alpha-tee", "beta-hoodie"],
            )
        with tempfile.TemporaryDirectory() as folder:
            env, _codex_home, studio = run_codex_family_eval.evaluation_environment(
                Path(folder) / "workspace", dict(os.environ)
            )
            project = run_codex_family_eval.seed_fixture(
                run_codex_family_eval._resolve_scenario(
                    REPO / "evals/family/approve-requires-reply.json"
                ),
                env, REPO / "skill/clothing-shop-studio",
            )
            state = json.loads((project / "metadata/state.json").read_text("utf-8"))
            self.assertFalse(state["approvals"])
            self.assertTrue(state["concepts"] if "concepts" in state else state["files"])

    def test_transcript_records_assertion_results(self):
        scenario = {"id": "x", "skill": "clothing-resume", "query": "Use $clothing-resume",
                    "followups": []}
        results = [{"type": "contains", "value": "a", "passed": True}]
        text = run_codex_family_eval._transcript(
            scenario, "environment", {"clothing-shop-studio": "h"},
            [{"text": "a", "tools": []}], results,
        )
        self.assertIn("## Assertions", text)
        self.assertIn("PASS `contains`", text)

    def test_failed_assertion_raises_with_type_and_value(self):
        scenario = {"assertions": [{"type": "contains", "value": "approval required"}]}
        with self.assertRaisesRegex(RuntimeError, "contains.*approval required"):
            run_codex_family_eval.evaluate_assertions(
                scenario, [{"text": "No match", "tools": []}]
            )


if __name__ == "__main__":
    unittest.main()
