from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class StructureTests(unittest.TestCase):
    def test_required_entrypoints_exist(self):
        self.assertTrue((ROOT / "SKILL.md").is_file())
        self.assertTrue((ROOT / "agents" / "openai.yaml").is_file())
        for name in ("references", "data", "schemas", "scripts", "assets", "evals"):
            self.assertTrue((ROOT / name).is_dir(), name)

    def test_description_is_trigger_only(self):
        skill_file = ROOT / "SKILL.md"
        self.assertTrue(skill_file.is_file(), "SKILL.md is missing")
        text = skill_file.read_text(encoding="utf-8")
        self.assertIn("description: Use when designing garments", text)
        self.assertNotIn("description: Use when designing garments by", text)

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


if __name__ == "__main__":
    unittest.main()
