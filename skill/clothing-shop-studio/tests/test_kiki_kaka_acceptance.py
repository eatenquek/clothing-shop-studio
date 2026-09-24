"""End-to-end KIKI KAKA acceptance, driven only through the public CLI."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1]
STUDIO = BUNDLE / "scripts/studio.py"
RENDER = BUNDLE / "scripts/render-options.py"

# Facts stated in the KIKI KAKA brief, parsed before any question is asked.
BRIEF_FACTS = {
    "garment_category": "long-sleeve",
    "fit": "oversized relaxed",
    "audience": "unisex young adults",
    "climate": "Singapore",
    "base_color": "monochrome black",
    "artwork_style": "utilitarian streetwear, intentionally imperfect condensed distressed type",
    "placement": "large upper back, small centre chest",
    "quantity": 100,
    "budget_tier": "average",
    "deliverables": "production_pack",
}
# Answers the user gives when asked; a question outside this table fails the test.
REPLIES = {
    "reference_image": None,
    "garment_subtype": "crew-neck long-sleeve tee",
    "intended_use": "everyday streetwear retail drop",
    "length": "regular body length, slightly dropped shoulder",
    "construction": "side-seamed body, 1x1 rib cuffs and collar",
    "fiber_blend": "100% combed cotton",
    "fabric_structure": "single jersey",
    "gsm": "heavyweight but still wearable",
    "confirm_heat_weight_tradeoff": "Keep a 220 GSM mid-heavy jersey with a boxy cut for airflow",
    "handfeel": "dry, matte, slightly washed",
    "stretch": "none",
    "opacity": "fully opaque",
    "care": "cold wash, no tumble dry",
    "size_range": "S-XXL unisex",
    "grading_strategy": "two print sizes: S-M at 280 mm, L-XXL at 320 mm wide",
    "brand_assets": "existing KIKI KAKA wordmark supplied as vector",
    "artwork_content": "KIKI KAKA wordmark with a Japanese yokai motif",
    "confirm_japanese_text_and_motif": "Text 鬼 (oni) confirmed; motif: traditional kasa-obake silhouette",
    "typography": "condensed sans, irregular baseline",
    "scale": "back print about 300 mm wide on the base size",
    "decoration_method": "plastisol screen print, one off-white ink",
    "producer_constraints": "local screen printer, max print area 380 x 450 mm",
    "packaging": "individually folded and bagged",
    "confirm_assumptions": "confirmed",
}


class KikiKakaAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = {**os.environ, "CLOTHING_SHOP_STUDIO_HOME": str(self.root / "projects")}

    def tearDown(self):
        for path in self.root.rglob("*"):
            if path.is_file():
                os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        self.temp.cleanup()

    def cli(self, command: str, payload: dict, script: Path = STUDIO) -> dict:
        completed = subprocess.run(
            [sys.executable, str(script), command] if script == STUDIO else [sys.executable, str(script)],
            input=json.dumps(payload, ensure_ascii=False), text=True, capture_output=True,
            check=False, cwd=self.root, env=self.env,
        )
        response = json.loads(completed.stdout)
        self.assertTrue(response["ok"], f"{command}: {response.get('error')}")
        return response["data"]

    def test_full_kiki_kaka_flow(self):
        created = self.cli("create_project", {"name": "KIKI KAKA"})
        project = created["project_dir"]
        self.assertEqual(created["next_question"]["id"], "reference_image")

        # Parse the brief first so no supplied fact is asked again.
        question = created["next_question"]
        for field, value in BRIEF_FACTS.items():
            question = self.cli("record_answer", {"project_dir": project, "field": field, "value": value})["next_question"]
        self.assertEqual(question["id"], "reference_image", "reference must still come first")

        asked = []
        while question is not None:
            qid = question["id"]
            self.assertNotIn(qid, BRIEF_FACTS, f"re-asked a supplied fact: {qid}")
            self.assertNotIn(qid, asked, f"asked twice: {qid}")
            self.assertIn(qid, REPLIES, f"unexpected question: {qid}")
            asked.append(qid)
            payload = {"project_dir": project, "field": qid, "value": REPLIES[qid]}
            if qid.startswith("confirm_"):
                payload["user_quote"] = str(REPLIES[qid])  # the user's own words
            data = self.cli("record_answer", payload)
            self.assertIsInstance(data["next_question"], (dict, type(None)))
            question = data["next_question"]

        for required in (
            "brand_assets",
            "confirm_heat_weight_tradeoff",
            "grading_strategy",
            "confirm_japanese_text_and_motif",
        ):
            self.assertIn(required, asked)
        self.assertLess(asked.index("gsm"), asked.index("confirm_heat_weight_tradeoff"))

        # Four labelled treatments of the back typography.
        plan = self.cli(
            "generate_options",
            {"project_dir": project, "mode": "plan", "decision_id": "back_typography",
             "axes": ["letter density", "baseline irregularity", "distress depth", "scale"],
             "constraints": {"colours": 1, "method": "plastisol screen print"}},
        )
        out_dir = Path(project) / plan["slots"][0]["destination"].rsplit("/", 1)[0]
        briefs = [
            {"label": slot["label"], "axis": slot["axis"], "title": f"Treatment {slot['label']}",
             "brief": "KIKI KAKA condensed distressed type", "garment": "long_sleeve",
             "placement": "upper_back", "colors": ["#111111", "#EDEBE4"]}
            for slot in plan["slots"]
        ]
        rendered = self.cli(
            "", {"project_dir": project, "output_dir": str(out_dir), "briefs": briefs}, script=RENDER
        )
        entries = self.cli(
            "generate_options",
            {"project_dir": project, "mode": "register", "decision_id": "back_typography",
             "contact_sheet": str(Path(rendered["contact_sheet"]).relative_to(project)),
             "results": [
                 {"label": slot["label"], "axis": slot["axis"], "renderer": "svg-fallback",
                  "path": str(Path(rendered["cards"][slot["label"]]).relative_to(project)),
                  "prompt": "KIKI KAKA condensed distressed type",
                  "convention_broken": "Type crosses the shoulder seams" if slot["wildcard"] else None}
                 for slot in plan["slots"]
             ]},
        )["entries"]
        self.assertEqual([entry["label"] for entry in entries], ["A", "B", "C", "W"])

        approval = self.cli(
            "approve_design",
            {"project_dir": project, "concept_ids": [entries[1]["id"]], "statement": "Go with B"},
        )
        self.assertEqual(approval["version"], "v001")

        # The screen-print master is typeset vector artwork with deterministic distress.
        master = Path(project) / "production/masters/kiki-kaka-back_MASTER.svg"
        master.parent.mkdir(parents=True, exist_ok=True)
        master.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="300mm" height="120mm" viewBox="0 0 300 120">'
            '<text x="0" y="90" font-size="96">KIKI KAKA</text>'
            '<g id="distress-mask"><circle cx="40" cy="60" r="2"/></g></svg>',
            encoding="utf-8",
        )
        registered = self.cli(
            "register_file",
            {"project_dir": project, "origin": "production_master",
             "path": "production/masters/kiki-kaka-back_MASTER.svg", "construction": "typeset",
             "approved_version": "v001", "placement": "upper_back",
             "reference_point": "centre back, below the back neck seam", "offset_mm": 80,
             "print_width_mm": 300, "print_height_mm": 120,
             "colours": ["Off-white plastisol, match to approved strike-off"],
             "decoration_method": "plastisol screen print"},
        )
        report = self.cli("validate", {"project_dir": project, "master_ids": [registered["id"]], "for_export": True})
        self.assertEqual(report["errors"], [])

        exported = self.cli("export_production_pack", {"project_dir": project})
        pack = Path(exported["path"])
        self.assertEqual(pack.name, "pack-v001")
        spec = (pack / "production-spec.md").read_text("utf-8")
        for expected in ("## Placement", "300 × 120 mm", "## Colour", "## Tolerances", "## Sizing",
                         "two print sizes", "strike-off", "## Files"):
            self.assertIn(expected, spec)
        self.assertNotRegex(spec, r"(?i)(\$\s?\d|SGD|USD|price per|quote:)")
        checklist = (pack / "handoff-checklist.md").read_text("utf-8")
        self.assertIn("Japanese", checklist)
        manifest = json.loads((pack / "manifest.json").read_text("utf-8"))
        self.assertEqual(
            sorted(item["role"] for item in manifest["files"]),
            ["handoff_checklist", "production_master", "production_spec"],
        )
        self.assertTrue(manifest["files"][0]["path"].startswith("masters/kiki-kaka_v001_upper-back_MASTER_pack-v001"))

        # A fresh process resumes without re-asking anything.
        resumed = self.cli("resume_project", {"project_dir": project})
        self.assertIsNone(resumed["next_question"])
        self.assertEqual(resumed["phase"], "production_exported")


if __name__ == "__main__":
    unittest.main()
