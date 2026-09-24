from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # discoverable from any cwd

from scripts.studio_core.errors import StudioError, ValidationError
from scripts.studio_core.options import (
    merge_concept,
    plan_options,
    register_options,
    render_option_cards,
    render_svg,
)
from scripts.studio_core.store import load_state
from tests.helpers import four_complete_briefs, four_results, make_project


class OptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp.name)
        self.project = make_project(self.tmp_path)

    def tearDown(self):
        self.temp.cleanup()

    def manifest(self) -> dict:
        return json.loads((self.project / "metadata/manifest.json").read_text("utf-8"))

    def test_plan_requires_three_practical_and_one_wildcard(self):
        plan = plan_options("back_typography", ["density", "alignment", "distress", "scale"], {"colors": 1})
        self.assertEqual([item["label"] for item in plan["slots"]], ["A", "B", "C", "W"])
        self.assertEqual(len({item["axis"] for item in plan["slots"]}), 4)
        self.assertEqual([item["wildcard"] for item in plan["slots"]], [False, False, False, True])
        self.assertEqual(plan["constraints"], {"colors": 1})
        for slot in plan["slots"]:
            self.assertTrue(slot["destination"].startswith("concepts/generated/back_typography/r01/"))

    def test_plan_rejects_duplicate_or_missing_axes(self):
        with self.assertRaises(ValidationError):
            plan_options("back_typography", ["scale", "scale", "density", "distress"], {})
        with self.assertRaises(ValidationError):
            plan_options("back_typography", ["scale", "density", "distress"], {})

    def test_register_records_generated_concepts_with_provenance(self):
        entries = register_options(self.project, four_results(self.project))
        self.assertEqual([entry["label"] for entry in entries], ["A", "B", "C", "W"])
        for entry in entries:
            self.assertEqual(entry["origin"], "generated_concept")
            self.assertFalse(entry["production_eligible"])
            digest = hashlib.sha256((self.project / entry["path"]).read_bytes()).hexdigest()
            self.assertEqual(entry["sha256"], digest)
            self.assertEqual(entry["renderer"], "test-renderer")
        self.assertEqual({item["id"] for item in self.manifest()["files"]}, {e["id"] for e in entries})
        state = load_state(self.project)
        self.assertEqual(state["concepts"][0]["decision_id"], "back_typography")
        self.assertEqual(state["concepts"][0]["ids"], [e["id"] for e in entries])

    def test_registered_entries_satisfy_manifest_schema(self):
        schema_path = Path(__file__).resolve().parents[1] / "schemas/manifest.schema.json"
        schema = json.loads(schema_path.read_text("utf-8"))
        entry_schema = schema["$defs"]["file"]
        self.assertEqual(
            set(entry_schema["properties"]["origin"]["enum"]),
            {"user_reference", "online_reference", "generated_concept", "approved_design", "production_master"},
        )
        for entry in register_options(self.project, four_results(self.project)):
            self.assertTrue(set(entry_schema["required"]).issubset(entry), entry["id"])
            self.assertIn(entry["origin"], entry_schema["properties"]["origin"]["enum"])

    def test_register_rejects_missing_label_or_duplicate_axis(self):
        before = self.manifest()
        with self.assertRaises(ValidationError):
            register_options(self.project, four_results(self.project, axes=["scale"] * 4))
        with self.assertRaises(ValidationError):
            register_options(self.project, four_results(self.project, labels=("A", "B", "C", "D")))
        self.assertEqual(self.manifest(), before)

    def test_register_rejects_files_outside_generated_folder(self):
        payload = four_results(self.project)
        outside = self.project / "references/user/option.svg"
        outside.write_text("<svg><text>A</text></svg>", encoding="utf-8")
        payload["results"][0]["path"] = "references/user/option.svg"
        with self.assertRaises(StudioError):
            register_options(self.project, payload)
        payload["results"][0]["path"] = "concepts/generated/../../references/user/option.svg"
        with self.assertRaises(StudioError):
            register_options(self.project, payload)

    def test_register_rejects_vector_preview_without_visible_label(self):
        payload = four_results(self.project)
        (self.project / payload["results"][3]["path"]).write_text("<svg><text>no label</text></svg>", "utf-8")
        with self.assertRaises(ValidationError):
            register_options(self.project, payload)

    def test_wildcard_must_state_the_convention_it_breaks(self):
        payload = four_results(self.project)
        del payload["results"][3]["convention_broken"]
        with self.assertRaises(ValidationError):
            register_options(self.project, payload)

    def test_second_registration_starts_a_new_round(self):
        first = register_options(self.project, four_results(self.project))
        second = register_options(self.project, four_results(self.project))
        self.assertTrue(first[0]["id"].endswith("-r01-A"))
        self.assertTrue(second[0]["id"].endswith("-r02-A"))

    def test_merge_records_both_parents(self):
        entries = {entry["label"]: entry for entry in register_options(self.project, four_results(self.project))}
        merged_path = self.project / "concepts/generated/back_typography/merge-A-C.svg"
        merged_path.write_text("<svg><text>A+C</text></svg>", encoding="utf-8")
        merged = merge_concept(
            self.project,
            {
                "decision_id": "back_typography",
                "path": "concepts/generated/back_typography/merge-A-C.svg",
                "parents": [entries["A"]["id"], entries["C"]["id"]],
                "description": "A's density with C's distress",
                "renderer": "test-renderer",
            },
        )
        self.assertEqual(merged["parents"], [entries["A"]["id"], entries["C"]["id"]])
        self.assertEqual(merged["origin"], "generated_concept")
        with self.assertRaises(ValidationError):
            merge_concept(
                self.project,
                {
                    "decision_id": "back_typography",
                    "path": "concepts/generated/back_typography/merge-A-C.svg",
                    "parents": [entries["A"]["id"], "unknown-concept"],
                    "renderer": "test-renderer",
                },
            )

    def test_svg_fallback_contains_visible_labels(self):
        path = render_svg(self.tmp_path, four_complete_briefs())
        svg = path.read_text("utf-8")
        for label in (">A<", ">B<", ">C<", ">W<"):
            self.assertIn(label, svg)
        for axis in ("density", "alignment", "distress", "scale"):
            self.assertIn(axis, svg)
        self.assertNotIn("http://", svg.replace("http://www.w3.org/2000/svg", ""))
        self.assertNotIn("https://", svg)

    def test_svg_fallback_escapes_user_text_and_rejects_unsafe_colours(self):
        briefs = four_complete_briefs()
        briefs[0]["title"] = "<script>alert(1)</script>"
        briefs[1]["colors"] = ['red" onload="alert(1)']
        svg = render_svg(self.tmp_path, briefs).read_text("utf-8")
        self.assertNotIn("<script>", svg)
        self.assertIn("&lt;script&gt;", svg)
        self.assertNotIn("onload", svg)

    def test_rendered_cards_register_as_four_options(self):
        cards = render_option_cards(self.project / "concepts/generated/back_typography/r01", four_complete_briefs())
        payload = {
            "decision_id": "back_typography",
            "results": [
                {
                    "label": brief["label"],
                    "axis": brief["axis"],
                    "path": str(cards[brief["label"]].relative_to(self.project)),
                    "renderer": "svg-fallback",
                    "prompt": brief["brief"],
                    "convention_broken": "Oversized type" if brief["label"] == "W" else None,
                }
                for brief in four_complete_briefs()
            ],
        }
        self.assertEqual(len(register_options(self.project, payload)), 4)


if __name__ == "__main__":
    unittest.main()
