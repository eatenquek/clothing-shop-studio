"""Four-way A/B/C/W visual option planning, registration, lineage, and SVG fallback."""

from __future__ import annotations

import hashlib
import html
import re
import textwrap
from pathlib import Path

from .config import resolve_inside
from .errors import ValidationError
from .store import _utc_now, append_event, load_state, write_atomic

LABELS = ("A", "B", "C", "W")
GENERATED_DIR = Path("concepts/generated")
DECISION_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
PREVIEW_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".html"}
TEXT_SUFFIXES = {".svg", ".html"}
HEX_COLOUR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
WILDCARD_RULE = "Break exactly one stated convention while keeping every hard constraint and production feasibility."


def _decision_id(value) -> str:
    if not isinstance(value, str) or not DECISION_PATTERN.match(value):
        raise ValidationError(
            "Decision id must be a lowercase snake_case identifier.",
            field="decision_id",
            recovery="Name the visual decision, for example `back_typography` or `base_color`.",
        )
    return value


def _distinct_axes(axes, field: str = "axes") -> list[str]:
    if not isinstance(axes, list) or len(axes) != len(LABELS):
        raise ValidationError(
            "Four visual axes are required: three practical options and one wildcard.",
            field=field,
            recovery="Name one distinct axis for each of A, B, C, and W.",
        )
    cleaned = [axis.strip() if isinstance(axis, str) else "" for axis in axes]
    if not all(cleaned) or len({axis.lower() for axis in cleaned}) != len(LABELS):
        raise ValidationError(
            "Four distinct visual axes are required.",
            field=field,
            recovery="Give each option its own axis so the four previews differ meaningfully.",
        )
    return cleaned


def _destination(decision_id: str, round_number: int, label: str) -> str:
    return f"{GENERATED_DIR.as_posix()}/{decision_id}/r{round_number:02d}/option-{label}"


def plan_options(
    decision_id: str,
    axes: list[str],
    constraints: dict,
    briefs: list[str] | None = None,
    round_number: int = 1,
) -> dict:
    """Return the A/B/C/W slot plan the agent renders before calling register."""
    decision_id = _decision_id(decision_id)
    axes = _distinct_axes(axes)
    if briefs is not None and (not isinstance(briefs, list) or len(briefs) != len(LABELS)):
        raise ValidationError(
            "Provide either no briefs or exactly four.",
            field="briefs",
            recovery="Send one creative brief per option.",
        )
    slots = []
    for index, (label, axis) in enumerate(zip(LABELS, axes)):
        slot = {
            "label": label,
            "axis": axis,
            "wildcard": label == "W",
            "destination": _destination(decision_id, round_number, label),
        }
        if briefs is not None:
            slot["brief"] = briefs[index]
        if label == "W":
            slot["wildcard_rule"] = WILDCARD_RULE
        slots.append(slot)
    return {
        "decision_id": decision_id,
        "round": round_number,
        "constraints": constraints or {},
        "label_rule": "Show each slot's label inside its image or on a labelled contact sheet.",
        "slots": slots,
    }


def next_round(state: dict, decision_id: str) -> int:
    return 1 + sum(1 for item in state.get("concepts", []) if item.get("decision_id") == decision_id)


def _resolve_generated(project: Path, relative, field: str = "path") -> tuple[Path, str]:
    candidate, normalised = resolve_inside(project, relative, f"{GENERATED_DIR.as_posix()}/", field)
    if candidate.suffix.lower() not in PREVIEW_SUFFIXES:
        raise ValidationError(
            "Unsupported preview format.",
            field=field,
            path=relative,
            recovery=f"Use one of: {', '.join(sorted(PREVIEW_SUFFIXES))}.",
        )
    return candidate, normalised


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _required_text(item: dict, key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(
            f"Each option needs a `{key}`.",
            field=key,
            recovery=f"Record the {key} used to produce the preview.",
        )
    return value.strip()


def register_options(project_dir: Path, payload: dict, now: str | None = None) -> list[dict]:
    """Record four rendered previews as generated concepts with provenance."""
    project = Path(project_dir)
    decision_id = _decision_id(payload.get("decision_id"))
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != len(LABELS):
        raise ValidationError(
            "Register exactly four previews: A, B, C, and W.",
            field="results",
            recovery="Render all four planned options before registering them.",
        )
    by_label = {item.get("label"): item for item in results if isinstance(item, dict)}
    if set(by_label) != set(LABELS):
        raise ValidationError(
            "Previews must be labelled A, B, C, and W exactly once each.",
            field="label",
            recovery="Relabel the previews and retry.",
        )
    ordered = [by_label[label] for label in LABELS]
    axes = _distinct_axes([item.get("axis") for item in ordered], field="axis")
    if not isinstance(by_label["W"].get("convention_broken"), str) or not by_label["W"]["convention_broken"].strip():
        raise ValidationError(
            "The wildcard must state which convention it breaks.",
            field="convention_broken",
            recovery="Describe the one convention W departs from while keeping hard constraints.",
        )

    state = load_state(project)
    round_number = payload.get("round") or next_round(state, decision_id)
    timestamp = now or _utc_now()
    entries, seen_paths = [], set()
    for label, axis, item in zip(LABELS, axes, ordered):
        absolute, relative = _resolve_generated(project, item.get("path"))
        if relative in seen_paths:
            raise ValidationError(
                "Each option needs its own preview file.",
                field="path",
                path=relative,
                recovery="Save one file per option.",
            )
        seen_paths.add(relative)
        if absolute.suffix.lower() in TEXT_SUFFIXES and f">{label}<" not in absolute.read_text("utf-8", errors="replace"):
            raise ValidationError(
                f"Preview {label} does not show its label.",
                field="label",
                path=relative,
                recovery="Render the option label visibly inside the preview.",
            )
        entry = {
            "id": f"{decision_id}-r{round_number:02d}-{label}",
            "origin": "generated_concept",
            "decision_id": decision_id,
            "round": round_number,
            "label": label,
            "axis": axis,
            "wildcard": label == "W",
            "path": relative,
            "sha256": _sha256(absolute),
            "renderer": _required_text(item, "renderer"),
            "prompt": item.get("prompt"),
            "parents": list(item.get("parents") or []),
            "registered_at": timestamp,
            "production_eligible": False,
        }
        if label == "W":
            entry["convention_broken"] = by_label["W"]["convention_broken"].strip()
        entries.append(entry)

    contact_sheet = None
    if payload.get("contact_sheet"):
        _, contact_sheet = _resolve_generated(project, payload["contact_sheet"], field="contact_sheet")
    append_event(
        project,
        {
            "type": "options_registered",
            "decision_id": decision_id,
            "round": round_number,
            "entries": entries,
            "contact_sheet": contact_sheet,
        },
        timestamp,
    )
    return entries


def merge_concept(project_dir: Path, payload: dict, now: str | None = None) -> dict:
    """Register one combined preview whose lineage names two or more existing concepts."""
    project = Path(project_dir)
    decision_id = _decision_id(payload.get("decision_id"))
    parents = payload.get("parents")
    if not isinstance(parents, list) or len(set(parents)) < 2:
        raise ValidationError(
            "A merged concept needs at least two distinct parent concepts.",
            field="parents",
            recovery="List the concept ids whose elements were combined.",
        )
    state = load_state(project)
    concepts = {item["id"] for item in state.get("files", []) if item.get("origin") == "generated_concept"}
    unknown = [parent for parent in parents if parent not in concepts]
    if unknown:
        raise ValidationError(
            f"Unknown parent concept: {', '.join(unknown)}.",
            field="parents",
            recovery="Use ids returned by generate_options register.",
        )
    absolute, relative = _resolve_generated(project, payload.get("path"))
    merges = sum(
        1 for item in state.get("files", []) if item.get("decision_id") == decision_id and item.get("label") == "M"
    )
    timestamp = now or _utc_now()
    entry = {
        "id": f"{decision_id}-m{merges + 1:02d}",
        "origin": "generated_concept",
        "decision_id": decision_id,
        "label": "M",
        "axis": None,
        "wildcard": False,
        "path": relative,
        "sha256": _sha256(absolute),
        "renderer": _required_text(payload, "renderer"),
        "prompt": payload.get("prompt"),
        "description": payload.get("description"),
        "parents": list(parents),
        "registered_at": timestamp,
        "production_eligible": False,
    }
    append_event(project, {"type": "concept_merged", "entry": entry}, timestamp)
    return entry


# --- SVG fallback -----------------------------------------------------------

CARD_WIDTH, CARD_HEIGHT = 800, 600
BACK_PLACEMENTS = {"upper_back", "full_back", "back_yoke", "back_neck"}
GARMENT_OUTLINES = {
    # Simple flat outlines drawn in a 300×300 box; long sleeves extend past the hem line.
    "tee": "M90 20 L130 10 Q150 30 170 10 L210 20 L280 70 L250 110 L220 90 L220 290 L80 290 L80 90 L50 110 L20 70 Z",
    "long_sleeve": "M90 20 L130 10 Q150 30 170 10 L210 20 L270 150 L290 260 L255 265 L220 150 L220 290 L80 290 "
    "L80 150 L45 265 L10 260 L30 150 Z",
    "hoodie": "M90 30 L110 0 Q150 -15 190 0 L210 30 L270 150 L290 260 L255 265 L220 150 L220 290 L80 290 "
    "L80 150 L45 265 L10 260 L30 150 Z",
}
PLACEMENT_BOXES = {
    # x, y, width, height inside the 300×300 garment box.
    "centre_chest": (125, 60, 50, 22),
    "center_chest": (125, 60, 50, 22),
    "left_chest": (170, 60, 30, 22),
    "full_front": (100, 60, 100, 120),
    "upper_back": (95, 45, 110, 70),
    "full_back": (95, 45, 110, 170),
    "back_yoke": (115, 35, 70, 25),
    "back_neck": (135, 30, 30, 14),
    "sleeve": (235, 120, 28, 60),
}


def _text(value, limit: int = 90) -> str:
    text = "" if value is None else str(value)
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return html.escape(text, quote=True)


def _validate_briefs(briefs) -> list[dict]:
    if not isinstance(briefs, list):
        raise ValidationError("Briefs must be a list.", field="briefs", recovery="Send four briefs.")
    by_label = {item.get("label"): item for item in briefs if isinstance(item, dict)}
    if set(by_label) != set(LABELS) or len(briefs) != len(LABELS):
        raise ValidationError(
            "Render exactly four briefs labelled A, B, C, and W.",
            field="briefs",
            recovery="Send one brief per planned slot.",
        )
    ordered = [by_label[label] for label in LABELS]
    _distinct_axes([item.get("axis") for item in ordered], field="axis")
    return ordered


def _card(brief: dict, x: int = 0, y: int = 0) -> str:
    label = brief["label"]
    garment = GARMENT_OUTLINES.get(brief.get("garment"), GARMENT_OUTLINES["tee"])
    placement = brief.get("placement")
    box = PLACEMENT_BOXES.get(placement)
    colours = [colour for colour in brief.get("colors", []) if isinstance(colour, str) and HEX_COLOUR.match(colour)]
    body = colours[0] if colours else "#D9D9D9"
    ink = colours[1] if len(colours) > 1 else "#1A1A1A"
    view = "Back view" if placement in BACK_PLACEMENTS else "Front view"
    parts = [
        f'<g transform="translate({x},{y})">',
        f'<rect x="8" y="8" width="{CARD_WIDTH - 16}" height="{CARD_HEIGHT - 16}" rx="18" fill="#FFFFFF" stroke="#222222" stroke-width="3"/>',
        f'<text x="40" y="120" font-family="Helvetica, Arial, sans-serif" font-size="110" font-weight="700" fill="#111111">{label}</text>',
        f'<text x="180" y="70" font-family="Helvetica, Arial, sans-serif" font-size="30" font-weight="700" fill="#111111">{_text(brief.get("title"), 32)}</text>',
        f'<text x="180" y="110" font-family="Helvetica, Arial, sans-serif" font-size="22" fill="#444444">Axis: {_text(brief.get("axis"), 40)}</text>',
    ]
    if label == "W":
        parts.append(
            '<text x="180" y="140" font-family="Helvetica, Arial, sans-serif" font-size="20" font-weight="700" fill="#B00020">WILDCARD</text>'
        )
    parts.extend(
        [
            '<g transform="translate(60,190)">',
            f'<path d="{garment}" fill="{body}" stroke="#222222" stroke-width="3"/>',
        ]
    )
    if box:
        bx, by, bw, bh = box
        parts.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" fill="{ink}" opacity="0.85"/>')
    parts.append("</g>")
    parts.extend(
        [
            f'<text x="400" y="230" font-family="Helvetica, Arial, sans-serif" font-size="22" fill="#222222">{view}</text>',
            f'<text x="400" y="265" font-family="Helvetica, Arial, sans-serif" font-size="22" fill="#222222">Placement: {_text(placement or "unspecified", 28)}</text>',
        ]
    )
    for index, colour in enumerate(colours[:5]):
        parts.append(
            f'<rect x="{400 + index * 60}" y="290" width="48" height="48" fill="{colour}" stroke="#222222" stroke-width="2"/>'
        )
    # Wrap on words before escaping so lines stay inside the card and entities stay whole.
    raw_brief = "" if brief.get("brief") is None else str(brief["brief"])
    lines = textwrap.wrap(raw_brief, width=34, max_lines=5, placeholder="…")
    for line_number, line in enumerate(lines):
        parts.append(
            f'<text x="400" y="{380 + line_number * 30}" font-family="Helvetica, Arial, sans-serif" font-size="20" fill="#333333">{html.escape(line, quote=True)}</text>'
        )
    parts.append(
        f'<text x="40" y="{CARD_HEIGHT - 30}" font-family="Helvetica, Arial, sans-serif" font-size="16" fill="#777777">Concept preview only — not a production master.</text>'
    )
    parts.append("</g>")
    return "".join(parts)


def _svg(width: int, height: int, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<rect width="{width}" height="{height}" fill="#F4F4F4"/>{body}</svg>\n'
    )


def render_svg(output_dir: Path, briefs: list[dict], filename: str = "contact-sheet.svg") -> Path:
    """Write a self-contained 2×2 labelled contact sheet and return its path."""
    ordered = _validate_briefs(briefs)
    positions = [(0, 0), (CARD_WIDTH, 0), (0, CARD_HEIGHT), (CARD_WIDTH, CARD_HEIGHT)]
    body = "".join(_card(brief, x, y) for brief, (x, y) in zip(ordered, positions))
    path = Path(output_dir) / filename
    write_atomic(path, _svg(CARD_WIDTH * 2, CARD_HEIGHT * 2, body).encode("utf-8"))
    return path


def render_option_cards(output_dir: Path, briefs: list[dict]) -> dict[str, Path]:
    """Write one labelled SVG per option so each can be registered individually."""
    ordered = _validate_briefs(briefs)
    paths = {}
    for brief in ordered:
        path = Path(output_dir) / f"option-{brief['label']}.svg"
        write_atomic(path, _svg(CARD_WIDTH, CARD_HEIGHT, _card(brief)).encode("utf-8"))
        paths[brief["label"]] = path
    return paths
