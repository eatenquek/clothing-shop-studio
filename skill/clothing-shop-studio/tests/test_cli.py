from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bundle = Path(__file__).resolve().parents[1]
        self.script = self.bundle / "scripts/studio.py"

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, command: str, payload: dict) -> tuple[subprocess.CompletedProcess, dict]:
        completed = subprocess.run(
            [sys.executable, str(self.script), command],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            check=False,
        )
        return completed, json.loads(completed.stdout)

    def test_create_resume_and_status(self):
        root = self.root / "projects"
        completed, response = self.run_cli(
            "create_project", {"root": str(root), "name": "KIKI KAKA"}
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(response["ok"])
        project = root / "kiki-kaka"

        resumed, resume_response = self.run_cli(
            "resume_project", {"project_dir": str(project)}
        )
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(resume_response["data"]["project_name"], "KIKI KAKA")

        status, status_response = self.run_cli("status", {"project_dir": str(project)})
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(status_response["data"]["phase"], "intake")

    def test_structured_validation_error(self):
        completed, response = self.run_cli("create_project", {"name": "Missing root"})
        self.assertEqual(completed.returncode, 2)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "validation_error")
        self.assertEqual(response["error"]["field"], "root")
        self.assertIn("recovery", response["error"])


if __name__ == "__main__":
    unittest.main()
