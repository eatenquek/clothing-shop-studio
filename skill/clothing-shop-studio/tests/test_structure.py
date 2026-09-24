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


if __name__ == "__main__":
    unittest.main()
