from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # discoverable from any cwd

from scripts.studio_core.errors import StorageError, UnsafePathError
from scripts.studio_core.store import append_event, create_project, load_state
from tests.helpers import FIXED_NOW, make_project


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.skill_dir = self.root / "installed-skill"
        self.skill_dir.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_create_project_writes_external_canonical_state(self):
        state = create_project(self.root / "projects", "鬼-kiki kaka", self.skill_dir, FIXED_NOW)
        project = self.root / "projects" / "鬼-kiki-kaka"
        self.assertEqual(state["schema_version"], 1)
        self.assertTrue((project / "metadata/state.json").is_file())
        self.assertEqual(load_state(project)["project_name"], "鬼-kiki kaka")
        self.assertTrue((project / "project.yaml").is_file())
        self.assertTrue((project / "decisions.md").is_file())
        for relative in (
            "references/user",
            "references/online",
            "concepts/generated",
            "designs/approved",
            "production",
        ):
            self.assertTrue((project / relative).is_dir(), relative)

    def test_rejects_symlink_into_skill(self):
        escape = self.root / "escape"
        escape.symlink_to(self.skill_dir, target_is_directory=True)
        with self.assertRaises(UnsafePathError):
            create_project(escape, "bad", self.skill_dir, FIXED_NOW)

    def test_failed_replace_preserves_previous_state(self):
        project = make_project(self.root)
        before = (project / "metadata/state.json").read_bytes()
        with mock.patch("os.replace", side_effect=OSError("disk failure")):
            with self.assertRaises(StorageError):
                append_event(
                    project,
                    {"type": "answer", "field": "fit", "value": "boxy"},
                    FIXED_NOW,
                )
        self.assertEqual((project / "metadata/state.json").read_bytes(), before)

    def test_answer_event_updates_state_and_readable_views(self):
        project = make_project(self.root)
        state = append_event(
            project,
            {"type": "answer", "field": "fit", "value": "boxy"},
            FIXED_NOW,
        )
        self.assertEqual(state["answers"]["fit"], "boxy")
        self.assertIn('"boxy"', (project / "project.yaml").read_text("utf-8"))
        self.assertIn("fit", (project / "decisions.md").read_text("utf-8"))
        events = [json.loads(line) for line in (project / "metadata/decisions.jsonl").read_text("utf-8").splitlines()]
        self.assertEqual(events[-1]["field"], "fit")

    def test_append_refuses_to_build_on_hand_edited_state(self):
        project = make_project(self.root)
        state_path = project / "metadata/state.json"
        state = json.loads(state_path.read_text("utf-8"))
        state["phase"] = "approved"
        state_path.write_text(json.dumps(state), "utf-8")
        tampered = state_path.read_bytes()
        with self.assertRaises(StorageError):
            append_event(project, {"type": "answer", "field": "fit", "value": "boxy"}, FIXED_NOW)
        self.assertEqual(state_path.read_bytes(), tampered)
        self.assertEqual(len((project / "metadata/decisions.jsonl").read_text("utf-8").splitlines()), 1)

    def test_answer_event_matches_interview_assumption_register(self):
        project = make_project(self.root)
        append_event(project, {"type": "answer", "field": "reference_image", "value": None}, FIXED_NOW)
        state = append_event(
            project,
            {
                "type": "answer",
                "field": "stretch",
                "value": "mechanical stretch",
                "source": "inferred",
                "evidence": "Performance brief",
                "confirmed": False,
            },
            FIXED_NOW,
        )
        self.assertEqual(state["answers"]["reference_status"], "none")
        register = {item["field"]: item for item in state["assumptions"]}
        self.assertEqual(
            register["stretch"],
            {
                "field": "stretch",
                "value": "mechanical stretch",
                "source": "inferred",
                "evidence": "Performance brief",
                "confirmed": False,
                "critical": False,
            },
        )
        # Resuming from disk yields the same register as the in-memory result.
        self.assertEqual(load_state(project)["assumptions"], state["assumptions"])


if __name__ == "__main__":
    unittest.main()
