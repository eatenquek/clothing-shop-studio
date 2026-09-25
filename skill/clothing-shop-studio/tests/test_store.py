from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # discoverable from any cwd

from scripts.studio_core.errors import StorageError, UnsafePathError, ValidationError
from scripts.studio_core.store import (
    _load_events,
    _seal,
    append_event,
    create_project,
    load_state,
    replay_state,
)
from scripts.studio_core.validation import validate_project
from scripts.studio_core.views import render_decisions_md, render_manifest, render_project_yaml
from tests.helpers import FIXED_NOW, make_project, ready_project


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
        self.assertEqual(state["schema_version"], 2)
        self.assertEqual(state["layout_version"], 2)
        self.assertEqual(state["path_base"], "studio_root")
        self.assertTrue((project / "metadata/state.json").is_file())
        self.assertEqual(load_state(project)["project_name"], "鬼-kiki kaka")
        self.assertTrue((project / "project.yaml").is_file())
        self.assertTrue((project / "decisions.md").is_file())
        self.assertEqual({path.name for path in project.iterdir()}, {"metadata", "project.yaml", "decisions.md"})
        for relative in ("references/鬼-kiki-kaka/user", "generated/鬼-kiki-kaka/concepts",
                         "approved/鬼-kiki-kaka", "production/鬼-kiki-kaka", "exports/鬼-kiki-kaka"):
            self.assertTrue((self.root / relative).is_dir(), relative)

    def test_rejects_symlink_into_skill(self):
        escape = self.root / "escape"
        escape.symlink_to(self.skill_dir, target_is_directory=True)
        with self.assertRaises(ValidationError):
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

    def test_legacy_contact_sheet_event_remains_writable_and_warns(self):
        project = make_project(self.root)
        sheet = project / "concepts/generated/legacy/r01/contact-sheet.svg"
        sheet.parent.mkdir(parents=True)
        sheet.write_text("<svg/>", encoding="utf-8")
        state = append_event(
            project,
            {
                "type": "options_registered",
                "decision_id": "legacy",
                "round": 1,
                "entries": [],
                "contact_sheet": "concepts/generated/legacy/r01/contact-sheet.svg",
            },
            FIXED_NOW,
        )

        self.assertNotIn("contact_sheet_sha256", state["concepts"][0])
        report = validate_project(project)
        self.assertNotIn("state_tampered", [item["code"] for item in report["errors"]])
        self.assertNotIn("contact_sheet_hash_mismatch", [item["code"] for item in report["errors"]])
        self.assertIn("legacy_contact_sheet_unhashed", [item["code"] for item in report["warnings"]])

        updated = append_event(
            project,
            {"type": "answer", "field": "fit", "value": "boxy"},
            FIXED_NOW,
        )
        self.assertEqual(updated["answers"]["fit"], "boxy")

    def test_legacy_japanese_confirmation_can_be_reconfirmed_after_upgrade(self):
        project = make_project(self.root)
        events = _load_events(project)
        legacy = _seal(
            {
                "type": "answer",
                "field": "confirm_japanese_text_and_motif",
                "value": "Legacy text confirmation",
                "source": "user",
                "confirmed": True,
                "user_quote": "Legacy text confirmation",
                "timestamp": FIXED_NOW,
            },
            events[-1]["event_hash"],
        )
        events.append(legacy)
        state = replay_state(events)
        (project / "metadata/decisions.jsonl").write_text(
            "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in events),
            encoding="utf-8",
        )
        (project / "metadata/state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (project / "metadata/manifest.json").write_text(render_manifest(state), encoding="utf-8")
        (project / "project.yaml").write_text(render_project_yaml(state), encoding="utf-8")
        (project / "decisions.md").write_text(render_decisions_md(events), encoding="utf-8")

        updated = append_event(
            project,
            {
                "type": "answer",
                "field": "confirm_japanese_text_and_motif",
                "value": {
                    "approved": True,
                    "text": "判定",
                    "reading": "hantei",
                    "meaning": "judgment",
                    "motif": "original talisman",
                },
                "source": "user",
                "confirmed": True,
                "user_quote": "I confirm 判定, hantei, judgment, and the original talisman.",
            },
            FIXED_NOW,
        )
        self.assertIsInstance(updated["answers"]["confirm_japanese_text_and_motif"], dict)

    def test_legacy_inferred_confirmed_true_still_blocks_export(self):
        project = ready_project(self.root, name="Legacy inferred confirmation")
        rebuilt = []
        previous_hash = "0" * 64
        for original in _load_events(project):
            event = {
                key: value
                for key, value in original.items()
                if key not in {"previous_hash", "event_hash"}
            }
            if event.get("type") == "answer" and event.get("field") == "placement":
                event.update(
                    {
                        "source": "inferred",
                        "confirmed": True,
                        "evidence": "legacy agent inference",
                    }
                )
            sealed = _seal(event, previous_hash)
            rebuilt.append(sealed)
            previous_hash = sealed["event_hash"]

        state = replay_state(rebuilt)
        (project / "metadata/decisions.jsonl").write_text(
            "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in rebuilt),
            encoding="utf-8",
        )
        (project / "metadata/state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (project / "metadata/manifest.json").write_text(render_manifest(state), encoding="utf-8")
        (project / "project.yaml").write_text(render_project_yaml(state), encoding="utf-8")
        (project / "decisions.md").write_text(render_decisions_md(rebuilt), encoding="utf-8")

        report = validate_project(project, for_export=True)
        self.assertIn(
            "unconfirmed_critical_assumption",
            [item["code"] for item in report["errors"]],
        )

    def test_legacy_vague_assumption_confirmation_replays_but_stays_untrusted(self):
        # Releases before strict wording accepted any user quote for the grouped
        # confirmation. Replay must still accept that history, but the vague quote
        # cannot vouch for the critical inference it followed.
        project = ready_project(self.root, name="Legacy vague confirmation")
        rebuilt = []
        previous_hash = "0" * 64
        for original in _load_events(project):
            event = {
                key: value
                for key, value in original.items()
                if key not in {"previous_hash", "event_hash"}
            }
            if event.get("type") == "answer" and event.get("field") == "placement":
                event.update({"source": "inferred", "confirmed": True, "evidence": "legacy agent inference"})
            sealed = _seal(event, previous_hash)
            rebuilt.append(sealed)
            previous_hash = sealed["event_hash"]
        for quote in ("go ahead", "Yes, but keep an eye on the placement"):
            sealed = _seal(
                {
                    "type": "answer",
                    "field": "confirm_assumptions",
                    "value": True,
                    "source": "user",
                    "confirmed": True,
                    "user_quote": quote,
                    "timestamp": FIXED_NOW,
                },
                previous_hash,
            )
            rebuilt.append(sealed)
            previous_hash = sealed["event_hash"]
        _install_events(project, rebuilt)

        report = validate_project(project, for_export=True)
        codes = [item["code"] for item in report["errors"]]
        self.assertNotIn("event_chain_broken", codes)
        self.assertNotIn("state_tampered", codes)
        self.assertIn("unconfirmed_critical_assumption", codes)

        confirmed = append_event(
            project,
            {
                "type": "answer",
                "field": "confirm_assumptions",
                "value": True,
                "source": "user",
                "confirmed": True,
                "user_quote": "Yes, all correct",
            },
            FIXED_NOW,
        )
        self.assertEqual(confirmed["answers"]["confirm_assumptions"], True)
        codes = [item["code"] for item in validate_project(project, for_export=True)["errors"]]
        self.assertNotIn("unconfirmed_critical_assumption", codes)

    def test_new_vague_assumption_confirmation_is_still_refused(self):
        project = make_project(self.root)
        append_event(
            project,
            {"type": "answer", "field": "fit", "value": "boxy", "source": "inferred", "confirmed": False},
            FIXED_NOW,
        )
        with self.assertRaises(ValidationError):
            append_event(
                project,
                {
                    "type": "answer",
                    "field": "confirm_assumptions",
                    "value": True,
                    "source": "user",
                    "user_quote": "go ahead",
                },
                FIXED_NOW,
            )


def _install_events(project: Path, events: list[dict]) -> None:
    """Write a hand-built historical log plus the state and views it replays to."""
    state = replay_state(events)
    (project / "metadata/decisions.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in events),
        encoding="utf-8",
    )
    (project / "metadata/state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (project / "metadata/manifest.json").write_text(render_manifest(state), encoding="utf-8")
    (project / "project.yaml").write_text(render_project_yaml(state), encoding="utf-8")
    (project / "decisions.md").write_text(render_decisions_md(events), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
