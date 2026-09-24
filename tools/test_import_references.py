"""Tests for the one-time reference importer (development tool; not installed)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from import_references import ImportError_, build, parse

HEADER = "# Refs\n\n**Library status: APPROVED — references accepted by the user on 2026-09-24.**\n\n"


def entry(number: int, rights: str = "third-party-inspiration-only") -> str:
    return (
        f"## {number:02d} — Item {number}\n\n"
        "- Role: fit / construction\n"
        f"- Rights: {rights}\n"
        f"- Source: [Maker {number}](https://example.com/{number})\n"
        f"- Image: https://cdn.example.com/{number}.jpg\n\n"
        f"![Reference preview](https://cdn.example.com/{number}.jpg)\n"
        "- Teaches: something useful.\n\n"
    )


class ImporterTests(unittest.TestCase):
    def write(self, name: str, text: str) -> Path:
        path = Path(self.temp.name) / name
        path.write_text(text, "utf-8")
        return path

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def test_parses_fields_roles_and_section_categories(self):
        text = HEADER + "## Materials\n\n" + entry(51) + "- Caution: marketplace source.\n"
        [record] = parse(text, None)
        self.assertEqual(record["role"], ["fit", "construction"])
        self.assertEqual(record["category"], "Materials")
        self.assertEqual(record["source_page"], "https://example.com/51")
        self.assertEqual(record["verified_on"], "2026-09-24")
        self.assertEqual(record["caution"], "marketplace source.")

    def test_builds_exactly_70_sorted_records(self):
        first = self.write("a.md", HEADER + "".join(entry(n) for n in range(1, 21)))
        second = self.write("b.md", HEADER + "## Rest\n\n" + "".join(entry(n) for n in range(70, 20, -1)))
        records = build([first, second])
        self.assertEqual([item["id"] for item in records], [f"{n:02d}" for n in range(1, 71)])

    def test_missing_or_duplicate_ids_fail(self):
        first = self.write("a.md", HEADER + "".join(entry(n) for n in range(1, 21)))
        short = self.write("b.md", HEADER + "## Rest\n\n" + "".join(entry(n) for n in range(21, 70)))
        with self.assertRaises(ImportError_):
            build([first, short])

    def test_wrong_rights_or_unapproved_file_fails(self):
        with self.assertRaises(ImportError_):
            parse(HEADER + entry(1, rights="cc-by"), "Core")
        with self.assertRaises(ImportError_):
            parse("# Refs\n\nDraft only.\n\n" + entry(1), "Core")


if __name__ == "__main__":
    unittest.main()
