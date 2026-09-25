"""Extract garments from a reference image into white-background catalogue cut-outs.

Workflow borrowed from the open Extract Clothing skill: inventory first, one job per
garment, prefer omission over invention, and an explicit text/logo policy.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from .errors import ValidationError
from .interview import CONFIRMATION_CUES, decision_problem
from .pngcolour import garment_colours
from .paths import StudioPaths, area_relative, project_area, resolve_stored, stored_relative
from .presentation import (
    PRESENTATION_FOLDERS,
    check_image,
    file_index,
    image_size,
    listing_eligible,
    next_round,
    presentation_error,
    record_decision,
    register_entries,
    sha256,
)
from .store import _utc_now, append_event, load_state, write_atomic

CATEGORIES = ("tops", "jackets", "bottoms", "accessories", "shoes")
GRAPHIC_POLICIES = ("exact", "mark-only", "omit")
MIN_EXTRACT_SIZE = 1200
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
SOURCE_ORIGINS = {"user_reference", "approved_design"}
FOLDER = PRESENTATION_FOLDERS["extracted_garment"]
POLICY_TEXT = {
    "exact": "Reproduce the visible wording exactly as in the source crop; do not restyle it.",
    "mark-only": "Show the emblem's shape and placement only; do not invent readable text.",
    "omit": "Omit any printed text, logo, or emblem that the source does not clearly show.",
}


def _text_list(value, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValidationError(f"`{field}` must be a list of short text items.", field=field,
                              recovery=f"Send `{field}` as a JSON list of strings.")
    return [item.strip() for item in value]


def _item(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValidationError("Each inventory item must be an object.", field="items",
                              recovery="Send one object per visible garment.")
    slug, name = raw.get("slug"), raw.get("name")
    if not isinstance(slug, str) or not SLUG.match(slug):
        raise ValidationError("Item slug must be lowercase letters, digits, and hyphens.", field="slug",
                              recovery="Use a slug such as `navy-crew-tee`.")
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("Each item needs a name.", field="name", recovery="Name the garment as seen.")
    if raw.get("category") not in CATEGORIES:
        raise ValidationError(f"Category must be one of: {', '.join(CATEGORIES)}.", field="category",
                              recovery="Pick the closest catalogue category.")
    if raw.get("graphic_policy") not in GRAPHIC_POLICIES:
        raise ValidationError(f"Graphic policy must be one of: {', '.join(GRAPHIC_POLICIES)}.",
                              field="graphic_policy", recovery="Use `omit` when text or logos are unclear.")
    bbox = raw.get("bbox")
    if (not isinstance(bbox, list) or len(bbox) != 4
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1 for v in bbox)
            or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]):
        raise ValidationError("`bbox` must be [left, top, right, bottom] fractions with left<right, top<bottom.",
                              field="bbox", recovery="Send the garment's box as fractions of the image.")
    return {"slug": slug, "name": name.strip(), "category": raw["category"],
            "details": _text_list(raw.get("details"), "details"),
            "observed": _text_list(raw.get("observed"), "observed"),
            "bbox": [float(v) for v in bbox], "graphic_policy": raw["graphic_policy"],
            "unknowns": _text_list(raw.get("unknowns"), "unknowns"), "untrusted_text": True}


def _inventory(state: dict, inventory_id) -> dict:
    for inventory in state.get("presentation", {}).get("inventories", []):
        if inventory["id"] == inventory_id:
            return inventory
    raise ValidationError("Unknown inventory.", field="inventory_id", recovery="Run `extract` mode `inventory` first.")


def record_inventory(project: Path, payload: dict, now: str | None = None) -> dict:
    state = load_state(project)
    files = file_index(state)
    source = files.get(payload.get("source_id"))
    if source is None or source.get("origin") not in SOURCE_ORIGINS:
        raise ValidationError("Extract from a registered user reference or approved design.", field="source_id",
                              recovery="Register the photo with `register_file` (origin user_reference) first.")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValidationError("List at least one visible garment.", field="items",
                              recovery="Send one item per garment you can see.")
    cleaned = [_item(item) for item in items]
    if len({item["slug"] for item in cleaned}) != len(cleaned):
        raise ValidationError("Item slugs must be unique.", field="slug", recovery="Give each garment its own slug.")
    count = len(state.get("presentation", {}).get("inventories", []))
    inventory = {"id": f"inv-{count + 1:03d}", "source_id": source["id"], "items": cleaned,
                 "target": payload.get("target"), "confirmed": False}
    append_event(project, {"type": "inventory_recorded", "inventory": inventory}, now)
    return inventory


def confirm_inventory(project: Path, payload: dict, now: str | None = None) -> dict:
    state = load_state(project)
    inventory = _inventory(state, payload.get("inventory_id"))
    problem = decision_problem(payload.get("user_quote"), CONFIRMATION_CUES)
    if problem:
        raise presentation_error("inventory_unconfirmed", f"The garment list was not confirmed ({problem}).",
                                 "Apply the user's corrections with a new inventory, show it, and ask again.",
                                 field="user_quote")
    append_event(project, {"type": "inventory_confirmed", "inventory_id": inventory["id"],
                           "user_quote": payload["user_quote"].strip()}, now)
    return _inventory(load_state(project), inventory["id"])


def record_consent(project: Path, payload: dict, now: str | None = None) -> dict:
    state = load_state(project)
    entry = file_index(state).get(payload.get("file_id"))
    if entry is None or entry.get("origin") != "user_reference":
        raise ValidationError("Consent applies to a registered user reference.", field="file_id",
                              recovery="Send the id of the user's reference image.")
    problem = decision_problem(payload.get("user_quote"), CONFIRMATION_CUES)
    if problem:
        raise presentation_error("transmission_consent_missing", f"Consent was not given ({problem}).",
                                 "Ask whether the image may be sent to the image tool and record a clear yes.",
                                 field="user_quote")
    append_event(project, {"type": "transmission_consent", "file_id": entry["id"],
                           "user_quote": payload["user_quote"].strip()}, now)
    return file_index(load_state(project))[entry["id"]]


def _prompt(item: dict) -> str:
    observed = "; ".join(item["observed"]) or "no additional observations"
    return (
        f"Reconstruct ONLY the complete empty {item['name']} ({item['category']}) from the source crop. "
        "Exclude the wearer, body, skin, hair, mannequin, hanger, other layers, props, and scene. "
        "Lay it flat and centred on a pure white #FFFFFF square background with even padding, no shadow, "
        "no cropping. Preserve the exact colours, fabric texture, stitching, and pattern. "
        f"Observed details: {observed}. {POLICY_TEXT[item['graphic_policy']]} "
        "Prefer omission over invention: do not add pockets, fasteners, trims, hardware, or branding "
        "that the source does not show."
    )


def plan_extraction(project: Path, payload: dict) -> dict:
    state = load_state(project)
    inventory = _inventory(state, payload.get("inventory_id"))
    if not inventory.get("confirmed"):
        raise presentation_error("inventory_unconfirmed", "The user has not confirmed the garment list.",
                                 "Show the inventory and record the user's confirmation first.",
                                 field="inventory_id")
    source = file_index(state)[inventory["source_id"]]
    if source["origin"] == "user_reference" and not source.get("external_transmission_consent"):
        raise presentation_error("transmission_consent_missing",
                                 "The user has not agreed to send this image to the image tool.",
                                 "Ask once and record the reply with `extract` mode `consent`.",
                                 field="source_id")
    round_number = next_round(state, "extracted_garment", "inventory_id", inventory["id"])
    base = area_relative(project, FOLDER, source["id"], f"r{round_number:02d}")
    return {
        "inventory_id": inventory["id"],
        "round": round_number,
        "jobs": [
            {"slug": item["slug"], "prompt": _prompt(item), "inputs": [source["path"]], "crop": item["bbox"],
             "crop_padding": 0.12, "destination": f"{base}/{item['slug']}.png", "background": "#FFFFFF",
             "min_size": MIN_EXTRACT_SIZE, "aspect": "1:1"}
            for item in inventory["items"]
        ],
    }


def register_extraction(project: Path, payload: dict, now: str | None = None) -> dict:
    state = load_state(project)
    inventory = _inventory(state, payload.get("inventory_id"))
    round_number = payload.get("round")
    if not isinstance(round_number, int) or round_number < 1:
        raise ValidationError("Send the planned round number.", field="round",
                              recovery="Use `round` from the extraction plan.")
    items = {item["slug"]: item for item in inventory["items"]}
    files = file_index(state)
    source = files[inventory["source_id"]]
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise ValidationError("Send one result per rendered garment.", field="results",
                              recovery="Include slug, path, renderer, and prompt for each file.")
    timestamp = now or _utc_now()
    entries, seen_hashes = [], set()
    for result in results:
        item = items.get(result.get("slug"))
        if item is None:
            raise ValidationError("Result slug is not in the confirmed inventory.", field="slug",
                                  recovery="Use slugs from the confirmed inventory.")
        stem = area_relative(project, FOLDER, source["id"], f"r{round_number:02d}", item["slug"])
        path = result.get("path")
        if path not in (f"{stem}.png", f"{stem}.jpg", f"{stem}.jpeg"):
            raise ValidationError("Register the file at its planned destination.", field="path", path=path,
                                  recovery=f"Save the image as {stem}.png.")
        absolute, relative = check_image(project, path, FOLDER)
        size = image_size(absolute)
        if size is None or size[0] != size[1] or size[0] < MIN_EXTRACT_SIZE:
            raise ValidationError(
                "The rendered image must be a square at least "
                f"{MIN_EXTRACT_SIZE}px on a side.", field="path", path=relative,
                recovery=f"Re-render as a square image at least {MIN_EXTRACT_SIZE}px on #FFFFFF and register again.",
            )
        digest = sha256(absolute)
        if digest in seen_hashes:
            raise ValidationError("Two results are byte-identical.", field="path", path=relative,
                                  recovery="Render each garment separately.")
        seen_hashes.add(digest)
        colours = garment_colours(absolute.read_bytes()) if absolute.suffix.lower() == ".png" else None
        colour_source = "measured"
        if colours is None:
            estimate = result.get("estimated_colours") or {}
            primary, secondary = estimate.get("primary"), estimate.get("secondary")
            if not isinstance(primary, str) or not HEX.match(primary) or (secondary is not None and not (
                    isinstance(secondary, str) and HEX.match(secondary))):
                raise ValidationError("Send estimated colours as #RRGGBB hex values.", field="estimated_colours",
                                      recovery="Estimate the garment's main colour, for example #1A2B3C.")
            colours, colour_source = {"primary": primary.upper(),
                                      "secondary": secondary.upper() if secondary else None}, "estimated"
        entry = {
            "id": f"xg-{inventory['id']}-r{round_number:02d}-{item['slug']}",
            "origin": "extracted_garment", "path": relative, "sha256": digest, "parents": [source["id"]],
            "registered_at": timestamp, "production_eligible": False, "inventory_id": inventory["id"],
            "round": round_number, "slug": item["slug"], "name": item["name"], "category": item["category"],
            "details": item["details"], "primary_colour": colours["primary"],
            "secondary_colour": colours["secondary"], "colour_source": colour_source,
            "renderer": str(result.get("renderer") or "unknown"), "prompt": str(result.get("prompt") or ""),
            "untrusted_text": True,
        }
        entry["listing_eligible"] = listing_eligible(entry, files)
        entries.append(entry)
    register_entries(project, entries, timestamp)
    catalogue = render_catalogue(project)
    return {"entries": entries, "catalogue": stored_relative(project, catalogue, category="exports")}


def render_catalogue(project: Path) -> Path:
    state = load_state(project)
    garments = [item for item in state.get("files", []) if item.get("origin") == "extracted_garment"]
    esc = lambda value: html.escape(str(value), quote=True)  # noqa: E731
    tabs = "".join(f'<a href="#{c}">{c.upper()}</a>' for c in ("all", *CATEGORIES))
    cards = []
    for item in garments:
        image = __import__("os").path.relpath(
            resolve_stored(project, item["path"]),
            StudioPaths.for_project(project).asset_dir("exports", Path(project).name) / "catalogues",
        )
        swatches = "".join(
            f'<span class="swatch" style="background:{colour}"></span><code>{colour}</code>'
            for colour in (item.get("primary_colour"), item.get("secondary_colour"))
            if isinstance(colour, str) and HEX.match(colour)
        )
        tags = "".join(f"<li>{esc(tag)}</li>" for tag in item.get("details", []))
        cards.append(
            f'<figure class="card {esc(item["category"])}"><img src="{esc(image)}" alt="{esc(item["name"])}">'
            f'<figcaption><strong>{esc(item["name"])}</strong><span>{esc(item["category"])}</span>'
            f'<div>{swatches}</div><ul>{tags}</ul>'
            f'<small>{"listing-eligible" if item.get("listing_eligible") else "inspiration only"}</small>'
            "</figcaption></figure>"
        )
    page = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>Catalogue</title><style>"
        "body{font-family:Helvetica,Arial,sans-serif;background:#F4F2EC;margin:32px;color:#1A1A1A}"
        "nav a{border:1px solid #CCC;padding:8px 14px;margin-right:4px;text-decoration:none;color:#1A1A1A}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:24px;margin-top:24px}"
        ".card{margin:0;background:#FFF;padding:12px}.card img{width:100%;aspect-ratio:1;object-fit:contain}"
        ".swatch{display:inline-block;width:14px;height:14px;border:1px solid #999;margin-right:4px}"
        "ul{padding:0;list-style:none}li{display:inline-block;border:1px solid #CCC;padding:2px 6px;margin:2px}"
        f"</style></head><body><p>{len(garments)} PIECES</p><nav>{tabs}</nav>"
        f"<main class=\"grid\">{''.join(cards)}</main></body></html>\n"
    )
    target = StudioPaths.for_project(project).asset_dir("exports", Path(project).name) / "catalogues/catalogue.html"
    write_atomic(target, page.encode("utf-8"))
    return target


def decide_garments(project: Path, payload: dict, now: str | None = None) -> dict:
    files = file_index(load_state(project))
    ids = payload.get("ids") or []
    if not ids or any(files.get(item, {}).get("origin") != "extracted_garment" for item in ids):
        raise ValidationError("Decide on registered cut-outs only.", field="ids",
                              recovery="Use ids returned by `extract` register.")
    return record_decision(project, "garment", ids, payload.get("decision"), payload.get("user_quote"), now)
