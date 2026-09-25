from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # discoverable from any cwd

from tests.helpers import ready_project


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.studio = self.root / "Documents/Clothing-Shop-Studio"
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
            env={**os.environ, "HOME": str(self.root)},
        )
        return completed, json.loads(completed.stdout)

    def create(self, name: str = "KIKI KAKA") -> Path:
        completed, response = self.run_cli(
            "create_project", {"root": str(self.studio / "projects"), "name": name}
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return Path(response["data"]["project_dir"])

    def asset_dir(self, project: Path, area: str, relative: str) -> Path:
        return self.studio / area / project.name / relative

    def test_create_resume_and_status(self):
        root = self.studio / "projects"
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
            "create_project", {"root": str(self.studio / "projects"), "name": "KIKI KAKA"}
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
        out_dir = self.asset_dir(project, "generated", "concepts/back_typography/r01")
        brief_file = self.root / "briefs.json"
        brief_file.write_text(
            json.dumps({"project_dir": str(project), "output_dir": str(out_dir), "briefs": briefs}), "utf-8"
        )
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
                     "path": str(Path(cards[slot["label"]]).resolve().relative_to(self.studio.resolve())),
                     "renderer": "svg-fallback", "prompt": "Condensed distressed type",
                     "convention_broken": "Type crosses the shoulder seam" if slot["wildcard"] else None}
                    for slot in slots
                ],
            },
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(len(registered["data"]["entries"]), 4)

    def test_render_options_requires_a_project_scoped_destination(self):
        project = self.create()
        briefs = [
            {"label": label, "axis": axis, "title": label, "brief": axis, "garment": "tee",
             "placement": "centre_chest", "colors": ["#111111", "#EEEEEE"]}
            for label, axis in zip("ABCW", ("density", "alignment", "distress", "scale"))
        ]
        completed = subprocess.run(
            [sys.executable, str(self.bundle / "scripts/render-options.py")],
            input=json.dumps({"project_dir": str(project), "output_dir": str(self.root / "outside"), "briefs": briefs}),
            text=True, capture_output=True, check=False, cwd=self.root,
        )
        self.assertEqual(completed.returncode, 3, completed.stderr)
        response = json.loads(completed.stdout)
        self.assertEqual(response["error"]["code"], "unsafe_path")

    def test_render_options_refuses_implicit_overwrite(self):
        project = self.create()
        output = self.asset_dir(project, "generated", "concepts/front_art/r01")
        briefs = [
            {"label": label, "axis": axis, "title": label, "brief": axis, "garment": "tee",
             "placement": "centre_chest", "colors": ["#111111", "#EEEEEE"]}
            for label, axis in zip("ABCW", ("density", "alignment", "distress", "scale"))
        ]
        payload = {"project_dir": str(project), "output_dir": str(output), "briefs": briefs}
        first = subprocess.run(
            [sys.executable, str(self.bundle / "scripts/render-options.py")], input=json.dumps(payload),
            text=True, capture_output=True, check=False, cwd=self.root,
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        second = subprocess.run(
            [sys.executable, str(self.bundle / "scripts/render-options.py")], input=json.dumps(payload),
            text=True, capture_output=True, check=False, cwd=self.root,
        )
        self.assertEqual(second.returncode, 2, second.stderr)
        self.assertEqual(json.loads(second.stdout)["error"]["field"], "overwrite")

    def test_approve_register_master_and_validate(self):
        project = self.create()
        concept_dir = self.asset_dir(project, "generated", "concepts/back_typography/r01")
        concept_dir.mkdir(parents=True)
        results = []
        for label, axis in zip("ABCW", ("density", "alignment", "distress", "scale")):
            (concept_dir / f"option-{label}.svg").write_text(f"<svg><text>{label}</text></svg>", "utf-8")
            results.append({"label": label, "axis": axis, "renderer": "svg-fallback",
                            "path": f"generated/{project.name}/concepts/back_typography/r01/option-{label}.svg",
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

        master = self.asset_dir(project, "production", "masters/back_MASTER.svg")
        master.parent.mkdir(parents=True, exist_ok=True)
        master.write_text("<svg><text>KIKI KAKA</text></svg>", "utf-8")
        completed, registered_master = self.run_cli(
            "register_file",
            {"project_dir": str(project), "origin": "production_master",
             "path": f"production/{project.name}/masters/back_MASTER.svg", "construction": "typeset",
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
        blocked_project = ready_project(
            self.studio, name="Blocked project", assumptions={"quantity": {"confirmed": False}}
        )
        completed, blocked = self.run_cli("export_production_pack", {"project_dir": str(blocked_project)})
        self.assertEqual(completed.returncode, 2)
        self.assertIn("unconfirmed_critical_assumption", [item["code"] for item in blocked["error"]["details"]])

        project = ready_project(self.studio, name="Ready project")
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
        commands = set(schema["properties"]["command"]["enum"]) - {"render_options", "command_error"}
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
        completed, response = self.run_cli(
            "create_project", {"root": str(self.root / "projects"), "name": "Wrong root"}
        )
        self.assertEqual(completed.returncode, 2)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "validation_error")
        self.assertEqual(response["error"]["field"], "root")
        self.assertIn("recovery", response["error"])

    def test_missing_input_file_returns_structured_error(self):
        missing = self.root / "missing-input.json"
        completed = subprocess.run(
            [sys.executable, str(self.script), "status", "--input", str(missing)],
            text=True,
            capture_output=True,
            check=False,
            cwd=self.root,
        )
        self.assertEqual(completed.returncode, 2, completed.stderr)
        response = json.loads(completed.stdout)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "validation_error")
        self.assertEqual(response["error"]["path"], str(missing))

    def test_unexpected_failure_returns_structured_internal_error(self):
        project = self.studio / "projects/broken-project"
        (project / "metadata").mkdir(parents=True)
        (project / "metadata/state.json").write_text('{"schema_version": 1}\n', encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(self.script), "status"],
            input=json.dumps({"project_dir": str(project)}),
            text=True,
            capture_output=True,
            check=False,
            cwd=self.root,
            env={**os.environ, "HOME": str(self.root)},
        )
        self.assertEqual(completed.returncode, 5, completed.stderr)
        response = json.loads(completed.stdout)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "internal_error")
        self.assertNotIn("project_name", response["error"]["message"])

    def test_validate_for_export_includes_export_blockers(self):
        project = ready_project(self.studio, name="Changed answers project")
        self.run_cli(
            "record_answer", {"project_dir": str(project), "field": "base_color", "value": "hot pink"}
        )
        completed, response = self.run_cli(
            "validate", {"project_dir": str(project), "for_export": True}
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse(response["data"]["ok"])
        self.assertIn("approval_answers_changed", [item["code"] for item in response["data"]["errors"]])

    def test_validate_for_export_honours_requested_master_ids(self):
        project = ready_project(self.studio, name="Missing master project")
        completed, response = self.run_cli(
            "validate",
            {
                "project_dir": str(project),
                "for_export": True,
                "master_ids": ["missing-master"],
            },
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse(response["data"]["ok"])
        self.assertIn("master_missing", [item["code"] for item in response["data"]["errors"]])

    def test_render_options_missing_input_is_structured_error(self):
        missing = self.root / "missing-render.json"
        completed = subprocess.run(
            [sys.executable, str(self.bundle / "scripts/render-options.py"), "--input", str(missing)],
            text=True, capture_output=True, check=False, cwd=self.root,
        )
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["error"]["code"], "validation_error")

    def test_create_rejects_payload_config_path_override(self):
        completed, response = self.run_cli(
            "create_project",
            {"root": str(self.root / "projects"), "name": "Unsafe config", "remember_root": True,
             "config_path": str(self.root / "arbitrary.json")},
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(response["error"]["field"], "config_path")

    def test_invalid_or_missing_command_returns_structured_error(self):
        schema = json.loads((self.bundle / "schemas/command-io.schema.json").read_text("utf-8"))
        allowed_commands = schema["properties"]["command"]["enum"]
        for args in ([], ["not-a-command"]):
            completed = subprocess.run(
                [sys.executable, str(self.script), *args],
                input="{}",
                text=True,
                capture_output=True,
                check=False,
                cwd=self.root,
            )
            self.assertEqual(completed.returncode, 2, completed.stderr)
            response = json.loads(completed.stdout)
            self.assertFalse(response["ok"])
            self.assertEqual(response["error"]["field"], "command")
            self.assertIn(response["command"], allowed_commands)

    def test_render_options_invalid_argument_returns_structured_error(self):
        completed = subprocess.run(
            [sys.executable, str(self.bundle / "scripts/render-options.py"), "--not-a-real-flag"],
            input="{}",
            text=True,
            capture_output=True,
            check=False,
            cwd=self.root,
        )
        self.assertEqual(completed.returncode, 2, completed.stderr)
        response = json.loads(completed.stdout)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["field"], "arguments")

    def test_presentation_commands_are_wired_and_structured(self):
        project = ready_project(self.studio, name="Presentation project")
        completed, response = self.run_cli("create_models", {"project_dir": str(project), "mode": "install_defaults"})
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(len(response["data"]["installed"]), 4)
        for command in ("extract", "create_models", "try_on", "create_listing"):
            completed, response = self.run_cli(command, {"project_dir": str(project), "mode": "bogus"})
            self.assertEqual(completed.returncode, 2, command)
            self.assertEqual(response["command"], command)
            self.assertEqual(response["error"]["field"], "mode")
        completed, response = self.run_cli("create_listing", {"project_dir": str(project), "mode": "build",
                                                              "version": "v001"})
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("white_background", response["data"]["missing"])
        schema = json.loads((self.bundle / "schemas/command-io.schema.json").read_text("utf-8"))
        names = schema["properties"]["command"]["enum"]
        for command in ("extract", "create_models", "try_on", "create_listing"):
            self.assertIn(command, names)

    def test_create_listing_cli_uses_the_recorded_project_name(self):
        project = ready_project(self.studio, name="Names project")
        completed, response = self.run_cli("create_listing", {"project_dir": str(project), "mode": "build",
                                                              "version": "v001",
                                                              "design_name": "Silk Luxe Premium Cashmere Blend"})
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(response["command"], "create_listing")
        self.assertEqual(response["error"]["field"], "design_name")
        completed, response = self.run_cli("create_listing", {"project_dir": str(project), "mode": "build",
                                                              "version": "v001"})
        self.assertEqual(completed.returncode, 0, completed.stderr)
        html = (self.studio / response["data"]["files"]["html"]).read_text("utf-8")
        self.assertIn("Names project", html)

if __name__ == "__main__":
    unittest.main()
