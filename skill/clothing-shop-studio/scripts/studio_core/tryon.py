"""Put approved designs or eligible cut-outs on a pinned AI model."""

from __future__ import annotations

from pathlib import Path

from .errors import ValidationError
from .models import pin_model
from .presentation import (
    PRESENTATION_FOLDERS,
    check_image,
    file_index,
    listing_eligible,
    next_round,
    presentation_error,
    record_decision,
    register_entries,
    require_round,
    sha256,
)
from .store import _utc_now, load_state

POSES = ("front", "three_quarter", "back")
FOLDER = PRESENTATION_FOLDERS["tryon_image"]
POSE_TEXT = {"front": "front view", "three_quarter": "three-quarter view turned 45 degrees", "back": "back view"}


def _garments(state: dict, payload: dict) -> list[dict]:
    files = file_index(state)
    ids = payload.get("garment_ids") or ([payload["design_id"]] if payload.get("design_id") else [])
    if not ids:
        raise ValidationError("Choose an approved design or extracted garments.", field="garment_ids",
                              recovery="Send `design_id` or `garment_ids`.")
    garments = []
    for garment_id in ids:
        entry = files.get(garment_id)
        if entry is None or entry.get("origin") not in {"approved_design", "extracted_garment"} \
                or entry.get("role") == "review_evidence":
            raise ValidationError(f"`{garment_id}` is not an approved design or extracted garment.",
                                  field="garment_ids", recovery="Use ids from approvals or `extract`.")
        if not listing_eligible(entry, files) or entry.get("listing_eligible") is False:
            raise presentation_error("garment_not_listing_eligible",
                                     f"`{garment_id}` comes from a third-party or unconfirmed source.",
                                     "Use your own approved design or a cut-out from an image you own.",
                                     field="garment_ids")
        garments.append(entry)
    return garments


def plan_tryon(project: Path, payload: dict, now: str | None = None) -> dict:
    poses = payload.get("poses")
    if not isinstance(poses, list) or not poses or any(pose not in POSES for pose in poses) \
            or len(set(poses)) != len(poses):
        raise ValidationError(f"Poses must be distinct values from: {', '.join(POSES)}.", field="poses",
                              recovery="Choose front, three_quarter, and/or back.")
    garments = _garments(load_state(project), payload)
    model = pin_model(project, payload.get("model_id"), now)
    identity = model["identity"]
    state = load_state(project)
    round_number = next_round(state, "tryon_image", "model_id", identity["id"])
    anchors = "; ".join(f"{key}: {identity[key]}" for key in (
        "gender_presentation", "age_range", "build", "skin_tone", "hair", "face_description", "lighting", "camera",
        "background"))
    garment_text = ", ".join(entry.get("name") or Path(entry["path"]).stem for entry in garments)
    jobs = [{
        "pose": pose,
        "inputs": [model["path"], *(entry["path"] for entry in garments)],
        "prompt": (f"Show the same person as the model reference image ({anchors}) wearing {garment_text}, "
                   f"{POSE_TEXT[pose]}, full length. Keep every identity anchor unchanged. Reproduce the garment "
                   "exactly as shown: same colour, print, placement, and scale; no invented logos, pockets, "
                   "or trims. Fictional AI-generated model; not any real person."),
        "destination": f"{FOLDER}r{round_number:02d}/{identity['id']}-{pose}.png",
        "aspect": "3:4",
    } for pose in poses]
    return {"round": round_number, "model": model["id"], "identity_lock": "reference_image", "jobs": jobs}


def register_tryon(project: Path, payload: dict, now: str | None = None) -> list[dict]:
    state = load_state(project)
    garments = _garments(state, payload)
    files = file_index(state)
    model = files.get(f"pin-{payload.get('model_id')}")
    if model is None:
        raise presentation_error("model_not_kept", "Plan the try-on first so the model is pinned.",
                                 "Run `try_on` mode `plan`.", field="model_id")
    round_number = require_round(payload.get("round"), "Use `round` from the `try_on` plan.")
    timestamp = now or _utc_now()
    entries, seen_hashes = [], set()
    for result in payload.get("results") or []:
        pose = result.get("pose")
        expected = f"{FOLDER}r{round_number:02d}/{model['library_model_id']}-{pose}.png"
        if pose not in POSES or result.get("path") != expected:
            raise ValidationError("Register each try-on at its planned destination.", field="path",
                                  recovery=f"Save the {pose} image as {expected}.")
        absolute, relative = check_image(project, result["path"], FOLDER)
        digest = sha256(absolute)
        if digest in seen_hashes:
            raise ValidationError("Two try-on poses are byte-identical.", field="path", path=relative,
                                  recovery="Render each pose separately.")
        seen_hashes.add(digest)
        entries.append({"id": f"try-{model['library_model_id']}-r{round_number:02d}-{pose}", "origin": "tryon_image",
                        "path": relative, "sha256": digest,
                        "parents": [*(entry["id"] for entry in garments), model["id"]], "registered_at": timestamp,
                        "production_eligible": False, "label": "AI try-on", "pose": pose, "round": round_number,
                        "model_id": model["library_model_id"], "renderer": str(result.get("renderer") or "unknown"),
                        "prompt": str(result.get("prompt") or "")})
    if not entries:
        raise ValidationError("Send the rendered try-on images.", field="results", recovery="Include pose and path.")
    register_entries(project, entries, timestamp)
    return entries


def decide_tryon(project: Path, payload: dict, now: str | None = None) -> dict:
    files = file_index(load_state(project))
    ids = payload.get("ids") or []
    if any(files.get(item, {}).get("origin") != "tryon_image" for item in ids):
        raise ValidationError("Decide on registered try-on images only.", field="ids",
                              recovery="Use ids returned by `try_on` register.")
    return record_decision(project, "tryon", ids, payload.get("decision"), payload.get("user_quote"), now)
