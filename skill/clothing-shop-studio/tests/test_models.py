from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # discoverable from any cwd

from scripts.studio_core.errors import ValidationError
from scripts.studio_core.models import (
    install_defaults,
    keep_models,
    library_models,
    pin_model,
    plan_models,
    plan_reference,
    refuse_real_person,
    register_models,
)
from scripts.studio_core.store import load_state
from scripts.studio_core.validation import validate_project
from tests.helpers import FIXED_NOW, make_png, make_project

BUNDLE = Path(__file__).resolve().parents[1]
PIXEL = (120, 100, 90, 255)


def png(seed: int) -> bytes:
    return make_png(2, 2, [[(seed, 10, 10, 255), PIXEL], [PIXEL, PIXEL]])


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = make_project(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def render(self, job, data):
        target = self.project / job["destination"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {"label": job.get("label"), "model_id": job.get("model_id"), "path": job["destination"],
                "renderer": "host-image-tool", "prompt": job["prompt"]}

    def test_defaults_install_once_outside_the_skill(self):
        result = install_defaults(self.project, BUNDLE)
        self.assertEqual(sorted(result["installed"]), ["m-aria", "m-kai", "m-noor", "m-theo"])
        self.assertEqual(sorted(result["missing_images"]), ["m-aria", "m-kai", "m-noor", "m-theo"])
        self.assertEqual(install_defaults(self.project, BUNDLE)["installed"], [])
        self.assertFalse(any(BUNDLE.rglob("front.png")))

    def test_real_person_backstop(self):
        for text in ("looks like Zendaya", "celebrity lookalike", "resembling a famous influencer"):
            with self.subTest(text=text), self.assertRaises(ValidationError) as caught:
                refuse_real_person(text)
            self.assertEqual(caught.exception.details[0]["code"], "real_person_model_refused")
        refuse_real_person("athletic build, short black hair")

    def test_candidates_need_affirmative_keep(self):
        plan = plan_models(self.project, {"range": {"gender_presentation": "feminine", "age_range": "20-30",
                                                     "build": "varied", "skin_tone": "varied", "hair": "varied"}})
        self.assertEqual([job["label"] for job in plan["jobs"]], ["A", "B", "C", "W"])
        results = [self.render(job, png(index)) for index, job in enumerate(plan["jobs"])]
        entries = register_models(self.project, {"kind": "candidates", "round": plan["round"],
                                                 "results": results, "identities": plan["identities"]}, FIXED_NOW)
        with self.assertRaises(ValidationError):
            keep_models(self.project, {"ids": [entries[0]["id"]], "user_quote": "maybe"}, FIXED_NOW)
        kept = keep_models(self.project, {"ids": [entries[0]["id"]], "user_quote": "Keep A, yes"}, FIXED_NOW)
        self.assertIn(kept["models"][0], library_models(self.project))
        self.assertEqual(validate_project(self.project)["errors"], [])

    def test_reference_render_for_default_then_pin_by_hash(self):
        install_defaults(self.project, BUNDLE)
        job = plan_reference(self.project, {"model_id": "m-kai"})["jobs"][0]
        register_models(self.project, {"kind": "reference", "results": [self.render(job, png(7))]}, FIXED_NOW)
        self.assertIsNotNone(library_models(self.project)["m-kai"]["front_image"])
        entry = pin_model(self.project, "m-kai", FIXED_NOW)
        self.assertEqual(entry["origin"], "synthetic_model")
        self.assertTrue(entry["ai_generated_person"])
        self.assertEqual(pin_model(self.project, "m-kai", FIXED_NOW)["id"], entry["id"])
        (self.project.parent.parent / "generated/_models/m-kai/front.png").write_bytes(png(99))
        self.assertEqual(validate_project(self.project)["errors"], [])
        self.assertTrue((self.project / entry["path"]).read_bytes() != png(99))


    def test_register_rejects_non_integer_round_as_validation_error(self):
        plan = plan_models(self.project, {"range": {"gender_presentation": "masculine", "age_range": "20-30",
                                                     "build": "varied", "skin_tone": "varied", "hair": "varied"}})
        results = [self.render(job, png(index)) for index, job in enumerate(plan["jobs"])]
        for bad in (None, "1", 0, -1, 1.5, True):
            with self.subTest(round=bad), self.assertRaises(ValidationError) as caught:
                register_models(self.project, {"kind": "candidates", "round": bad, "results": results,
                                               "identities": plan["identities"]}, FIXED_NOW)
            self.assertEqual(caught.exception.field, "round")

    def test_candidate_entries_are_never_production_eligible(self):
        plan = plan_models(self.project, {"range": {"gender_presentation": "feminine", "age_range": "30-40",
                                                     "build": "varied", "skin_tone": "varied", "hair": "varied"}})
        results = [self.render(job, png(index + 20)) for index, job in enumerate(plan["jobs"])]
        entries = register_models(self.project, {"kind": "candidates", "round": plan["round"],
                                                 "results": results, "identities": plan["identities"]}, FIXED_NOW)
        self.assertEqual({entry["production_eligible"] for entry in entries}, {False})
        self.assertNotIn("presentation", load_state(make_project(Path(self.temp.name) / "fresh")))

    def test_install_defaults_ignores_stray_files(self):
        import shutil

        bundle = Path(self.temp.name) / "bundle"
        shutil.copytree(BUNDLE / "assets/models", bundle / "assets/models")
        (bundle / "assets/models/.DS_Store").write_bytes(b"finder metadata")
        result = install_defaults(self.project, bundle)
        self.assertEqual(sorted(result["installed"]), ["m-aria", "m-kai", "m-noor", "m-theo"])

    def keep_round_one_candidate_a(self, project, seed):
        plan = plan_models(project, {"range": {"gender_presentation": "feminine", "age_range": "20-30",
                                                "build": "varied", "skin_tone": "varied", "hair": "varied"}})
        results = []
        for index, job in enumerate(plan["jobs"]):
            target = project / job["destination"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(png(seed + index))
            results.append({"label": job["label"], "path": job["destination"], "renderer": "host-image-tool",
                            "prompt": job["prompt"]})
        entries = register_models(project, {"kind": "candidates", "round": plan["round"], "results": results,
                                            "identities": plan["identities"]}, FIXED_NOW)
        candidate_a = next(entry for entry in entries if entry["identity"]["id"] == plan["identities"]["A"]["id"])
        keep_models(project, {"ids": [candidate_a["id"]], "user_quote": "Keep A, yes"}, FIXED_NOW)
        return plan, candidate_a

    def test_custom_candidate_ids_are_project_scoped_in_the_shared_library(self):
        root = Path(self.temp.name)
        project_p = make_project(root, "Project P")
        project_q = make_project(root, "Project Q")
        self.assertEqual(project_p.parent, project_q.parent)
        plan_p, kept_p = self.keep_round_one_candidate_a(project_p, 10)
        plan_q, kept_q = self.keep_round_one_candidate_a(project_q, 60)
        self.assertEqual((plan_p["round"], plan_q["round"]), (1, 1))
        self.assertNotEqual(kept_p["id"], kept_q["id"])
        for model_id in (kept_p["id"], kept_q["id"]):
            self.assertRegex(model_id, r"^m-[0-9a-f]{8}-r01-a$")
            self.assertNotIn(str(root), model_id)
        library = library_models(project_p)
        self.assertIn(kept_p["id"], library)
        self.assertIn(kept_q["id"], library)
        pinned = pin_model(project_p, kept_p["id"], FIXED_NOW)
        self.assertEqual((project_p / pinned["path"]).read_bytes(), (project_p / kept_p["path"]).read_bytes())
        self.assertNotEqual((project_p / pinned["path"]).read_bytes(), (project_q / kept_q["path"]).read_bytes())

    def test_candidate_ids_are_deterministic_and_cannot_be_forged(self):
        plan = plan_models(self.project, {"range": {"gender_presentation": "feminine", "age_range": "20-30",
                                                     "build": "varied", "skin_tone": "varied", "hair": "varied"}})
        again = plan_models(self.project, {"range": {"gender_presentation": "feminine", "age_range": "20-30",
                                                      "build": "varied", "skin_tone": "varied", "hair": "varied"}})
        self.assertEqual(plan["identities"]["A"]["id"], again["identities"]["A"]["id"])
        results = [self.render(job, png(index)) for index, job in enumerate(plan["jobs"])]
        forged = {**plan["identities"], "A": {**plan["identities"]["A"], "id": "m-00000000-r01-a"}}
        with self.assertRaises(ValidationError):
            register_models(self.project, {"kind": "candidates", "round": plan["round"], "results": results,
                                           "identities": forged}, FIXED_NOW)

if __name__ == "__main__":
    unittest.main()
