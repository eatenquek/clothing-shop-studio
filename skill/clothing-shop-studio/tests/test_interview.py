from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # discoverable from any cwd

from scripts.studio_core.errors import ValidationError
from scripts.studio_core.interview import load_graph, next_question, record_answer
from tests.helpers import blank_state, collect_question_ids, state_with_answers


class InterviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "data/interview-graph.json"
        cls.graph = json.loads(path.read_text("utf-8"))["questions"]

    def test_reference_is_first_and_only_once(self):
        question = next_question(blank_state(), self.graph)
        self.assertEqual(question["id"], "reference_image")
        state = record_answer(blank_state(), "reference_image", None, source="user")
        self.assertNotEqual(next_question(state, self.graph)["id"], "reference_image")
        self.assertEqual(state["answers"]["reference_status"], "none")

    def test_supplied_brief_skips_known_fields(self):
        state = state_with_answers(
            garment_category="long_sleeve",
            audience="unisex_young_adult",
            climate="humid_tropical",
            quantity=100,
            reference_status="none",
        )
        seen = collect_question_ids(state, self.graph, limit=8)
        self.assertNotIn("garment_category", seen)
        self.assertNotIn("audience", seen)
        self.assertNotIn("climate", seen)
        self.assertNotIn("quantity", seen)

    def test_heavy_singapore_long_sleeve_surfaces_conflict(self):
        state = state_with_answers(
            reference_status="none",
            garment_category="long_sleeve",
            climate="humid_tropical",
            gsm=260,
        )
        question = next_question(state, self.graph)
        self.assertEqual(question["id"], "confirm_heat_weight_tradeoff")
        self.assertIn("heat", question["prompt"].lower())

    def test_inferred_value_is_unconfirmed_assumption(self):
        state = record_answer(
            blank_state(),
            "fabric_structure",
            "mesh knit",
            source="inferred",
            evidence="Reference appears perforated",
            confirmed=False,
        )
        assumption = state["assumptions"][0]
        self.assertEqual(assumption["field"], "fabric_structure")
        self.assertFalse(assumption["confirmed"])
        self.assertEqual(assumption["source"], "inferred")

    def test_free_text_category_and_climate_are_canonicalised(self):
        state = record_answer(blank_state(), "garment_category", "T-Shirt", source="user")
        state = record_answer(state, "climate", "Singapore", source="user")
        self.assertEqual(state["answers"]["garment_category"], "tee")
        self.assertEqual(state["answers"]["climate"], "humid_tropical")
        state["answers"]["reference_status"] = "none"
        self.assertIn("gsm", collect_question_ids(state, self.graph, limit=20))

    def test_heavyweight_label_surfaces_conflict_without_a_number(self):
        state = record_answer(
            state_with_answers(reference_status="none", garment_category="long_sleeve", climate="humid_tropical"),
            "gsm",
            "heavyweight but still wearable",
            source="user",
        )
        self.assertEqual(next_question(state, self.graph)["id"], "confirm_heat_weight_tradeoff")
        numeric = record_answer(state_with_answers(), "gsm", "260 gsm", source="user")
        self.assertEqual(numeric["answers"]["gsm"], 260)

    def test_options_sources_route_to_planned_reference_files(self):
        planned = {
            "adaptive-interview.md",
            "garments-materials.md",
            "visual-options.md",
            "production-pack.md",
            "safety-scope.md",
            "inspiration-library.md",
            "workflow.md",
        }
        for node in self.graph:
            self.assertIn(node["options_source"].split("#")[0], planned, node["id"])

    def test_load_graph_reads_bundle_graph_and_rejects_missing_file(self):
        bundle = Path(__file__).resolve().parents[1]
        graph = load_graph(bundle)
        self.assertEqual([node["id"] for node in graph], [node["id"] for node in self.graph])
        with self.assertRaises(ValidationError):
            load_graph(bundle / "no-such-bundle")

    def test_every_question_has_required_contract(self):
        required = {
            "id",
            "phase",
            "prompt",
            "answer_type",
            "applies_when",
            "skip_if_known",
            "inferable",
            "critical",
            "visual",
            "options_source",
        }
        for question in self.graph:
            self.assertTrue(required.issubset(question), question["id"])


if __name__ == "__main__":
    unittest.main()
