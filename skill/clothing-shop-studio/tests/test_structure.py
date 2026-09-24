from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class StructureTests(unittest.TestCase):
    def test_required_entrypoints_exist(self):
        self.assertTrue((ROOT / "SKILL.md").is_file())
        self.assertTrue((ROOT / "agents" / "openai.yaml").is_file())
        for name in ("references", "data", "schemas", "scripts", "assets", "evals"):
            self.assertTrue((ROOT / name).is_dir(), name)

    def test_description_is_trigger_only_and_scoped_to_own_designs(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        description = next(line for line in text.splitlines() if line.startswith("description: "))
        self.assertTrue(description.startswith("description: Use when designing the user's own garments"))
        for phrase in ("catalogue cut-outs", "AI-model try-ons", "listing-concept visuals"):
            self.assertIn(phrase, description)
        self.assertLess(len(description), 420)
        self.assertLess(len(text.splitlines()), 45)

    def test_presentation_reference_and_near_miss_evals_exist(self):
        reference = (ROOT / "references/presentation.md").read_text(encoding="utf-8")
        for code in ("inventory_unconfirmed", "transmission_consent_missing", "garment_not_listing_eligible",
                     "model_not_kept", "real_person_model_refused", "decision_not_affirmative"):
            self.assertIn(code, reference)
        self.assertIn("no prices", reference.lower())
        for name in ("presentation-listing", "near-miss-shopper-tryon", "near-miss-mug-background",
                     "near-miss-shopee-price"):
            self.assertTrue((ROOT / "evals/scenarios" / f"{name}.json").is_file(), name)

    def test_presentation_reference_carries_listing_rulings_and_full_notice(self):
        reference = (ROOT / "references/presentation.md").read_text(encoding="utf-8")
        self.assertIn("Omit `design_name`", reference)
        self.assertIn("descends from that approved version", reference)
        self.assertIn("physical sample", reference)
        self.assertIn("Singapore seller generation notice", reference)
        self.assertIn("word for word", reference)
        skill_text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("shopper try-on of other brands' products, and general photo editing", skill_text)

    def test_presentation_evals_are_identical_in_bundle_and_repo(self):
        repo_scenarios = ROOT.parents[1] / "evals/scenarios"
        for name in ("presentation-listing", "near-miss-shopper-tryon", "near-miss-mug-background",
                     "near-miss-shopee-price"):
            bundle = (ROOT / "evals/scenarios" / f"{name}.json").read_bytes()
            self.assertEqual(bundle, (repo_scenarios / f"{name}.json").read_bytes(), name)

    def test_generation_disclaimer_is_mandatory_and_uses_official_sources(self):
        skill_text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        safety_text = (ROOT / "references" / "safety-scope.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("After every newly generated design output", skill_text)
        self.assertIn("Singapore seller generation notice", safety_text)
        for official_source in (
            "ipos.gov.sg/about-ip/copyright/infringement-and-enforcement",
            "mlaw.gov.sg/public-consultation-on-artificial-intelligence",
            "copyright.gov/newsnet/2025/1060.html",
            "ipos.gov.sg/about-ip/trade-marks/introduction-trade-marks",
            "etsy.com/au/legal/creativity",
            "ccs.gov.sg/media-and-events/newsroom",
        ):
            self.assertIn(official_source, safety_text)

        self.assertIn("informational, not legal advice", safety_text)
        self.assertIn("Do not bake this notice into the artwork", safety_text)
        self.assertIn("before the single closing question", skill_text)
        self.assertIn("before that single closing question", safety_text)


    def test_seller_notice_is_always_reproduced_in_full(self):
        safety = (ROOT / "references" / "safety-scope.md").read_text(encoding="utf-8")
        self.assertNotIn("shorter treatment, keep every topic", safety)
        self.assertNotIn("compress the prose", safety)
        self.assertIn("Always reproduce the full quoted notice word for word", safety)
        self.assertIn("including presentation visuals", safety)
        self.assertIn("even if the user asks for a shorter treatment", safety)
        self.assertIn("Do not bake this notice into the artwork", safety)

if __name__ == "__main__":
    unittest.main()
