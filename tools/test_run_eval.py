from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools import run_eval


class RunEvalIsolationTests(unittest.TestCase):
    def test_eval_environment_uses_throwaway_home_and_matching_project_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder) / "eval-run"
            env, projects = run_eval.evaluation_environment(
                workspace, {"HOME": "/Users/example", "KEEP_ME": "yes"}
            )

            expected_home = workspace / "home"
            self.assertEqual(Path(env["HOME"]), expected_home.resolve())
            self.assertEqual(env["KEEP_ME"], "yes")
            self.assertNotIn("CLOTHING_SHOP_STUDIO_HOME", env)
            self.assertEqual(
                projects.resolve(),
                (expected_home / "Documents/Clothing-Shop-Studio/projects").resolve(),
            )

    def test_eval_workspace_lives_under_the_studio_work_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            studio_root = Path(folder) / "Clothing-Shop-Studio"
            workspace = run_eval.create_eval_workspace(studio_root)
            self.assertEqual(workspace.parent, (studio_root / ".work/evals").resolve())


if __name__ == "__main__":
    unittest.main()
