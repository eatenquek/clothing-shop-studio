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
        # Run from an unrelated directory so bundle-relative data loading is exercised.
        completed = subprocess.run(
            [sys.executable, str(self.script), command],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            check=False,
            cwd=self.root,
        )
        return completed, json.loads(completed.stdout)

    def create(self, name: str = "KIKI KAKA") -> Path:
        completed, response = self.run_cli(
            "create_project", {"root": str(self.root / "projects"), "name": name}
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return Path(response["data"]["project_dir"])

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

    def test_create_and_resume_return_first_unanswered_question(self):
        completed, response = self.run_cli(
            "create_project", {"root": str(self.root / "projects"), "name": "KIKI KAKA"}
        )
        self.assertEqual(response["data"]["next_question"]["id"], "reference_image")
        _, resumed = self.run_cli(
            "resume_project", {"project_dir": response["data"]["project_dir"]}
        )
        self.assertEqual(resumed["data"]["next_question"]["id"], "reference_image")

    def test_record_answer_declines_reference_and_returns_one_question(self):
        project = self.create()
        completed, response = self.run_cli(
            "record_answer",
            {"project_dir": str(project), "field": "reference_image", "value": None},
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(response["ok"])
        data = response["data"]
        self.assertIsInstance(data["next_question"], dict)
        self.assertEqual(data["next_question"]["id"], "garment_category")
        self.assertEqual(data["state"]["answers"]["reference_status"], "none")
        events = (project / "metadata/decisions.jsonl").read_text("utf-8").splitlines()
        self.assertEqual(len(events), 2)
        self.assertEqual(json.loads(events[-1])["field"], "reference_image")

        _, followup = self.run_cli(
            "record_answer",
            {"project_dir": str(project), "field": "garment_category", "value": "long_sleeve"},
        )
        asked = followup["data"]["next_question"]["id"]
        self.assertNotIn(asked, {"reference_image", "garment_category"})

    def test_record_answer_keeps_inferred_value_in_assumptions_register(self):
        project = self.create()
        _, response = self.run_cli(
            "record_answer",
            {
                "project_dir": str(project),
                "field": "handfeel",
                "value": "dry, matte",
                "source": "inferred",
                "evidence": "Utilitarian streetwear brief",
                "confirmed": False,
            },
        )
        register = {item["field"]: item for item in response["data"]["state"]["assumptions"]}
        self.assertEqual(register["handfeel"]["source"], "inferred")
        self.assertFalse(register["handfeel"]["confirmed"])
        self.assertEqual(register["handfeel"]["evidence"], "Utilitarian streetwear brief")

    def test_record_answer_rejects_unknown_source(self):
        project = self.create()
        completed, response = self.run_cli(
            "record_answer",
            {"project_dir": str(project), "field": "fit", "value": "boxy", "source": "reference_text"},
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(response["error"]["field"], "source")
        events = (project / "metadata/decisions.jsonl").read_text("utf-8").splitlines()
        self.assertEqual(len(events), 1)

    def test_structured_validation_error(self):
        completed, response = self.run_cli("create_project", {"name": "Missing root"})
        self.assertEqual(completed.returncode, 2)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "validation_error")
        self.assertEqual(response["error"]["field"], "root")
        self.assertIn("recovery", response["error"])


if __name__ == "__main__":
    unittest.main()
