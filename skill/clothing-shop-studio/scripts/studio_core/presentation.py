"""Shared rules for presentation images: folders, file checks, lineage, decisions."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .config import resolve_inside
from .errors import ValidationError
from .interview import APPROVAL_CUES, decision_problem
from .store import append_event, load_state

PRESENTATION_FOLDERS = {
    "extracted_garment": "presentation/extracted/",
    "synthetic_model": "presentation/models/",
    "tryon_image": "presentation/tryon/",
    "listing_concept": "presentation/listing/",
}
IMAGE_SIGNATURES = {
    ".png": b"\x89PNG\r\n\x1a\n",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
}
DECISIONS = ("keep", "regenerate", "drop")
MODELS_DIRNAME = "_models"


def presentation_error(code: str, message: str, recovery: str, field: str | None = None,
                       path: str | None = None) -> ValidationError:
    return ValidationError(message, field=field, path=path, recovery=recovery,
                           details=[{"code": code, "message": message}])


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
STANDALONE_MARKERS = {0x01, 0xD8, 0xD9} | set(range(0xD0, 0xD8))


def image_size(path: Path) -> tuple[int, int] | None:
    """Return (width, height) from a PNG or JPEG header only, or None if unreadable."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(data) < 24:
            return None
        width, height = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        return (width, height) if width and height else None
    if data.startswith(b"\xff\xd8"):
        offset = 2
        while offset + 1 < len(data):
            if data[offset] != 0xFF:
                offset += 1
                continue
            marker = data[offset + 1]
            if marker == 0xFF:
                offset += 1
                continue
            if marker in STANDALONE_MARKERS:
                offset += 2
                continue
            if offset + 4 > len(data):
                return None
            length = int.from_bytes(data[offset + 2:offset + 4], "big")
            if marker in SOF_MARKERS:
                segment = data[offset + 4:offset + 4 + length - 2]
                if len(segment) < 5:
                    return None
                height, width = int.from_bytes(segment[1:3], "big"), int.from_bytes(segment[3:5], "big")
                return (width, height) if width and height else None
            if length < 2:
                return None
            offset += 2 + length
        return None
    return None


def check_image(project: Path, relative: str, folder: str, field: str = "path") -> tuple[Path, str]:
    """Require a non-empty PNG or JPEG inside `folder` whose bytes match its extension."""
    absolute, normalised = resolve_inside(project, relative, folder, field)
    signature = IMAGE_SIGNATURES.get(absolute.suffix.lower())
    if signature is None:
        raise ValidationError("Presentation images must be PNG or JPEG.", field=field, path=normalised,
                              recovery="Save the rendered image as .png or .jpg and register it again.")
    data = absolute.read_bytes()
    if not data or not data.startswith(signature):
        raise ValidationError("The image is empty or its content does not match its extension.",
                              field=field, path=normalised,
                              recovery="Save the actual rendered image at the planned destination.")
    return absolute, normalised


def file_index(state: dict) -> dict[str, dict]:
    return {item["id"]: item for item in state.get("files", [])}


def listing_eligible(entry: dict, files: dict[str, dict]) -> bool:
    """True when no ancestor is third-party, unconfirmed, or an online reference."""
    stack, seen = list(entry.get("parents") or []), set()
    while stack:
        parent_id = stack.pop()
        if parent_id in seen:
            continue
        seen.add(parent_id)
        parent = files.get(parent_id)
        if parent is None:
            return False
        if parent.get("origin") == "online_reference":
            return False
        if parent.get("origin") == "user_reference" and parent.get("rights") != "user-owned-or-licensed":
            return False
        stack.extend(parent.get("parents") or [])
    return True


def require_decision(quote, cues=APPROVAL_CUES) -> str:
    problem = decision_problem(quote, cues)
    if problem:
        raise presentation_error(
            "decision_not_affirmative",
            f"The reply is not an unqualified yes ({problem}).",
            "Resolve the request, show the result again, and record the user's clear reply.",
            field="user_quote",
        )
    return quote.strip()


def record_decision(project: Path, kind: str, ids: list[str], decision: str, user_quote: str,
                    now: str | None = None) -> dict:
    if decision not in DECISIONS:
        raise ValidationError(f"Decision must be one of: {', '.join(DECISIONS)}.", field="decision",
                              recovery="Send keep, regenerate, or drop.")
    if not isinstance(ids, list) or not ids or not all(isinstance(item, str) for item in ids):
        raise ValidationError("List the ids this decision covers.", field="ids",
                              recovery="Send the registered ids the user decided on.")
    quote = require_decision(user_quote) if decision == "keep" else str(user_quote or "").strip()
    if not quote:
        raise ValidationError("Record the user's words for this decision.", field="user_quote",
                              recovery="Pass the user's reply as `user_quote`.")
    state = append_event(project, {"type": "presentation_decision", "kind": kind, "ids": ids,
                                   "decision": decision, "user_quote": quote}, now)
    return state["presentation"]["decisions"][-1]


def kept_ids(state: dict, kind: str) -> set[str]:
    latest: dict[str, str] = {}
    for decision in state.get("presentation", {}).get("decisions", []):
        if decision["kind"] == kind:
            for item in decision["ids"]:
                latest[item] = decision["decision"]
    return {item for item, value in latest.items() if value == "keep"}


def register_entries(project: Path, entries: list[dict], now: str | None) -> None:
    append_event(project, {"type": "files_registered", "entries": entries}, now)


def require_round(value, recovery: str) -> int:
    """Planned round numbers are positive integers; anything else is a caller error."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValidationError("Send the planned round number as an integer of at least 1.", field="round",
                              recovery=recovery)
    return value


def library_root(project: Path) -> Path:
    return Path(project).parent / MODELS_DIRNAME


def next_round(state: dict, origin: str, group_key: str, group: str) -> int:
    rounds = {item.get("round") for item in state.get("files", [])
              if item.get("origin") == origin and item.get(group_key) == group}
    return 1 + max((value for value in rounds if isinstance(value, int)), default=0)
