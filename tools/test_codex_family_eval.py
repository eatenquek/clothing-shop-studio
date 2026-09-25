from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import run_codex_family_eval


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
                "id": "success", "skill": "clothing-resume", "query": "test",
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


if __name__ == "__main__":
    unittest.main()
