from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # discoverable from any cwd

from scripts.studio_core.errors import ValidationError
from scripts.studio_core.listing import build_listing, decide_listing
from scripts.studio_core.store import load_state
from scripts.studio_core.tryon import decide_tryon, plan_tryon, register_tryon
from scripts.studio_core.validation import validate_project
from tests.helpers import FIXED_NOW
from tests.test_tryon import TryOnTests, png


class ListingTests(TryOnTests):
    def kept_tryon(self, pose="front"):
        plan = plan_tryon(self.project, {"design_id": self.design, "model_id": "m-aria", "poses": [pose]}, FIXED_NOW)
        job = plan["jobs"][0]
        (self.project / job["destination"]).parent.mkdir(parents=True, exist_ok=True)
        (self.project / job["destination"]).write_bytes(png(40 + len(pose)))
        entry = register_tryon(self.project, {"round": plan["round"], "model_id": "m-aria",
                                              "garment_ids": [self.design],
                                              "results": [{"pose": pose, "path": job["destination"]}]}, FIXED_NOW)[0]
        decide_tryon(self.project, {"ids": [entry["id"]], "decision": "keep", "user_quote": "Yes"}, FIXED_NOW)
        return entry

    def test_listing_has_no_unconfirmed_text_and_marks_missing_slots(self):
        tryon = self.kept_tryon("front")
        result = build_listing(self.project, {"version": "v001"}, FIXED_NOW)
        self.assertEqual(result["version"], "listing-v001")
        self.assertEqual(result["slots"]["front"], tryon["id"])
        self.assertIn("back", result["missing"])
        self.assertIn("white_background", result["missing"])
        page = (self.project / result["files"]["html"]).read_text("utf-8")
        self.assertIn("Concept — not a live listing", page)
        for banned in ("¥", "$", "SGD", "RMB", "price", "Price", "size chart", "cm"):
            self.assertNotIn(banned, re.sub(r"<style>.*?</style>", "", page, flags=re.S))
        self.assertEqual(validate_project(self.project)["errors"], [])

    def test_unkept_or_ineligible_images_are_excluded(self):
        plan = plan_tryon(self.project, {"design_id": self.design, "model_id": "m-aria", "poses": ["back"]}, FIXED_NOW)
        job = plan["jobs"][0]
        (self.project / job["destination"]).parent.mkdir(parents=True, exist_ok=True)
        (self.project / job["destination"]).write_bytes(png(77))
        register_tryon(self.project, {"round": plan["round"], "model_id": "m-aria", "garment_ids": [self.design],
                                      "results": [{"pose": "back", "path": job["destination"]}]}, FIXED_NOW)
        result = build_listing(self.project, {"version": "v001"}, FIXED_NOW)
        self.assertIsNone(result["slots"]["back"])

    def test_design_name_is_escaped_and_versions_increment(self):
        self.kept_tryon("front")
        first = build_listing(self.project, {"version": "v001", "design_name": "<img src=x onerror=1>"}, FIXED_NOW)
        page = (self.project / first["files"]["html"]).read_text("utf-8")
        self.assertNotIn("<img src=x", page)
        second = build_listing(self.project, {"version": "v001"}, FIXED_NOW)
        self.assertEqual(second["version"], "listing-v002")
        with self.assertRaises(ValidationError):
            decide_listing(self.project, {"ids": [first["files"]["html_id"]], "decision": "keep",
                                          "user_quote": "Keep for now"}, FIXED_NOW)

    def test_unknown_approval_version_is_refused(self):
        with self.assertRaises(ValidationError):
            build_listing(self.project, {"version": "v404"}, FIXED_NOW)


    def register_cutout(self, cutout_id, parent, seed):
        import hashlib

        from scripts.studio_core.presentation import register_entries

        relative = f"presentation/extracted/{cutout_id}.png"
        data = png(seed)
        (self.project / relative).parent.mkdir(parents=True, exist_ok=True)
        (self.project / relative).write_bytes(data)
        register_entries(self.project, [{"id": cutout_id, "origin": "extracted_garment", "path": relative,
                                         "sha256": hashlib.sha256(data).hexdigest(), "parents": [parent],
                                         "registered_at": FIXED_NOW, "production_eligible": False}], FIXED_NOW)

    def test_kept_eligible_cutout_fills_white_background_slot(self):
        from scripts.studio_core.extract import decide_garments
        from scripts.studio_core.validation import register_file

        shop = self.project / "references/user/shop.png"
        shop.write_bytes(png(5))
        third_party = register_file(self.project, {"origin": "user_reference", "path": "references/user/shop.png",
                                                   "rights": "third-party-inspiration-only"}, FIXED_NOW)
        self.register_cutout("xg-shop", third_party["id"], 81)
        self.register_cutout("xg-own", self.design, 82)
        decide_garments(self.project, {"ids": ["xg-shop"], "decision": "keep", "user_quote": "Yes keep it"}, FIXED_NOW)
        self.assertIsNone(build_listing(self.project, {"version": "v001"}, FIXED_NOW)["slots"]["white_background"])
        decide_garments(self.project, {"ids": ["xg-own"], "decision": "keep", "user_quote": "Yes keep it"}, FIXED_NOW)
        result = build_listing(self.project, {"version": "v001"}, FIXED_NOW)
        self.assertEqual(result["slots"]["white_background"], "xg-own")
        listing_entry = next(item for item in load_state(self.project)["files"]
                             if item["path"] == result["files"]["html"])
        self.assertIn("xg-own", listing_entry["parents"])
        self.assertFalse(listing_entry["production_eligible"])
        self.assertEqual(validate_project(self.project)["errors"], [])

if __name__ == "__main__":
    unittest.main()
