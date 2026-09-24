from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # discoverable from any cwd

from scripts.studio_core.errors import UnsafePathError, ValidationError
from scripts.studio_core.presentation import (
    PRESENTATION_FOLDERS,
    check_image,
    image_size,
    kept_ids,
    library_root,
    listing_eligible,
    record_decision,
    register_entries,
)
from scripts.studio_core.store import load_state
from scripts.studio_core.validation import master_problems, validate_project
from tests.helpers import FIXED_NOW, make_png, make_project, ready_project

PNG_1PX = make_png(1, 1, [[(0, 0, 0, 255)]])


def write(project: Path, relative: str, data: bytes) -> str:
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return relative


class PresentationCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = make_project(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_legacy_project_state_gains_no_presentation_key(self):
        project = ready_project(self.root, name="Legacy shape")
        self.assertNotIn("presentation", load_state(project))
        self.assertEqual(validate_project(project)["errors"], [])

    def test_check_image_refuses_wrong_folder_signature_and_empty(self):
        folder = PRESENTATION_FOLDERS["extracted_garment"]
        good = write(self.project, f"{folder}src/r01/tee.png", PNG_1PX)
        self.assertEqual(check_image(self.project, good, folder)[1], good)
        with self.assertRaises(UnsafePathError):
            check_image(self.project, write(self.project, "concepts/generated/x.png", PNG_1PX), folder)
        for name, data in (("fake.png", b"not a png"), ("empty.png", b""), ("doc.txt", b"text")):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                check_image(self.project, write(self.project, f"{folder}src/r01/{name}", data), folder)

    def test_presentation_files_are_generated_for_master_checks(self):
        relative = write(self.project, "presentation/extracted/src/r01/tee.png", PNG_1PX)
        entry = {"id": "xg-001", "origin": "extracted_garment", "path": relative, "sha256": "0" * 64,
                 "parents": [], "registered_at": FIXED_NOW, "production_eligible": False}
        register_entries(self.project, [entry], FIXED_NOW)
        master = {"id": "master-x", "origin": "production_master", "path": "production/masters/x_MASTER.png",
                  "parents": ["xg-001"], "construction": "user_supplied"}
        problems = master_problems(master, {"xg-001": entry})
        codes = [item["code"] for item in problems]
        self.assertTrue({"master_generated_raster", "master_generated_concept"} & set(codes), codes)
        self.assertTrue(any("extracted_garment" in item["message"] for item in problems), problems)

    def test_listing_eligibility_follows_rights_lineage(self):
        files = {
            "ref-own": {"id": "ref-own", "origin": "user_reference", "rights": "user-owned-or-licensed", "parents": []},
            "ref-3p": {"id": "ref-3p", "origin": "user_reference", "rights": "third-party-inspiration-only", "parents": []},
            "ref-web": {"id": "ref-web", "origin": "online_reference", "parents": []},
            "v001-a": {"id": "v001-a", "origin": "approved_design", "parents": ["c-a"]},
            "c-a": {"id": "c-a", "origin": "generated_concept", "parents": []},
            "m-1": {"id": "m-1", "origin": "synthetic_model", "parents": []},
        }
        own = {"id": "x1", "origin": "extracted_garment", "parents": ["ref-own"]}
        third = {"id": "x2", "origin": "extracted_garment", "parents": ["ref-3p"]}
        web = {"id": "x3", "origin": "extracted_garment", "parents": ["ref-web"]}
        design = {"id": "t1", "origin": "tryon_image", "parents": ["v001-a", "m-1"]}
        self.assertTrue(listing_eligible(own, files))
        self.assertFalse(listing_eligible(third, files))
        self.assertFalse(listing_eligible(web, files))
        self.assertTrue(listing_eligible(design, files))

    def test_decisions_need_affirmative_keep_and_latest_wins(self):
        with self.assertRaises(ValidationError) as caught:
            record_decision(self.project, "tryon", ["t1"], "keep", "Yes, but make it brighter", FIXED_NOW)
        self.assertEqual(caught.exception.details[0]["code"], "decision_not_affirmative")
        record_decision(self.project, "tryon", ["t1"], "keep", "Keep it, yes", FIXED_NOW)
        self.assertEqual(kept_ids(load_state(self.project), "tryon"), {"t1"})
        record_decision(self.project, "tryon", ["t1"], "drop", "Drop that one", FIXED_NOW)
        self.assertEqual(kept_ids(load_state(self.project), "tryon"), set())
        self.assertEqual(validate_project(self.project)["errors"], [])

    def test_library_root_is_beside_projects(self):
        self.assertEqual(library_root(self.project), self.project.parent / "_models")

    def test_image_size_reads_png_jpeg_and_headers(self):
        png_path = self.project / "sample.png"
        png_path.write_bytes(make_png(4, 3, [[(0, 0, 0, 255)] * 4] * 3))
        self.assertEqual(image_size(png_path), (4, 3))

        # A minimal, real baseline JPEG: SOI, an SOF0 segment declaring a 4x4
        # grayscale image, then EOI, built by hand from real marker bytes.
        jpeg_path = self.project / "sample.jpg"
        jpeg_path.write_bytes(bytes.fromhex("ffd8" "ffc0" "000b" "08" "0004" "0004" "01" "011100" "ffd9"))
        self.assertEqual(image_size(jpeg_path), (4, 4))

        garbage_path = self.project / "sample.bin"
        garbage_path.write_bytes(b"not an image")
        self.assertIsNone(image_size(garbage_path))
        self.assertIsNone(image_size(self.project / "missing.png"))


if __name__ == "__main__":
    unittest.main()
