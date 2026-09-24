from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # discoverable from any cwd

from tests.helpers import ready_project


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

    def test_generate_options_plan_render_and_register(self):
        project = self.create()
        _, planned = self.run_cli(
            "generate_options",
            {
                "project_dir": str(project),
                "mode": "plan",
                "decision_id": "back_typography",
                "axes": ["density", "alignment", "distress", "scale"],
                "constraints": {"colors": 1},
            },
        )
        slots = planned["data"]["slots"]
        self.assertEqual([slot["label"] for slot in slots], ["A", "B", "C", "W"])

        briefs = [
            {"label": slot["label"], "axis": slot["axis"], "title": f"Option {slot['label']}",
             "brief": "Condensed distressed type", "garment": "long_sleeve",
             "placement": "upper_back", "colors": ["#111111", "#EEEEEE"]}
            for slot in slots
        ]
        out_dir = project / "concepts/generated/back_typography/r01"
        brief_file = self.root / "briefs.json"
        brief_file.write_text(json.dumps({"output_dir": str(out_dir), "briefs": briefs}), "utf-8")
        rendered = subprocess.run(
            [sys.executable, str(self.bundle / "scripts/render-options.py"), "--input", str(brief_file)],
            text=True, capture_output=True, check=False, cwd=self.root,
        )
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        cards = json.loads(rendered.stdout)["data"]["cards"]
        self.assertTrue(Path(json.loads(rendered.stdout)["data"]["contact_sheet"]).is_file())

        completed, registered = self.run_cli(
            "generate_options",
            {
                "project_dir": str(project),
                "mode": "register",
                "decision_id": "back_typography",
                "results": [
                    {"label": slot["label"], "axis": slot["axis"],
                     "path": str(Path(cards[slot["label"]]).relative_to(project)),
                     "renderer": "svg-fallback", "prompt": "Condensed distressed type",
                     "convention_broken": "Type crosses the shoulder seam" if slot["wildcard"] else None}
                    for slot in slots
                ],
            },
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(len(registered["data"]["entries"]), 4)

    def test_approve_register_master_and_validate(self):
        project = self.create()
        concept_dir = project / "concepts/generated/back_typography/r01"
        concept_dir.mkdir(parents=True)
        results = []
        for label, axis in zip("ABCW", ("density", "alignment", "distress", "scale")):
            (concept_dir / f"option-{label}.svg").write_text(f"<svg><text>{label}</text></svg>", "utf-8")
            results.append({"label": label, "axis": axis, "renderer": "svg-fallback",
                            "path": f"concepts/generated/back_typography/r01/option-{label}.svg",
                            "convention_broken": "Crosses the seam" if label == "W" else None})
        _, registered = self.run_cli(
            "generate_options",
            {"project_dir": str(project), "mode": "register", "decision_id": "back_typography", "results": results},
        )
        concept_a = registered["data"]["entries"][0]["id"]

        completed, approved = self.run_cli(
            "approve_design",
            {"project_dir": str(project), "concept_ids": [concept_a], "statement": "Approve option A"},
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(approved["data"]["version"], "v001")

        master = project / "production/masters/back_MASTER.svg"
        master.parent.mkdir(parents=True)
        master.write_text("<svg><text>KIKI KAKA</text></svg>", "utf-8")
        completed, registered_master = self.run_cli(
            "register_file",
            {"project_dir": str(project), "origin": "production_master",
             "path": "production/masters/back_MASTER.svg", "construction": "typeset",
             "approved_version": "v001"},
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

        completed, report = self.run_cli(
            "validate", {"project_dir": str(project), "master_ids": [registered_master["data"]["id"]]}
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(report["data"]["errors"], [])

        _, state = self.run_cli("status", {"project_dir": str(project)})
        self.assertEqual(state["data"]["approved_versions"], ["v001"])
        self.assertEqual(state["data"]["blockers"], [])

    def test_export_production_pack_reports_pack_or_blockers(self):
        blocked_project = ready_project(self.root / "blocked", assumptions={"quantity": {"confirmed": False}})
        completed, blocked = self.run_cli("export_production_pack", {"project_dir": str(blocked_project)})
        self.assertEqual(completed.returncode, 2)
        self.assertIn("unconfirmed_critical_assumption", [item["code"] for item in blocked["error"]["details"]])

        project = ready_project(self.root / "ready")
        completed, response = self.run_cli("export_production_pack", {"project_dir": str(project)})
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(response["data"]["pack_version"], "pack-v001")
        self.assertTrue(Path(response["data"]["path"], "production-spec.md").is_file())

    def test_generate_options_rejects_unknown_mode(self):
        project = self.create()
        completed, response = self.run_cli(
            "generate_options", {"project_dir": str(project), "mode": "describe"}
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(response["error"]["field"], "mode")

    def test_every_schema_command_dispatches(self):
        schema = json.loads((self.bundle / "schemas/command-io.schema.json").read_text("utf-8"))
        commands = set(schema["properties"]["command"]["enum"]) - {"render_options"}
        for command in sorted(commands):
            completed, response = self.run_cli(command, {})
            self.assertEqual(response["command"], command)
            self.assertFalse(response["ok"], command)  # an empty payload is always incomplete
            self.assertEqual(completed.returncode, 2, command)
        help_text = subprocess.run(
            [sys.executable, str(self.script), "--help"], text=True, capture_output=True, check=False
        ).stdout
        listed = set(help_text.split("{", 1)[1].split("}", 1)[0].split(","))
        self.assertEqual(listed, commands)

    def test_structured_validation_error(self):
        completed, response = self.run_cli("create_project", {"name": "Missing root"})
        self.assertEqual(completed.returncode, 2)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "validation_error")
        self.assertEqual(response["error"]["field"], "root")
        self.assertIn("recovery", response["error"])


if __name__ == "__main__":
    unittest.main()
