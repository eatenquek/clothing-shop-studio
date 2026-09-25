from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # discoverable from any cwd

from scripts.studio_core.errors import ValidationError
from scripts.studio_core.models import install_defaults, plan_reference, register_models
from scripts.studio_core.presentation import kept_ids
from scripts.studio_core.store import load_state
from scripts.studio_core.tryon import decide_tryon, plan_tryon, register_tryon
from scripts.studio_core.validation import validate_project
from tests.helpers import FIXED_NOW, make_png, ready_project
from tests.test_extract import GARMENT, ITEM

BUNDLE = Path(__file__).resolve().parents[1]


def png(seed):
    return make_png(2, 1, [[(seed, 0, 0, 255), (0, seed, 0, 255)]])


class TryOnTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = ready_project(Path(self.temp.name))
        install_defaults(self.project, BUNDLE)
        job = plan_reference(self.project, {"model_id": "m-aria"})["jobs"][0]
        (self.project / job["destination"]).parent.mkdir(parents=True, exist_ok=True)
        (self.project / job["destination"]).write_bytes(png(9))
        register_models(self.project, {"kind": "reference", "results": [
            {"model_id": "m-aria", "path": job["destination"], "prompt": job["prompt"]}]}, FIXED_NOW)
        self.design = next(item["id"] for item in load_state(self.project)["files"]
                           if item["origin"] == "approved_design" and item.get("role") != "review_evidence")

    def tearDown(self):
        self.temp.cleanup()

    def test_plan_pins_model_and_locks_identity(self):
        plan = plan_tryon(self.project, {"design_id": self.design, "model_id": "m-aria",
                                         "poses": ["front", "back"]}, FIXED_NOW)
        self.assertEqual([job["pose"] for job in plan["jobs"]], ["front", "back"])
        job = plan["jobs"][0]
        self.assertIn(f"generated/{self.project.name}/models/pinned/m-aria-front.png", job["inputs"])
        self.assertIn("exactly as shown", job["prompt"])
        self.assertIn("same person", job["prompt"])
        self.assertEqual(job["destination"], f"generated/{self.project.name}/tryon/r01/m-aria-front.png")

    def test_plan_refuses_bad_poses_models_and_ineligible_garments(self):
        with self.assertRaises(ValidationError):
            plan_tryon(self.project, {"design_id": self.design, "model_id": "m-aria", "poses": ["side"]}, FIXED_NOW)
        with self.assertRaises(ValidationError) as caught:
            plan_tryon(self.project, {"design_id": self.design, "model_id": "m-nobody", "poses": ["front"]}, FIXED_NOW)
        self.assertEqual(caught.exception.details[0]["code"], "model_not_kept")
        ineligible = {"id": "xg-shop", "origin": "extracted_garment", "listing_eligible": False}
        from scripts.studio_core.presentation import register_entries
        path = self.project / "presentation/extracted/shop/r01/x.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(GARMENT)
        import hashlib
        register_entries(self.project, [{**ineligible, "path": "presentation/extracted/shop/r01/x.png",
                                         "sha256": hashlib.sha256(GARMENT).hexdigest(),
                                         "parents": ["ref-missing"], "registered_at": FIXED_NOW,
                                         "production_eligible": False}], FIXED_NOW)
        with self.assertRaises(ValidationError) as caught:
            plan_tryon(self.project, {"garment_ids": ["xg-shop"], "model_id": "m-aria", "poses": ["front"]}, FIXED_NOW)
        self.assertEqual(caught.exception.details[0]["code"], "garment_not_listing_eligible")

    def test_register_and_keep(self):
        plan = plan_tryon(self.project, {"design_id": self.design, "model_id": "m-aria", "poses": ["front"]}, FIXED_NOW)
        job = plan["jobs"][0]
        (self.project / job["destination"]).parent.mkdir(parents=True, exist_ok=True)
        (self.project / job["destination"]).write_bytes(png(3))
        entries = register_tryon(self.project, {"round": plan["round"], "model_id": "m-aria",
                                                "garment_ids": [self.design], "results": [
            {"pose": "front", "path": job["destination"], "renderer": "host", "prompt": job["prompt"]}]}, FIXED_NOW)
        entry = entries[0]
        self.assertEqual(entry["label"], "AI try-on")
        self.assertEqual(entry["parents"], [self.design, "pin-m-aria"])
        with self.assertRaises(ValidationError):
            decide_tryon(self.project, {"ids": [entry["id"]], "decision": "keep",
                                        "user_quote": "Keep, but fix the collar"}, FIXED_NOW)
        decide_tryon(self.project, {"ids": [entry["id"]], "decision": "keep", "user_quote": "Yes keep it"}, FIXED_NOW)
        self.assertEqual(kept_ids(load_state(self.project), "tryon"), {entry["id"]})
        self.assertEqual(validate_project(self.project)["errors"], [])


    def test_kept_project_scoped_custom_model_can_be_tried_on(self):
        from scripts.studio_core.models import keep_models, plan_models

        plan = plan_models(self.project, {"range": {"gender_presentation": "feminine", "age_range": "20-30",
                                                     "build": "varied", "skin_tone": "varied", "hair": "varied"}})
        results = []
        for index, job in enumerate(plan["jobs"]):
            (self.project / job["destination"]).parent.mkdir(parents=True, exist_ok=True)
            (self.project / job["destination"]).write_bytes(png(100 + index))
            results.append({"label": job["label"], "path": job["destination"], "prompt": job["prompt"]})
        entries = register_models(self.project, {"kind": "candidates", "round": plan["round"], "results": results,
                                                 "identities": plan["identities"]}, FIXED_NOW)
        model_id = plan["identities"]["A"]["id"]
        keep_models(self.project, {"ids": [model_id], "user_quote": "Keep A, yes"}, FIXED_NOW)
        tryon = plan_tryon(self.project, {"design_id": self.design, "model_id": model_id, "poses": ["front"]},
                           FIXED_NOW)
        job = tryon["jobs"][0]
        self.assertEqual(job["destination"], f"generated/{self.project.name}/tryon/r01/{model_id}-front.png")
        (self.project / job["destination"]).parent.mkdir(parents=True, exist_ok=True)
        (self.project / job["destination"]).write_bytes(png(55))
        entry = register_tryon(self.project, {"round": tryon["round"], "model_id": model_id,
                                              "garment_ids": [self.design], "results": [
            {"pose": "front", "path": job["destination"]}]}, FIXED_NOW)[0]
        self.assertEqual(entry["parents"], [self.design, f"pin-{model_id}"])
        self.assertFalse(entry["production_eligible"])
        self.assertTrue(any(item["id"] == model_id for item in entries))

    def test_register_rejects_non_integer_round(self):
        plan_tryon(self.project, {"design_id": self.design, "model_id": "m-aria", "poses": ["front"]}, FIXED_NOW)
        for bad in (None, "1", 0, 1.5, True):
            with self.subTest(round=bad), self.assertRaises(ValidationError) as caught:
                register_tryon(self.project, {"round": bad, "model_id": "m-aria", "garment_ids": [self.design],
                                              "results": [{"pose": "front", "path": "x.png"}]}, FIXED_NOW)
            self.assertEqual(caught.exception.field, "round")

    def test_register_refuses_byte_identical_poses(self):
        plan = plan_tryon(self.project, {"design_id": self.design, "model_id": "m-aria",
                                         "poses": ["front", "back"]}, FIXED_NOW)
        results = []
        for job in plan["jobs"]:
            (self.project / job["destination"]).parent.mkdir(parents=True, exist_ok=True)
            (self.project / job["destination"]).write_bytes(png(33))
            results.append({"pose": job["pose"], "path": job["destination"]})
        with self.assertRaises(ValidationError):
            register_tryon(self.project, {"round": plan["round"], "model_id": "m-aria",
                                          "garment_ids": [self.design], "results": results}, FIXED_NOW)

    def test_reference_images_supported_defaults_to_reference_lock(self):
        plan = plan_tryon(self.project, {"design_id": self.design, "model_id": "m-aria", "poses": ["front"],
                                         "reference_images_supported": True}, FIXED_NOW)
        self.assertEqual(plan["identity_lock"], "reference_image")
        self.assertIn(f"generated/{self.project.name}/models/pinned/m-aria-front.png", plan["jobs"][0]["inputs"])

    def test_description_only_lock_keeps_anchors_and_sends_no_images(self):
        plan = plan_tryon(self.project, {"design_id": self.design, "model_id": "m-aria",
                                         "poses": ["front", "back"], "reference_images_supported": False}, FIXED_NOW)
        self.assertEqual(plan["identity_lock"], "description_only")
        for job in plan["jobs"]:
            self.assertEqual(job["inputs"], [])
            self.assertIn("shoulder-length straight dark brown hair", job["prompt"])
            self.assertNotIn("reference image", job["prompt"])
            self.assertNotIn("presentation/", job["prompt"])
        self.assertEqual(plan["jobs"][0]["destination"], f"generated/{self.project.name}/tryon/r01/m-aria-front.png")

    def test_reference_images_supported_must_be_a_boolean(self):
        for bad in ("false", 0, 1, None, "true"):
            with self.subTest(value=bad), self.assertRaises(ValidationError) as caught:
                plan_tryon(self.project, {"design_id": self.design, "model_id": "m-aria", "poses": ["front"],
                                          "reference_images_supported": bad}, FIXED_NOW)
            self.assertEqual(caught.exception.field, "reference_images_supported")
        pinned = [item for item in load_state(self.project)["files"] if item["id"] == "pin-m-aria"]
        self.assertEqual(pinned, [], "an invalid option must be refused before the model is pinned")

if __name__ == "__main__":
    unittest.main()
