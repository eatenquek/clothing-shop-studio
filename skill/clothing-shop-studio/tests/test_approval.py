from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # discoverable from any cwd

from scripts.studio_core.approval import approve_design
from scripts.studio_core.errors import ValidationError
from scripts.studio_core.options import merge_concept
from scripts.studio_core.store import load_state, status
from tests.helpers import FIXED_NOW, hash_tree, make_project, register_concepts

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
        v2 = approve_design(self.project, [concept], "Revise sleeve", now=LATER)
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
        for statement in ("Use your recommendation and continue.", "you decide", "Continue"):
            with self.assertRaises(ValidationError, msg=statement):
                approve_design(self.project, [self.concepts["A"]["id"]], statement, now=FIXED_NOW)
        self.assertEqual(list((self.project / "designs/approved").iterdir()), [])

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
        version = approve_design(self.project, [merged["id"]], "A's density, C's distress", now=FIXED_NOW)
        approval = json.loads((version / "approval.json").read_text("utf-8"))
        self.assertEqual(approval["lineage"][merged["id"]], [self.concepts["A"]["id"], self.concepts["C"]["id"]])

    def test_status_lists_approved_versions(self):
        approve_design(self.project, [self.concepts["A"]["id"]], "Approve A", now=FIXED_NOW)
        self.assertEqual(status(self.project)["approved_versions"], ["v001"])


if __name__ == "__main__":
    unittest.main()
