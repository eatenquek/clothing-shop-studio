"""File registration policy and whole-project validation.

Validation never trusts a single signal: it recomputes the decision-log hash chain,
replays state, re-renders generated views, re-hashes every registered file, and walks
each master's lineage, so a renamed or edited file cannot pass by name alone.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .approval import APPROVED_DIR
from .config import resolve_inside
from .errors import StudioError, ValidationError
from .interview import CRITICAL_FIELDS, is_critical
from .store import (
    _load_events,
    _utc_now,
    append_event,
    broken_links,
    load_state,
    replay_state,
)
from .views import render_decisions_md, render_manifest, render_project_yaml

ORIGIN_FOLDERS = {
    "user_reference": "references/user/",
    "online_reference": "references/online/",
    "generated_concept": "concepts/generated/",
    "approved_design": "designs/approved/",
    "production_master": "production/masters/",
}
# Concepts enter through generate_options and approvals through approve_design.
REGISTRABLE_ORIGINS = ("user_reference", "online_reference", "production_master")
ID_PREFIXES = {"user_reference": "ref-user", "online_reference": "ref-online", "production_master": "master"}
RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".psd", ".heic"}
MASTER_CONSTRUCTIONS = ("user_supplied", "typeset", "vector_construction")
MASTER_TOKEN, MOCKUP_TOKEN = "MASTER", "MOCKUP"
MEASUREMENT_KEYS = ("offset_mm", "print_width_mm", "print_height_mm")
MASTER_METADATA_KEYS = (
    "approved_version",
    "placement",
    "reference_point",
    *MEASUREMENT_KEYS,
    "colours",
    "decoration_method",
    "notes",
)
PACK_PATTERN = re.compile(r"^pack-v\d{3,}$")
URL_PATTERN = re.compile(r"^https://\S+$")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_raster(path: str) -> bool:
    return Path(path).suffix.lower() in RASTER_SUFFIXES


def _generated_ancestors(entry: dict, files: dict[str, dict]) -> list[dict]:
    """Every generated concept in the entry's content lineage (the entry itself included)."""
    found, stack, seen = [], [entry], set()
    while stack:
        current = stack.pop()
        if current["id"] in seen:
            continue
        seen.add(current["id"])
        if current.get("origin") == "generated_concept":
            found.append(current)
        stack.extend(files[parent] for parent in current.get("parents") or [] if parent in files)
    return found


def master_problems(entry: dict, files: dict[str, dict]) -> list[dict]:
    """Reasons an entry cannot serve as a production master."""
    problems = []
    name = Path(entry["path"]).name
    for ancestor in _generated_ancestors(entry, files):
        raster = _is_raster(ancestor["path"])
        problems.append(
            {
                "code": "master_generated_raster" if raster else "master_generated_concept",
                "message": f"`{entry['id']}` derives from generated concept `{ancestor['id']}`; "
                "generated previews cannot become production artwork.",
                "id": entry["id"],
            }
        )
    if MOCKUP_TOKEN in name:
        problems.append({"code": "mockup_as_master", "message": f"`{name}` is a mockup, not a master.", "id": entry["id"]})
    elif MASTER_TOKEN not in name:
        problems.append(
            {"code": "master_missing_token", "message": f"`{name}` must contain `{MASTER_TOKEN}`.", "id": entry["id"]}
        )
    if entry.get("origin") == "production_master":
        construction = entry.get("construction")
        if construction not in MASTER_CONSTRUCTIONS:
            problems.append(
                {
                    "code": "master_construction_unknown",
                    "message": f"`{entry['id']}` must state how it was made: {', '.join(MASTER_CONSTRUCTIONS)}.",
                    "id": entry["id"],
                }
            )
        elif _is_raster(entry["path"]) and construction != "user_supplied":
            problems.append(
                {
                    "code": "master_raster_not_user_supplied",
                    "message": f"`{name}` is raster artwork; only the user's own supplied artwork may be a raster master.",
                    "id": entry["id"],
                }
            )
    return problems


def register_file(project_dir: Path, payload: dict, now: str | None = None) -> dict:
    """Register a user reference, online reference note, or production master."""
    project = Path(project_dir)
    origin = payload.get("origin")
    if origin not in REGISTRABLE_ORIGINS:
        raise ValidationError(
            f"Origin must be one of: {', '.join(REGISTRABLE_ORIGINS)}.",
            field="origin",
            recovery="Register concepts with generate_options and approvals with approve_design.",
        )
    absolute, relative = resolve_inside(project, payload.get("path"), ORIGIN_FOLDERS[origin])
    state = load_state(project)
    files = {item["id"]: item for item in state.get("files", [])}
    parents = payload.get("parents") or []
    unknown = [parent for parent in parents if parent not in files]
    if unknown:
        raise ValidationError(
            f"Unknown parent file: {', '.join(unknown)}.",
            field="parents",
            recovery="Use ids of files already registered in this project.",
        )
    count = sum(1 for item in state.get("files", []) if item.get("origin") == origin)
    entry = {
        "id": f"{ID_PREFIXES[origin]}-{count + 1:03d}",
        "origin": origin,
        "path": relative,
        "sha256": _sha256(absolute),
        "parents": list(parents),
        "registered_at": now or _utc_now(),
        "production_eligible": origin == "production_master",
    }
    if origin == "user_reference":
        # Anything read out of a reference is data about the reference, never an instruction.
        entry["untrusted_text"] = True
        entry["external_transmission_consent"] = False
        for key in ("extracted_text", "notes", "contains_person"):
            if payload.get(key) is not None:
                entry[key] = payload[key]
    elif origin == "online_reference":
        source_page = payload.get("source_page")
        if not isinstance(source_page, str) or not URL_PATTERN.match(source_page):
            raise ValidationError(
                "Online references need their https source page.",
                field="source_page",
                recovery="Record the page the reference came from.",
            )
        entry.update(
            {
                "source_page": source_page,
                "rights": "third-party-inspiration-only",
                "untrusted_text": True,
                "library_id": payload.get("library_id"),
            }
        )
    else:
        entry["construction"] = payload.get("construction")
        approved = {item["version"] for item in state.get("approvals", [])}
        if payload.get("approved_version") is not None and payload["approved_version"] not in approved:
            raise ValidationError(
                "The master must implement a recorded approved version.",
                field="approved_version",
                recovery="Approve the design first, then register its master.",
            )
        for key in MEASUREMENT_KEYS:
            value = payload.get(key)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0):
                raise ValidationError(
                    f"`{key}` must be a non-negative number of millimetres.",
                    field=key,
                    recovery="Send the measurement as a number, for example 300.",
                )
            if key != "offset_mm" and value == 0:
                # A zero offset is a real placement; a zero print size is not printable.
                raise ValidationError(
                    f"`{key}` must be greater than zero.",
                    field=key,
                    recovery="Send the artwork's printed size in millimetres, for example 300.",
                )
        for key in MASTER_METADATA_KEYS:
            if payload.get(key) is not None:
                entry[key] = payload[key]
        problems = master_problems(entry, files)
        if problems:
            raise ValidationError(
                " ".join(problem["message"] for problem in problems),
                field="path",
                path=relative,
                recovery="Build the master from user-supplied artwork, licensed typesetting, or vector construction.",
            )
    append_event(project, {"type": "files_registered", "entries": [entry]}, entry["registered_at"])
    return entry


def validate_project(project_dir: Path, master_ids: list[str] | None = None, for_export: bool = False) -> dict:
    """Return {"ok", "errors", "warnings"}; each finding has a stable `code`."""
    project = Path(project_dir)
    errors: list[dict] = []
    warnings: list[dict] = []

    def error(code: str, message: str, **context) -> None:
        errors.append({"code": code, "message": message, **context})

    try:
        state = load_state(project)
        events = _load_events(project)
    except StudioError as exc:
        error("state_unreadable", exc.message)
        return {"ok": False, "errors": errors, "warnings": warnings}

    # 1. Canonical state must be exactly what the hash-chained log produces.
    broken = broken_links(events)
    if broken:
        error("event_chain_broken", f"The decision log was edited at event(s) {broken}.", path="metadata/decisions.jsonl")
    else:
        try:
            if replay_state(events) != state:
                error("state_tampered", "metadata/state.json differs from the decision log.", path="metadata/state.json")
        except StudioError as exc:
            error("event_chain_broken", exc.message, path="metadata/decisions.jsonl")

    # 2. Readable views must be regenerated, never hand-edited.
    views = {
        "project.yaml": render_project_yaml(state),
        "decisions.md": render_decisions_md(events),
        "metadata/manifest.json": render_manifest(state),
    }
    for relative, expected in views.items():
        path = project / relative
        if not path.is_file() or path.read_text("utf-8") != expected:
            error("generated_view_tampered", f"{relative} was edited by hand.", path=relative)

    # 3. Every registered file exists, matches its hash, and lives in its origin's folder.
    files = {item["id"]: item for item in state.get("files", [])}
    for entry in state.get("files", []):
        path = project / entry["path"]
        folder = ORIGIN_FOLDERS.get(entry.get("origin"))
        if folder is None or not entry["path"].startswith(folder):
            error("origin_folder_mismatch", f"`{entry['id']}` ({entry.get('origin')}) is outside {folder}.", id=entry["id"])
        if not path.is_file():
            error("file_missing", f"`{entry['path']}` is missing.", id=entry["id"], path=entry["path"])
        elif _sha256(path) != entry["sha256"]:
            code = "approved_hash_mismatch" if entry.get("origin") == "approved_design" else "file_hash_mismatch"
            error(code, f"`{entry['path']}` changed after registration.", id=entry["id"], path=entry["path"])

    # 4. Approved versions are immutable and fully accounted for.
    recorded = {item["version"]: item for item in state.get("approvals", [])}
    approved_root = project / APPROVED_DIR
    on_disk = sorted(path.name for path in approved_root.iterdir()) if approved_root.is_dir() else []
    for name in on_disk:
        if name not in recorded:
            error("unrecorded_approval", f"designs/approved/{name} was not created by approve_design.", path=f"designs/approved/{name}")
    for version, approval in recorded.items():
        folder = approved_root / version
        manifest = folder / "approval.json"
        if not manifest.is_file() or _sha256(manifest) != approval.get("approval_sha256"):
            error("approved_hash_mismatch", f"{version}/approval.json changed or is missing.", path=f"designs/approved/{version}/approval.json")
        expected = {"approval.json"} | {Path(files[item]["path"]).name for item in approval.get("files", []) if item in files}
        extra = sorted(path.name for path in folder.iterdir() if path.name not in expected) if folder.is_dir() else []
        if extra:
            error("approved_hash_mismatch", f"{version} contains unrecorded files: {', '.join(extra)}.", path=f"designs/approved/{version}")

    # 5. Masters: explicit candidates plus every registered master.
    candidates = list(master_ids or []) + [
        item["id"] for item in state.get("files", []) if item.get("origin") == "production_master"
    ]
    for master_id in dict.fromkeys(candidates):
        entry = files.get(master_id)
        if entry is None:
            error("master_missing", f"`{master_id}` is not a registered file.", id=master_id)
            continue
        errors.extend(master_problems(entry, files))

    # 6. Exported packs are immutable: recorded, hashed, and free of extra files.
    recorded_packs = {pack["version"]: pack for pack in state.get("production", {}).get("packs", [])}
    production_root = project / "production"
    if production_root.is_dir():
        for path in sorted(production_root.iterdir()):
            if PACK_PATTERN.match(path.name) and path.name not in recorded_packs:
                error("unrecorded_pack", f"production/{path.name} was not created by export_production_pack.", path=f"production/{path.name}")
    for version, pack in recorded_packs.items():
        folder = project / pack["path"]
        expected = {item["path"]: item["sha256"] for item in pack.get("files", [])}
        manifest = folder / "manifest.json"
        if not manifest.is_file() or _sha256(manifest) != pack.get("manifest_sha256"):
            error("pack_hash_mismatch", f"{version}/manifest.json changed or is missing.", path=f"{pack['path']}/manifest.json")
        for relative, digest in expected.items():
            path = folder / relative
            if not path.is_file() or _sha256(path) != digest:
                error("pack_hash_mismatch", f"{version}/{relative} changed or is missing.", path=f"{pack['path']}/{relative}")
        present = {path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()} if folder.is_dir() else set()
        extra = sorted(present - set(expected) - {"manifest.json"})
        if extra:
            error("pack_hash_mismatch", f"{version} contains unrecorded files: {', '.join(extra)}.", path=pack["path"])

    # 7. Assumptions: an export treats every critical field as critical; otherwise
    # criticality is recomputed because production scope may have changed.
    for item in state.get("assumptions", []):
        if item.get("confirmed"):
            continue
        if for_export and (item["field"] in CRITICAL_FIELDS or is_critical(item["field"], state)):
            error(
                "unconfirmed_critical_assumption",
                f"`{item['field']}` = {item['value']!r} is unconfirmed and blocks production.",
                field=item["field"],
            )
        else:
            warnings.append(
                {
                    "code": "unconfirmed_assumption",
                    "message": f"`{item['field']}` = {item['value']!r} ({item.get('source')}) is not yet confirmed.",
                    "field": item["field"],
                }
            )
    return {"ok": not errors, "errors": errors, "warnings": warnings}
