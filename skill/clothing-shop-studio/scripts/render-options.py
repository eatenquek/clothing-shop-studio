#!/usr/bin/env python3
"""Render four labelled A/B/C/W SVG previews when no raster image tool is available.

Input JSON (stdin or --input): {"output_dir": "<project>/concepts/generated/<decision>/rNN",
"briefs": [{"label", "axis", "title", "brief", "garment", "placement", "colors"}, ...]}.
Writes option-A.svg ... option-W.svg plus contact-sheet.svg and prints their paths as JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from studio_core import SCHEMA_VERSION
from studio_core.config import ensure_external
from studio_core.errors import StudioError, ValidationError
from studio_core.options import render_option_cards, render_svg

BUNDLE_DIR = Path(__file__).resolve().parents[1]
COMMAND = "render_options"


def emit(payload: dict) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", help="Read the JSON payload from this file instead of stdin")
    args = parser.parse_args(argv)
    try:
        try:
            payload = json.loads(Path(args.input).read_text("utf-8")) if args.input else json.load(sys.stdin)
        except json.JSONDecodeError as exc:
            raise ValidationError("Input is not valid JSON.", recovery="Correct the JSON and retry.") from exc
        if not isinstance(payload, dict) or not payload.get("output_dir"):
            raise ValidationError(
                "Provide `output_dir` and four `briefs`.",
                field="output_dir",
                recovery="Use the destination folder from the generate_options plan.",
            )
        # Previews belong to the external project, never to the installed skill.
        output_dir = ensure_external(Path(os.path.expanduser(payload["output_dir"])), BUNDLE_DIR)
        cards = render_option_cards(output_dir, payload.get("briefs"))
        sheet = render_svg(output_dir, payload.get("briefs"))
        emit(
            {
                "ok": True,
                "command": COMMAND,
                "schema_version": SCHEMA_VERSION,
                "data": {"cards": {label: str(path) for label, path in cards.items()}, "contact_sheet": str(sheet)},
            }
        )
        return 0
    except StudioError as exc:
        emit({"ok": False, "command": COMMAND, "schema_version": SCHEMA_VERSION, "error": exc.as_dict()})
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
