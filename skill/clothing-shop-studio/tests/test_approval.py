from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # discoverable from any cwd

from scripts.studio_core.approval import approve_design
from scripts.studio_core.errors import ValidationError
from scripts.studio_core.options import merge_concept, register_options
from scripts.studio_core.store import load_state, status
from tests.helpers import FIXED_NOW, four_results, hash_tree, make_project, register_concepts

LATER = "2026-09-25T00:00:00Z"


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = make_project(Path(self.temp.name))
        self.concepts = register_concepts(self.project)

    def tearDown(self):
        self.temp.cleanup()

    def test_approval_creates_new_immutable_versions(self):
        concept = self.concepts["A"]["id"]
        v1 = approve_design(self.project, [concept], "Approve A", now=FIXED_NOW)
        before = hash_tree(v1)
        v2 = approve_design(self.project, [concept], "Approve A for the new version", now=LATER)
        self.assertEqual(v1.name, "v001")
        self.assertEqual(v2.name, "v002")
        self.assertNotEqual(hash_tree(v1), hash_tree(v2))
        self.assertEqual(hash_tree(v1), before, "creating v002 must not touch v001")
        approval = json.loads((v1 / "approval.json").read_text("utf-8"))
        self.assertEqual(approval["statement"], "Approve A")
        self.assertEqual(approval["source_hashes"], {concept: self.concepts["A"]["sha256"]})

    def test_approved_version_freezes_a_copy_of_the_concept(self):
        version = approve_design(self.project, [self.concepts["B"]["id"]], "Go with B", now=FIXED_NOW)
        state = load_state(self.project)
        approved = [item for item in state["files"] if item["origin"] == "approved_design"]
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0]["parents"], [self.concepts["B"]["id"]])
        self.assertTrue((self.project / approved[0]["path"]).is_file())
        self.assertTrue(approved[0]["path"].startswith(f"designs/approved/{version.name}/"))
        self.assertEqual(state["phase"], "approved")

    def test_approval_rejects_unknown_ids_and_empty_statement(self):
        with self.assertRaises(ValidationError):
            approve_design(self.project, ["no-such-concept"], "Approve", now=FIXED_NOW)
        with self.assertRaises(ValidationError):
            approve_design(self.project, [self.concepts["A"]["id"]], "  ", now=FIXED_NOW)
        self.assertEqual(list((self.project / "designs/approved").iterdir()), [])

    def test_delegation_is_not_an_approval(self):
        for statement in (
            "Use your recommendation and continue.", "you decide", "Continue",
            "Do what you think is best", "Use your best judgment", "Surprise me",
            "Sounds good, use your recommendation", "Whatever works", "OK go with your pick",
            "Go with your recommendation", "I will go with your recommendation",
            "Sure, you pick", "Your choice", "fine, whatever you think is best",
            "Approve whichever you recommend",
        ):
            with self.assertRaises(ValidationError, msg=statement):
                approve_design(self.project, [self.concepts["A"]["id"]], statement, now=FIXED_NOW)
        self.assertEqual(list((self.project / "designs/approved").iterdir()), [])

    def test_rejection_is_not_an_approval(self):
        for statement in (
            "I do not approve A",
            "Don't approve this",
            "I cannot approve A",
            "This is not approved",
            "Reject option A",
            "No, I decline this design",
            "I refuse to approve A",
            "Approval denied",
            "I veto option A",
            "Maybe later",
            "Not sure, maybe A",
            "A, but change the sleeve",
            "Nope",
            "nah",
            "This could use more work",
            "Do you approve A?",
            "I would approve A if you change it",
            # Leading refusals and negative selections.
            "No, take it back",
            "No thanks, I'll take a different one",
            "I wouldn't pick A",
            "Don't go with A",
            "Pick anything except A",
            "I'll take B instead",
            # Affirmative words carrying a revision request.
            "Yes, but make the sleeve longer",
            "Yes, but swap the navy for black",
            "Go with A, just make the logo bigger",
            "Take A but lose the sleeve print",
            "Use A, minus the back print",
            "Yes, go with A and tweak the font",
            "Yes — go with A and remove the hem tag",
            "Approve A without the tag",
            # Conditional, provisional, hedged, or ambiguous approvals.
            "Yes if the print is smaller",
            "Yes, approve A after you tweak it",
            "approve A pending the strike-off",
            "A is approved, subject to the printer's proof",
            "Approve A for now",
            "Approve A tentatively",
            "I approve A, I guess",
            "Approve A or B",
            "Approve A?",
            "Hold off for now",
            "Not yet",
        ):
            with self.assertRaises(ValidationError, msg=statement):
                approve_design(self.project, [self.concepts["A"]["id"]], statement, now=FIXED_NOW)
        self.assertEqual(list((self.project / "designs/approved").iterdir()), [])

    def test_approval_requires_an_affirmative_decision(self):
        for statement in (
            "I approve A",
            "Approved.",
            "Yes, approve option A",
            "Go with A",
            "Let's do A",
            "No changes, approve A",
            "Yes, approve A as is",
            "Approve revised A",
            "Lock in A",
        ):
            project = make_project(Path(self.temp.name), name=statement)
            concepts = register_concepts(project)
            approve_design(project, [concepts["A"]["id"]], statement, now=FIXED_NOW)

    def test_approval_rejects_concept_changed_after_registration(self):
        (self.project / self.concepts["C"]["path"]).write_text("<svg><text>C edited</text></svg>", "utf-8")
        with self.assertRaises(ValidationError):
            approve_design(self.project, [self.concepts["C"]["id"]], "Approve C", now=FIXED_NOW)
        self.assertEqual(list((self.project / "designs/approved").iterdir()), [])

    def test_merged_concept_approval_records_lineage(self):
        path = self.project / "concepts/generated/back_typography/merge.svg"
        path.write_text("<svg><text>M</text></svg>", "utf-8")
        merged = merge_concept(
            self.project,
            {
                "decision_id": "back_typography",
                "path": "concepts/generated/back_typography/merge.svg",
                "parents": [self.concepts["A"]["id"], self.concepts["C"]["id"]],
                "renderer": "test-renderer",
            },
            FIXED_NOW,
        )
        version = approve_design(
            self.project,
            [merged["id"]],
            "Approve the merged concept: A's density, C's distress",
            now=FIXED_NOW,
        )
        approval = json.loads((version / "approval.json").read_text("utf-8"))
        self.assertEqual(approval["lineage"][merged["id"]], [self.concepts["A"]["id"], self.concepts["C"]["id"]])

    def test_status_lists_approved_versions(self):
        approve_design(self.project, [self.concepts["A"]["id"]], "Approve A", now=FIXED_NOW)
        self.assertEqual(status(self.project)["approved_versions"], ["v001"])

    def test_approval_freezes_hashed_contact_sheet_review_evidence(self):
        payload = four_results(self.project, decision_id="front_art")
        sheet = self.project / "concepts/generated/front_art/r01/contact-sheet.png"
        sheet.write_bytes(b"reviewed raster contact sheet")
        payload["contact_sheet"] = str(sheet.relative_to(self.project))
        entries = {item["label"]: item for item in register_options(self.project, payload, FIXED_NOW)}
        version = approve_design(self.project, [entries["A"]["id"]], "Approve A", now=FIXED_NOW)
        approval = load_state(self.project)["approvals"][-1]
        self.assertEqual(list(approval["review_evidence_hashes"].values()), [approval["contact_sheet_sha256"]])
        self.assertTrue((version / "review-contact-sheet.png").is_file())

    def test_refusal_details_follow_the_error_schema(self):
        with self.assertRaises(ValidationError) as caught:
            approve_design(self.project, [self.concepts["A"]["id"]], "Yes, but change the sleeve", now=FIXED_NOW)
        detail = caught.exception.details[0]
        self.assertEqual(detail["code"], "revision")
        self.assertIn("message", detail)


if __name__ == "__main__":
    unittest.main()
