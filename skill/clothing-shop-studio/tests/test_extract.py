from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # discoverable from any cwd

from scripts.studio_core.errors import ValidationError
from scripts.studio_core.extract import (
    confirm_inventory,
    plan_extraction,
    record_consent,
    record_inventory,
    register_extraction,
)
from scripts.studio_core.store import load_state
from scripts.studio_core.validation import register_file, validate_project
from tests.helpers import FIXED_NOW, make_png, make_project

NAVY, WHITE = (20, 30, 90, 255), (255, 255, 255, 255)
GARMENT = make_png(4, 4, [[WHITE, NAVY, NAVY, WHITE]] * 4)
# A minimal, real (not placeholder) baseline JPEG: SOI, an SOF0 segment declaring a 4x4
# grayscale image, then EOI. Built by hand so `image_size` can read real headers from it.
JPEG_4X4 = bytes.fromhex("ffd8" "ffc0" "000b" "08" "0004" "0004" "01" "011100" "ffd9")
ITEM = {"slug": "navy-tee", "name": "Navy tee", "category": "tops", "details": ["casual"],
        "observed": ["crew neck"], "bbox": [0.1, 0.1, 0.8, 0.9], "graphic_policy": "omit", "unknowns": []}


def small_extract():
    """Patch the extraction module's minimum size down to fit the 4x4 test fixtures."""
    return patch("scripts.studio_core.extract.MIN_EXTRACT_SIZE", 4)


def code(error: ValidationError) -> str:
    return error.details[0]["code"] if error.details else ""


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = make_project(Path(self.temp.name))
        photo = self.project / "references/user/sample.png"
        photo.write_bytes(GARMENT)
        self.ref = register_file(self.project, {"origin": "user_reference", "path": "references/user/sample.png",
                                                "rights": "user-owned-or-licensed",
                                                "rights_statement": "My own sample."}, FIXED_NOW)

    def tearDown(self):
        self.temp.cleanup()

    def inventory(self, items=None):
        return record_inventory(self.project, {"source_id": self.ref["id"], "items": items or [ITEM]}, FIXED_NOW)

    def ready(self):
        inventory = self.inventory()
        confirm_inventory(self.project, {"inventory_id": inventory["id"], "user_quote": "Yes, that's right"}, FIXED_NOW)
        record_consent(self.project, {"file_id": self.ref["id"], "user_quote": "Yes"}, FIXED_NOW)
        return inventory

    def test_inventory_validates_items(self):
        for bad in ({**ITEM, "category": "hats"}, {**ITEM, "graphic_policy": "trace"},
                    {**ITEM, "bbox": [0.5, 0.5, 0.2, 0.9]}, {**ITEM, "slug": "Bad Slug"}):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                self.inventory([bad])
        with self.assertRaises(ValidationError):
            self.inventory([ITEM, ITEM])

    def test_plan_requires_confirmation_and_consent(self):
        inventory = self.inventory()
        with self.assertRaises(ValidationError) as caught:
            plan_extraction(self.project, {"inventory_id": inventory["id"]})
        self.assertEqual(code(caught.exception), "inventory_unconfirmed")
        with self.assertRaises(ValidationError):
            confirm_inventory(self.project, {"inventory_id": inventory["id"], "user_quote": "Yes, but add the cap"})
        confirm_inventory(self.project, {"inventory_id": inventory["id"], "user_quote": "Correct"}, FIXED_NOW)
        with self.assertRaises(ValidationError) as caught:
            plan_extraction(self.project, {"inventory_id": inventory["id"]})
        self.assertEqual(code(caught.exception), "transmission_consent_missing")

    def test_plan_jobs_follow_the_extraction_contract(self):
        inventory = self.ready()
        plan = plan_extraction(self.project, {"inventory_id": inventory["id"]})
        job = plan["jobs"][0]
        self.assertEqual(job["destination"], f"generated/{self.project.name}/extracted/{self.ref['id']}/r01/navy-tee.png")
        self.assertEqual((job["background"], job["min_size"]), ("#FFFFFF", 1200))
        for phrase in ("Reconstruct ONLY the complete empty", "Prefer omission over invention", "Omit any"):
            self.assertIn(phrase, job["prompt"])

    @small_extract()
    def test_register_records_lineage_colour_and_catalogue(self):
        inventory = self.ready()
        destination = plan_extraction(self.project, {"inventory_id": inventory["id"]})["jobs"][0]["destination"]
        (self.project / destination).parent.mkdir(parents=True, exist_ok=True)
        (self.project / destination).write_bytes(GARMENT)
        result = register_extraction(self.project, {"inventory_id": inventory["id"], "round": 1,
                                                    "results": [{"slug": "navy-tee", "path": destination,
                                                                 "renderer": "host-image-tool", "prompt": "p"}]},
                                     FIXED_NOW)
        entry = result["entries"][0]
        self.assertEqual((entry["origin"], entry["parents"], entry["primary_colour"]),
                         ("extracted_garment", [self.ref["id"]], "#141E5A"))
        self.assertTrue(entry["listing_eligible"])
        page = (self.project / result["catalogue"]).read_text("utf-8")
        self.assertIn("Navy tee", page)
        self.assertEqual(validate_project(self.project)["errors"], [])

    def test_register_refuses_unplanned_paths(self):
        inventory = self.ready()
        plan_extraction(self.project, {"inventory_id": inventory["id"]})
        stray = self.project / "presentation/extracted/elsewhere.png"
        stray.parent.mkdir(parents=True, exist_ok=True)
        stray.write_bytes(GARMENT)
        with self.assertRaises(ValidationError):
            register_extraction(self.project, {"inventory_id": inventory["id"], "round": 1,
                                               "results": [{"slug": "navy-tee", "path": "presentation/extracted/elsewhere.png",
                                                            "renderer": "r", "prompt": "p"}]}, FIXED_NOW)

    @small_extract()
    def test_catalogue_escapes_names_and_rejects_bad_colours(self):
        inventory = self.inventory([{**ITEM, "name": "<script>alert(1)</script>", "details": ["<b>x</b>"]}])
        confirm_inventory(self.project, {"inventory_id": inventory["id"], "user_quote": "Yes"}, FIXED_NOW)
        record_consent(self.project, {"file_id": self.ref["id"], "user_quote": "Yes"}, FIXED_NOW)
        destination = plan_extraction(self.project, {"inventory_id": inventory["id"]})["jobs"][0]["destination"]
        (self.project / destination).parent.mkdir(parents=True, exist_ok=True)
        (self.project / destination).write_bytes(JPEG_4X4)
        jpg = destination[:-4] + ".jpg"
        (self.project / destination).rename(self.project / jpg)
        with self.assertRaises(ValidationError):
            register_extraction(self.project, {"inventory_id": inventory["id"], "round": 1, "results": [
                {"slug": "navy-tee", "path": jpg, "renderer": "r", "prompt": "p",
                 "estimated_colours": {"primary": "red;}</style><script>"}}]}, FIXED_NOW)
        result = register_extraction(self.project, {"inventory_id": inventory["id"], "round": 1, "results": [
            {"slug": "navy-tee", "path": jpg, "renderer": "r", "prompt": "p",
             "estimated_colours": {"primary": "#AA0000"}}]}, FIXED_NOW)
        page = (self.project / result["catalogue"]).read_text("utf-8")
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertEqual(result["entries"][0]["colour_source"], "estimated")

    @small_extract()
    def test_third_party_source_is_inspiration_only(self):
        photo = self.project / "references/user/shop.png"
        photo.write_bytes(GARMENT)
        shop = register_file(self.project, {"origin": "user_reference", "path": "references/user/shop.png",
                                            "rights": "third-party-inspiration-only"}, FIXED_NOW)
        inventory = record_inventory(self.project, {"source_id": shop["id"], "items": [ITEM]}, FIXED_NOW)
        confirm_inventory(self.project, {"inventory_id": inventory["id"], "user_quote": "Yes"}, FIXED_NOW)
        record_consent(self.project, {"file_id": shop["id"], "user_quote": "Yes"}, FIXED_NOW)
        destination = plan_extraction(self.project, {"inventory_id": inventory["id"]})["jobs"][0]["destination"]
        (self.project / destination).parent.mkdir(parents=True, exist_ok=True)
        (self.project / destination).write_bytes(GARMENT)
        entry = register_extraction(self.project, {"inventory_id": inventory["id"], "round": 1, "results": [
            {"slug": "navy-tee", "path": destination, "renderer": "r", "prompt": "p"}]}, FIXED_NOW)["entries"][0]
        self.assertFalse(entry["listing_eligible"])

    def test_register_refuses_undersized_images_at_the_default_minimum(self):
        # No MIN_EXTRACT_SIZE patch here: a 4x4 render must be refused against the
        # real 1200px default, proving the size gate is actually wired in.
        inventory = self.ready()
        destination = plan_extraction(self.project, {"inventory_id": inventory["id"]})["jobs"][0]["destination"]
        (self.project / destination).parent.mkdir(parents=True, exist_ok=True)
        (self.project / destination).write_bytes(GARMENT)
        with self.assertRaises(ValidationError):
            register_extraction(self.project, {"inventory_id": inventory["id"], "round": 1,
                                               "results": [{"slug": "navy-tee", "path": destination,
                                                            "renderer": "r", "prompt": "p"}]}, FIXED_NOW)

    @patch("scripts.studio_core.extract.MIN_EXTRACT_SIZE", 1)
    def test_register_refuses_non_square_images(self):
        inventory = self.ready()
        destination = plan_extraction(self.project, {"inventory_id": inventory["id"]})["jobs"][0]["destination"]
        (self.project / destination).parent.mkdir(parents=True, exist_ok=True)
        wide = make_png(4, 2, [[WHITE, NAVY, NAVY, WHITE]] * 2)
        (self.project / destination).write_bytes(wide)
        with self.assertRaises(ValidationError):
            register_extraction(self.project, {"inventory_id": inventory["id"], "round": 1,
                                               "results": [{"slug": "navy-tee", "path": destination,
                                                            "renderer": "r", "prompt": "p"}]}, FIXED_NOW)

    def test_garment_keep_decision(self):
        from scripts.studio_core.extract import decide_garments
        with self.assertRaises(ValidationError):
            decide_garments(self.project, {"ids": ["nope"], "decision": "keep", "user_quote": "Yes"}, FIXED_NOW)

if __name__ == "__main__":
    unittest.main()
