from __future__ import annotations

import copy
import unittest
from pathlib import Path

from tools import family_manifest


REPO = Path(__file__).resolve().parents[1]


class FamilyManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifest = family_manifest.load_manifest(REPO)

    def invalid(self, mutate, message: str) -> None:
        manifest = copy.deepcopy(self.manifest)
        mutate(manifest)
        with self.assertRaisesRegex(RuntimeError, message):
            family_manifest.validate_manifest(REPO, manifest)

    def test_committed_manifest_defines_the_nine_member_family(self):
        manifest = self.manifest
        self.assertEqual(manifest["family"], "clothing-shop-studio")
        self.assertEqual(manifest["family_version"], 1)
        self.assertEqual(manifest["family_interface"], 1)
        self.assertEqual(len(manifest["wrappers"]), 9)
        self.assertEqual(
            [member["name"] for member in family_manifest.ordered_members(REPO, manifest)],
            ["clothing-shop-studio"] + [item["name"] for item in manifest["wrappers"]],
        )

    def test_duplicate_and_invalid_names_are_refused(self):
        self.invalid(
            lambda value: value["wrappers"].__setitem__(1, copy.deepcopy(value["wrappers"][0])),
            "duplicate.*clothing-new",
        )
        self.invalid(lambda value: value["wrappers"][0].__setitem__("name", "Clothing New"), "name")
        self.invalid(lambda value: value["wrappers"][0].__setitem__("name", "a" * 65), "name")

    def test_interface_ranges_are_required_and_ordered(self):
        self.invalid(lambda value: value["wrappers"][0].pop("core_interface_min"), "core_interface_min")
        self.invalid(
            lambda value: value["wrappers"][0].update(
                {"core_interface_min": 3, "core_interface_max": 2}
            ),
            "interface range",
        )

    def test_unknown_commands_and_missing_scripts_are_refused(self):
        self.invalid(
            lambda value: value["wrappers"][0]["operations"].append({"command": "invented", "modes": []}),
            "unknown command.*invented",
        )
        self.invalid(
            lambda value: value["wrappers"][2]["scripts"].append("scripts/not-there.py"),
            "missing script",
        )

    def test_reference_files_headings_and_mode_tokens_are_required(self):
        self.invalid(
            lambda value: value["wrappers"][0]["references"][0].__setitem__(
                "path", "references/missing.md"
            ),
            "missing reference",
        )
        self.invalid(
            lambda value: value["wrappers"][2]["references"][0]["sections"].append("Not a heading"),
            "missing heading",
        )
        self.invalid(
            lambda value: value["wrappers"][2]["operations"][0]["modes"].append("teleport"),
            "undocumented mode.*teleport",
        )

    def test_manifest_does_not_copy_seller_notice_urls(self):
        self.invalid(
            lambda value: value["wrappers"][2]["gates"].append("https://example.invalid/notice"),
            "URL",
        )

    def test_complete_operation_mode_sets_are_present(self):
        by_name = {item["name"]: item for item in self.manifest["wrappers"]}
        options = {item["command"]: item["modes"] for item in by_name["clothing-options"]["operations"]}
        extract = {item["command"]: item["modes"] for item in by_name["clothing-extract"]["operations"]}
        self.assertEqual(options["generate_options"], ["plan", "register", "merge"])
        self.assertEqual(extract["extract"], ["inventory", "confirm", "consent", "plan", "register", "decide"])


if __name__ == "__main__":
    unittest.main()
