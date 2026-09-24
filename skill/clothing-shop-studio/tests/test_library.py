from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".heic", ".tif", ".tiff", ".bmp"}
ROLES = {"fit", "material", "construction", "decoration", "artwork", "scene", "presentation", "branding", "production"}


class LibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = json.loads((ROOT / "data/inspiration-library.json").read_text("utf-8"))

    def test_library_has_70_unique_inspiration_only_records(self):
        self.assertEqual(len(self.items), 70)
        self.assertEqual([item["id"] for item in self.items], [f"{number:02d}" for number in range(1, 71)])
        self.assertTrue(all(item["rights"] == "third-party-inspiration-only" for item in self.items))
        self.assertTrue(all(item["source_page"].startswith("https://") for item in self.items))

    def test_every_record_is_complete(self):
        required = {
            "id", "title", "category", "role", "source_name", "source_page",
            "remote_image_url", "rights", "verification", "verified_on", "teaches",
        }
        for item in self.items:
            self.assertTrue(required.issubset(item), item["id"])
            self.assertTrue(item["title"] and item["teaches"] and item["source_name"], item["id"])
            self.assertTrue(set(item["role"]).issubset(ROLES) and item["role"], item["id"])
            self.assertTrue(item["remote_image_url"].startswith("https://"), item["id"])
            self.assertEqual(item["verification"], "user_approved")
            self.assertRegex(item["verified_on"], r"^\d{4}-\d{2}-\d{2}$")

    def test_library_contains_no_local_third_party_images(self):
        media = [path for path in ROOT.rglob("*") if path.suffix.lower() in MEDIA_SUFFIXES]
        self.assertEqual(media, [])

    def test_library_guide_states_rights_and_remote_previews(self):
        guide = (ROOT / "references/inspiration-library.md").read_text("utf-8")
        self.assertIn("third-party-inspiration-only", guide)
        self.assertIn("remote_image_url", guide)


class ReferenceRouteTests(unittest.TestCase):
    """Every interview route must land on a real heading in a bundled reference file."""

    @staticmethod
    def anchors(path: Path) -> set[str]:
        headings = re.findall(r"^#{1,6}\s+(.+?)\s*$", path.read_text("utf-8"), flags=re.MULTILINE)
        return {re.sub(r"[^\w\- ]", "", heading.lower()).strip().replace(" ", "-") for heading in headings}

    def test_interview_options_sources_resolve(self):
        graph = json.loads((ROOT / "data/interview-graph.json").read_text("utf-8"))["questions"]
        for node in graph:
            filename, _, anchor = node["options_source"].partition("#")
            path = ROOT / "references" / filename
            self.assertTrue(path.is_file(), f"{node['id']}: {filename} is missing")
            self.assertIn(anchor, self.anchors(path), f"{node['id']}: #{anchor} not found in {filename}")


if __name__ == "__main__":
    unittest.main()
