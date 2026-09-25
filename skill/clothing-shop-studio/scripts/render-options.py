#!/usr/bin/env python3
"""Render four labelled A/B/C/W SVG previews when no raster image tool is available.

Input JSON (stdin or --input): {"project_dir": "<project>",
"output_dir": "<project>/concepts/generated/<decision>/rNN",
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
from studio_core.paths import project_area
from studio_core.errors import StudioError, UnsafePathError, ValidationError
from studio_core.options import render_option_cards, render_svg
from studio_core.store import load_state

BUNDLE_DIR = Path(__file__).resolve().parents[1]
COMMAND = "render_options"


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValidationError(
            f"Invalid command line: {message}",
            field="arguments",
            recovery="Pass one optional `--input` JSON file, or send the JSON payload on stdin.",
        )


def emit(payload: dict) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


def main(argv=None) -> int:
    try:
        parser = JsonArgumentParser(description=__doc__.splitlines()[0])
        parser.add_argument("--input", help="Read the JSON payload from this file instead of stdin")
        args = parser.parse_args(argv)
        try:
            payload = json.loads(Path(args.input).read_text("utf-8")) if args.input else json.load(sys.stdin)
        except OSError as exc:
            raise ValidationError(
                "Input file could not be read.",
                path=str(args.input),
                recovery="Provide a readable JSON input file or send the payload on stdin.",
            ) from exc
        except json.JSONDecodeError as exc:
            raise ValidationError("Input is not valid JSON.", recovery="Correct the JSON and retry.") from exc
        if not isinstance(payload, dict) or not payload.get("project_dir") or not payload.get("output_dir"):
            raise ValidationError(
                "Provide `project_dir`, `output_dir`, and four `briefs`.",
                field="project_dir",
                recovery="Use the destination folder from the generate_options plan.",
            )
        project = ensure_external(Path(os.path.expanduser(payload["project_dir"])), BUNDLE_DIR)
        load_state(project)
        output_dir = Path(os.path.expanduser(payload["output_dir"])).resolve(strict=False)
        generated_root = project_area(project, "concepts/generated").resolve(strict=False)
        try:
            output_dir.relative_to(generated_root)
        except ValueError as exc:
            raise UnsafePathError(
                "Rendered options must stay inside this project's concepts/generated folder.",
                field="output_dir",
                path=str(output_dir),
                recovery="Use the absolute destination returned by generate_options plan.",
            ) from exc
        targets = [output_dir / f"option-{label}.svg" for label in "ABCW"] + [output_dir / "contact-sheet.svg"]
        if not payload.get("overwrite") and any(path.exists() for path in targets):
            raise ValidationError(
                "Rendering would overwrite an existing option round.",
                field="overwrite",
                path=str(output_dir),
                recovery="Use a new planned round, or set `overwrite: true` before registration when replacement is intentional.",
            )
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
    except Exception:
        exc = StudioError(
            "Rendering failed unexpectedly.",
            recovery="Retry once, then validate the skill bundle and report the input if it persists.",
        )
        emit({"ok": False, "command": COMMAND, "schema_version": SCHEMA_VERSION, "error": exc.as_dict()})
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
