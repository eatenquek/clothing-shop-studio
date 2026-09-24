from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # discoverable from any cwd

from scripts.studio_core.errors import ValidationError
from scripts.studio_core.interview import assumption_confirmation, load_graph, next_question, record_answer
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

    def test_descriptive_category_and_climate_phrases_are_canonicalised(self):
        cases = {
            "dri-fit running-club tee": "performance_top",
            "oversized relaxed long-sleeve tee": "long_sleeve",
            "heavyweight pullover hoodie": "hoodie",
            "boxy streetwear tee": "tee",
            "6-panel dad cap": "headwear",
            "a cute handmade scarf": "a cute handmade scarf",
        }
        for phrase, expected in cases.items():
            state = record_answer(blank_state(), "garment_category", phrase, source="user")
            self.assertEqual(state["answers"]["garment_category"], expected, phrase)
        for phrase in ("Singapore (hot, humid)", "humid outdoor training in Singapore"):
            state = record_answer(blank_state(), "climate", phrase, source="user")
            self.assertEqual(state["answers"]["climate"], "humid_tropical", phrase)

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

    def test_brand_artwork_is_requested_before_artwork_content(self):
        seen = collect_question_ids(state_with_answers(reference_status="none"), self.graph, limit=40)
        self.assertIn("brand_assets", seen)
        self.assertLess(seen.index("brand_assets"), seen.index("artwork_content"))

    def test_japanese_theme_requires_text_and_motif_confirmation(self):
        for content in ("KIKI KAKA wordmark with a Japanese yokai motif", "KIKI KAKA 鬼"):
            state = state_with_answers(reference_status="none", artwork_content=content)
            question = next_question(state, self.graph)
            self.assertEqual(question["id"], "confirm_japanese_text_and_motif", content)
            self.assertTrue(question["critical"])
            confirmed = record_answer(
                state, question["id"], "Text: 鬼 (oni); motif: kasa-obake", source="user",
                user_quote="Yes: 鬼 (oni), kasa-obake",
            )
            self.assertNotEqual(next_question(confirmed, self.graph)["id"], "confirm_japanese_text_and_motif")
        plain = state_with_answers(reference_status="none", artwork_content="KIKI KAKA wordmark")
        self.assertNotEqual(next_question(plain, self.graph)["id"], "confirm_japanese_text_and_motif")

    def test_confirmations_need_the_users_own_words(self):
        state = state_with_answers(reference_status="none")
        with self.assertRaises(ValidationError):
            record_answer(state, "confirm_heat_weight_tradeoff", "keep 280 gsm", source="inferred")
        with self.assertRaises(ValidationError):
            record_answer(state, "confirm_heat_weight_tradeoff", "keep 280 gsm", source="user")
        confirmed = record_answer(
            state, "confirm_heat_weight_tradeoff", "keep 280 gsm", source="user",
            user_quote="Keep it heavy, I like the structure",
        )
        self.assertEqual(confirmed["assumptions"][-1]["user_quote"], "Keep it heavy, I like the structure")

    def test_delegation_cannot_confirm_japanese_text(self):
        state = state_with_answers(reference_status="none", artwork_content="yokai motif")
        for quote in ("Use your recommendation and continue.", "continue", "you decide"):
            with self.assertRaises(ValidationError, msg=quote):
                record_answer(state, "confirm_japanese_text_and_motif", "Tengu", source="user", user_quote=quote)
        record_answer(state, "confirm_japanese_text_and_motif", "Tengu", source="user", user_quote="Yes, Tengu is right")

    def test_correction_cannot_confirm_all_assumptions(self):
        state = record_answer(blank_state(), "fit", "oversized", source="inferred", confirmed=False)
        with self.assertRaises(ValidationError):
            record_answer(
                state, "confirm_assumptions", "No, the fit should be slim", source="user",
                user_quote="No, the fit should be slim",
            )
        self.assertFalse(state["assumptions"][0]["confirmed"])

    def test_new_assumption_after_confirmation_is_asked_again(self):
        state = state_with_answers(reference_status="none")
        state = record_answer(state, "fit", "oversized", source="inferred", confirmed=False)
        state = record_answer(
            state, "confirm_assumptions", "confirmed", source="user", user_quote="confirmed"
        )
        state = record_answer(state, "gsm", 220, source="default", confirmed=False)
        question = assumption_confirmation(state)
        self.assertEqual(question["id"], "confirm_assumptions")
        self.assertIn("gsm: 220", question["prompt"])

    def test_visual_choice_is_recorded_in_words_not_as_a_concept_id(self):
        state = state_with_answers(reference_status="none")
        state["files"] = [{"id": "base_color-r01-A", "origin": "generated_concept"}]
        with self.assertRaises(ValidationError):
            record_answer(state, "base_color", "base_color-r01-A", source="user")
        chosen = record_answer(state, "base_color", "jet black", source="user", evidence="base_color-r01-A")
        self.assertEqual(chosen["answers"]["base_color"], "jet black")

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
