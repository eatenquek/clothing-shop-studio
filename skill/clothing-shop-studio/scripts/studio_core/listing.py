"""Taobao-style listing concept: a visual mock that carries no unconfirmed facts."""

from __future__ import annotations

import html
import os
from pathlib import Path

from .errors import ValidationError
from .paths import area_relative, project_area, resolve_stored
from .presentation import (
    PRESENTATION_FOLDERS,
    file_index,
    kept_ids,
    listing_eligible,
    record_decision,
    register_entries,
    sha256,
)
from .store import _utc_now, append_event, load_state, write_atomic

SLOTS = ("hero", "white_background", "front", "three_quarter", "back")
FOLDER = PRESENTATION_FOLDERS["listing_concept"]
TAG = "Concept — not a live listing"


def _descends_from(entry: dict, files: dict[str, dict], targets: set[str]) -> bool:
    """True when the entry's parent graph reaches one of the target file ids."""
    stack, seen = list(entry.get("parents") or []), set()
    while stack:
        parent_id = stack.pop()
        if parent_id in targets:
            return True
        if parent_id in seen or parent_id not in files:
            continue
        seen.add(parent_id)
        stack.extend(files[parent_id].get("parents") or [])
    return False


def _pick(state: dict, version: str) -> dict:
    files = file_index(state)
    approved = [item for item in state.get("files", []) if item.get("origin") == "approved_design"
                and item.get("version") == version and item.get("role") != "review_evidence"]
    design_ids = {item["id"] for item in approved}
    kept = kept_ids(state, "tryon") | kept_ids(state, "garment")
    slots = dict.fromkeys(SLOTS)
    for entry in state.get("files", []):
        if entry["id"] not in kept or not listing_eligible(entry, files):
            continue
        if entry["origin"] == "tryon_image" and design_ids & set(entry["parents"]) and slots[entry["pose"]] is None:
            slots[entry["pose"]] = entry["id"]
        if (entry["origin"] == "extracted_garment" and slots["white_background"] is None
                and _descends_from(entry, files, design_ids)):
            slots["white_background"] = entry["id"]
    slots["hero"] = slots["front"] or slots["three_quarter"]
    return slots


def build_listing(project: Path, payload: dict, now: str | None = None) -> dict:
    state = load_state(project)
    version = payload.get("version")
    if version not in {item["version"] for item in state.get("approvals", [])}:
        raise ValidationError("Build a listing concept from a recorded approved version.", field="version",
                              recovery="Send an approved version such as v001.")
    requested_name = payload.get("design_name")
    if requested_name is not None and requested_name != state["project_name"]:
        # The project name is the only display name the user has confirmed; anything
        # else could carry an unconfirmed claim such as a material or quality.
        raise ValidationError("The listing name must be the project's recorded name.", field="design_name",
                              recovery="Omit `design_name` to use the project name, or create the project "
                                       "under the name the user confirmed.")
    files = file_index(state)
    slots = _pick(state, version)
    number = 1 + len(state.get("presentation", {}).get("listings", []))
    folder = area_relative(project, FOLDER, f"v{number:03d}")
    out = project_area(project, FOLDER) / f"v{number:03d}"
    name = html.escape(state["project_name"], quote=True)

    def src(slot: str) -> str | None:
        entry = files.get(slots[slot]) if slots[slot] else None
        return html.escape(os.path.relpath(resolve_stored(project, entry["path"]), out), quote=True) if entry else None

    def frame(slot: str, size: str) -> str:
        image = src(slot)
        label = slot.replace("_", " ")
        return (f'<figure class="slot {size}"><img src="{image}" alt="{label}"></figure>' if image
                else f'<figure class="slot {size} empty"><figcaption>{label} — not generated yet</figcaption></figure>')

    bars = '<div class="bar w80"></div><div class="bar w40"></div><div class="bar w60"></div>'
    closeups = "".join(
        f'<figure class="crop" style="background-image:url(\'{src("white_background")}\');'
        f'background-position:{pos}"></figure>' for pos in ("20% 20%", "50% 50%", "80% 70%")
    ) if src("white_background") else ""
    page = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>Listing concept</title><style>"
        "body{margin:0;background:#EEE;font-family:Helvetica,Arial,sans-serif;color:#1A1A1A}"
        ".page{width:750px;margin:0 auto;background:#FFF}.tag{background:#1A1A1A;color:#FFF;font-size:12px;padding:6px 12px}"
        ".gallery{display:grid;grid-template-columns:repeat(4,1fr);gap:4px}.slot{margin:0;aspect-ratio:1;background:#F4F4F4}"
        ".slot.main{grid-column:1/-1}.slot img{width:100%;height:100%;object-fit:cover}"
        ".empty{display:flex;align-items:center;justify-content:center;border:2px dashed #BBB;color:#888}"
        ".bar{height:14px;background:#DDD;margin:10px 16px;border-radius:4px}.w80{width:80%}.w40{width:40%}.w60{width:60%}"
        ".crop{margin:4px 0;height:260px;background-size:300%}"
        f"</style></head><body><div class=\"page\"><div class=\"tag\">{TAG}</div>"
        f"<section class=\"gallery\">{frame('hero', 'main')}"
        f"{''.join(frame(slot, 'thumb') for slot in SLOTS[1:])}</section>"
        f"<h1 style=\"font-size:20px;margin:16px\">{name}</h1>{bars}"
        f"<section class=\"detail\">{frame('front', 'full')}{closeups}</section></div></body></html>\n"
    )
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="750" height="900"><rect width="750" height="900" fill="#FFF"/>'
           f'<rect width="750" height="28" fill="#1A1A1A"/><text x="12" y="19" fill="#FFF" font-size="12" '
           f'font-family="Helvetica">{TAG}</text>'
           + (f'<image href="{src("hero")}" x="0" y="28" width="750" height="750" '
              'preserveAspectRatio="xMidYMid slice"/>' if src("hero")
              else '<rect x="0" y="28" width="750" height="750" fill="#F4F4F4" stroke="#BBB" stroke-dasharray="8"/>')
           + f'<text x="16" y="820" font-size="20" font-family="Helvetica">{name}</text>'
           '<rect x="16" y="840" width="600" height="14" rx="4" fill="#DDD"/></svg>\n')
    write_atomic(out / "listing-concept.html", page.encode("utf-8"))
    write_atomic(out / "listing-concept.svg", svg.encode("utf-8"))
    timestamp = now or _utc_now()
    used = [slot_id for slot_id in dict.fromkeys(slots.values()) if slot_id]
    entries = [{"id": f"listing-v{number:03d}-{kind}", "origin": "listing_concept",
                "path": f"{folder}/listing-concept.{kind}", "sha256": sha256(out / f"listing-concept.{kind}"),
                "parents": used, "registered_at": timestamp, "production_eligible": False, "approved_version": version}
               for kind in ("html", "svg")]
    register_entries(project, entries, timestamp)
    listing = {"id": f"listing-v{number:03d}", "approved_version": version, "slots": slots,
               "files": [entry["id"] for entry in entries]}
    append_event(project, {"type": "listing_built", "listing": listing}, timestamp)
    return {"version": listing["id"], "slots": slots, "missing": [slot for slot in SLOTS if not slots[slot]],
            "files": {"html": entries[0]["path"], "svg": entries[1]["path"], "html_id": entries[0]["id"]}}


def decide_listing(project: Path, payload: dict, now: str | None = None) -> dict:
    files = file_index(load_state(project))
    ids = payload.get("ids") or []
    if any(files.get(item, {}).get("origin") != "listing_concept" for item in ids):
        raise ValidationError("Decide on registered listing concepts only.", field="ids",
                              recovery="Use ids returned by `create_listing` build.")
    return record_decision(project, "listing", ids, payload.get("decision"), payload.get("user_quote"), now)
