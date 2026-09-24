from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # discoverable from any cwd

from scripts.studio_core.errors import ValidationError
from scripts.studio_core.export import check_compatibility, export_production_pack
from scripts.studio_core.store import load_state
from scripts.studio_core.validation import validate_project
from tests.helpers import make_project, ready_project


def blocker_codes(error: ValidationError) -> list[str]:
    return [item["code"] for item in error.details]


class CompatibilityTests(unittest.TestCase):
    def test_water_based_ink_on_coated_shell_is_blocked(self):
        report = check_compatibility({"fabric": "coated_nylon", "decoration": "water_based_screen_print"})
        self.assertFalse(report["compatible"])
        self.assertEqual(report["status"], "incompatible")
        self.assertIn("heat_transfer", report["alternatives"])

    def test_free_text_facts_match_rules(self):
        report = check_compatibility(
            {"fabric": "100% ring-spun cotton single jersey", "decoration": "Plastisol screen print", "spot_colors": 1}
        )
        self.assertEqual(report["status"], "compatible")
        self.assertEqual(report["rule_id"], "screen_print_cotton_spot_colours")
        shell = check_compatibility({"fabric": "Nylon shell with DWR coating", "decoration": "water-based screen print"})
        self.assertFalse(shell["compatible"])

    def test_heat_sensitive_synthetic_blocks_high_heat_transfer(self):
        report = check_compatibility({"fabric": "nylon spandex", "decoration": "high_heat_transfer"})
        self.assertFalse(report["compatible"])
        self.assertIn("low_temp_transfer", report["alternatives"])

    def test_conditional_and_unknown_combinations_do_not_claim_compatibility(self):
        many = check_compatibility({"fabric": "cotton", "decoration": "screen_print", "spot_colors": 9})
        self.assertEqual(many["status"], "conditionally_compatible")
        unknown = check_compatibility({"fabric": "hemp silk", "decoration": "laser etching"})
        self.assertEqual(unknown["status"], "unverified")
        self.assertIsNone(unknown["compatible"])
        for report in (many, unknown):
            self.assertIn("producer", report["confirm"].lower())

    def test_every_rule_records_notes_and_producer_confirmation(self):
        rules = json.loads((Path(__file__).resolve().parents[1] / "data/compatibility-rules.json").read_text("utf-8"))
        ids = [rule["id"] for rule in rules["rules"]]
        self.assertEqual(len(ids), len(set(ids)))
        for rule in rules["rules"]:
            self.assertTrue(rule["notes"], rule["id"])
            self.assertIn("producer", rule["confirm"].lower(), rule["id"])
            if rule["result"] == "incompatible":
                self.assertTrue(rule["alternatives"], rule["id"])


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp.name)

    def tearDown(self):
        for path in self.tmp_path.rglob("*"):
            if path.is_file():
                os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        self.temp.cleanup()

    def test_export_blocks_unconfirmed_critical_assumption(self):
        project = ready_project(self.tmp_path, assumptions={"size_range": {"confirmed": False, "critical": True}})
        with self.assertRaises(ValidationError) as caught:
            export_production_pack(project)
        self.assertIn("unconfirmed_critical_assumption", blocker_codes(caught.exception))
        self.assertEqual(list((project / "production").glob("pack-*")), [])

    def test_export_requires_approval_and_master(self):
        project = make_project(self.tmp_path)
        with self.assertRaises(ValidationError) as caught:
            export_production_pack(project)
        codes = blocker_codes(caught.exception)
        self.assertIn("no_approved_design", codes)
        self.assertIn("no_production_master", codes)
        self.assertIn("missing_critical_answer", codes)

    def test_export_requires_master_placement_dimensions(self):
        project = ready_project(self.tmp_path, master={"print_width_mm": None, "offset_mm": None})
        with self.assertRaises(ValidationError) as caught:
            export_production_pack(project)
        self.assertIn("master_missing_dimensions", blocker_codes(caught.exception))

    def test_export_blocks_incompatible_method(self):
        project = ready_project(
            self.tmp_path,
            answers={"fiber_blend": "nylon with DWR coating", "decoration_method": "water-based screen print"},
            master={"decoration_method": "water-based screen print"},
        )
        with self.assertRaises(ValidationError) as caught:
            export_production_pack(project)
        self.assertIn("incompatible_production_method", blocker_codes(caught.exception))

    def test_unicode_export_paths_and_required_sections(self):
        pack = export_production_pack(ready_project(self.tmp_path, name="鬼 KIKI KAKA"))
        self.assertEqual(pack.name, "pack-v001")
        spec = (pack / "production-spec.md").read_text("utf-8")
        for heading in ("Placement", "Colour", "Material", "Sizing", "Tolerances", "Files"):
            self.assertIn(f"## {heading}", spec)
        self.assertIn("鬼 KIKI KAKA", spec)
        self.assertIn("300 × 120 mm", spec)
        self.assertIn("two print sizes", spec)
        self.assertNotIn("${", spec)
        masters = list((pack / "masters").iterdir())
        self.assertEqual(len(masters), 1)
        self.assertTrue(masters[0].name.startswith("鬼-kiki-kaka_v001_upper-back_MASTER_pack-v001"))

    def test_pack_manifest_hashes_every_file_and_checklist_is_complete(self):
        project = ready_project(self.tmp_path)
        pack = export_production_pack(project)
        manifest = json.loads((pack / "manifest.json").read_text("utf-8"))
        self.assertEqual(manifest["pack_version"], "pack-v001")
        self.assertEqual(manifest["approved_versions"], ["v001"])
        for item in manifest["files"]:
            digest = hashlib.sha256((pack / item["path"]).read_bytes()).hexdigest()
            self.assertEqual(item["sha256"], digest, item["path"])
        checklist = (pack / "handoff-checklist.md").read_text("utf-8")
        self.assertIn("- [ ]", checklist)
        self.assertIn("strike-off", checklist.lower())
        self.assertNotIn("${", checklist)
        self.assertEqual(load_state(project)["phase"], "production_exported")

    def test_second_export_is_a_new_version_and_the_first_is_untouched(self):
        project = ready_project(self.tmp_path)
        first = export_production_pack(project)
        before = {path.name: path.read_bytes() for path in first.rglob("*") if path.is_file()}
        second = export_production_pack(project)
        self.assertEqual(second.name, "pack-v002")
        after = {path.name: path.read_bytes() for path in first.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_edited_pack_is_reported_by_validation(self):
        project = ready_project(self.tmp_path)
        pack = export_production_pack(project)
        spec = pack / "production-spec.md"
        os.chmod(spec, stat.S_IRUSR | stat.S_IWUSR)
        spec.write_text("# edited", "utf-8")
        self.assertIn("pack_hash_mismatch", [item["code"] for item in validate_project(project)["errors"]])

    def test_export_lists_unconfirmed_low_risk_assumptions(self):
        project = ready_project(self.tmp_path, assumptions={"fit": {"confirmed": False}})
        pack = export_production_pack(project)
        self.assertIn("fit", (pack / "production-spec.md").read_text("utf-8").split("## Assumptions")[1])


if __name__ == "__main__":
    unittest.main()
