#!/usr/bin/env python3
"""One-time importer: approved online-reference Markdown -> data/inspiration-library.json.

Only metadata and remote URLs are imported. No third-party image is downloaded.
The import fails unless the sources contain exactly references 01-70, every record
carries the `third-party-inspiration-only` rights label, and each source file
records the user's approval date.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REVIEW_DIR = Path(
    "/Users/quekee/.codex/visualizations/2026/09/21/01a0c2de-4ae5-7490-90dc-d4f5a332f7ed/"
    "clothing-shop-studio-reference-review"
)
DEFAULT_SOURCES = (REVIEW_DIR / "online-references.md", REVIEW_DIR / "online-references-21-70.md")
FIRST_FILE_CATEGORY = "Core garments and techniques"
RIGHTS = "third-party-inspiration-only"
EXPECTED_IDS = [f"{number:02d}" for number in range(1, 71)]

APPROVAL = re.compile(r"status:\s*APPROVED\b.*?(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
ENTRY = re.compile(r"^##\s+(\d{2})\s+[—-]\s+(.+?)\s*$")
SECTION = re.compile(r"^##\s+(?!\d)(.+?)\s*$")
FIELD = re.compile(r"^-\s+(Role|Rights|Source|Image|Teaches|Caution|Preview fallback):\s*(.*?)\s*$")
SOURCE_LINK = re.compile(r"^\[(.+)\]\((https://[^)\s]+)\)$")
URL = re.compile(r"^https://\S+$")


class ImportError_(Exception):
    """Raised when the approved sources do not describe a complete, valid library."""


def parse(text: str, default_category: str | None) -> list[dict]:
    approval = APPROVAL.search(text)
    if not approval:
        raise ImportError_("Source file does not record an APPROVED status with a date.")
    approved_on = approval.group(1)
    records, current, category = [], None, default_category
    for line in text.splitlines():
        if match := ENTRY.match(line):
            current = {"id": match.group(1), "title": match.group(2), "category": category, "fields": {}}
            records.append(current)
        elif match := SECTION.match(line):
            category, current = match.group(1), None
        elif current is not None and (match := FIELD.match(line)):
            current["fields"][match.group(1)] = match.group(2)
    return [_record(item, approved_on) for item in records]


def _record(raw: dict, approved_on: str) -> dict:
    fields, ident = raw["fields"], raw["id"]
    missing = [name for name in ("Role", "Rights", "Source", "Image", "Teaches") if not fields.get(name)]
    if missing:
        raise ImportError_(f"Reference {ident} is missing: {', '.join(missing)}.")
    if fields["Rights"] != RIGHTS:
        raise ImportError_(f"Reference {ident} has rights {fields['Rights']!r}; expected {RIGHTS!r}.")
    source = SOURCE_LINK.match(fields["Source"])
    if not source:
        raise ImportError_(f"Reference {ident} source must be a Markdown link to an https page.")
    if not URL.match(fields["Image"]):
        raise ImportError_(f"Reference {ident} image must be an https URL.")
    if not raw["category"]:
        raise ImportError_(f"Reference {ident} has no category.")
    record = {
        "id": ident,
        "title": raw["title"],
        "category": raw["category"],
        "role": [part.strip().lower() for part in fields["Role"].split("/") if part.strip()],
        "source_name": source.group(1),
        "source_page": source.group(2),
        "remote_image_url": fields["Image"],
        "rights": RIGHTS,
        "verification": "user_approved",
        "verified_on": approved_on,
        "teaches": fields["Teaches"],
    }
    if fields.get("Caution"):
        record["caution"] = fields["Caution"]
    if fields.get("Preview fallback"):
        record["preview_fallback"] = fields["Preview fallback"]
    return record


def build(sources: list[Path]) -> list[dict]:
    records = []
    for index, path in enumerate(sources):
        records += parse(Path(path).read_text("utf-8"), FIRST_FILE_CATEGORY if index == 0 else None)
    records.sort(key=lambda item: item["id"])
    ids = [item["id"] for item in records]
    if ids != EXPECTED_IDS:
        duplicates = sorted({ident for ident in ids if ids.count(ident) > 1})
        missing = sorted(set(EXPECTED_IDS) - set(ids))
        raise ImportError_(f"Expected references 01-70 exactly; missing {missing}, duplicated {duplicates}.")
    return records


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sources", nargs="+", type=Path, default=list(DEFAULT_SOURCES))
    args = parser.parse_args(argv)
    try:
        records = build(args.sources)
    except (ImportError_, OSError) as exc:
        print(f"import failed: {exc}", file=sys.stderr)
        return 1
    args.output.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(records)} references to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
