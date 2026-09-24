"""File registration policy and whole-project validation.

Validation never trusts a single signal: it recomputes the decision-log hash chain,
replays state, re-renders generated views, re-hashes every registered file, and walks
each master's lineage, so a renamed or edited file cannot pass by name alone.
"""

from __future__ import annotations

import hashlib
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .approval import APPROVED_DIR
from .config import resolve_inside
from .errors import StudioError, ValidationError
from .interview import CRITICAL_FIELDS, is_critical, pending_assumptions
from .presentation import PRESENTATION_FOLDERS
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
ORIGIN_FOLDERS.update(PRESENTATION_FOLDERS)
GENERATED_ORIGINS = {"generated_concept", *PRESENTATION_FOLDERS}
# Concepts enter through generate_options and approvals through approve_design.
REGISTRABLE_ORIGINS = ("user_reference", "online_reference", "production_master")
ID_PREFIXES = {"user_reference": "ref-user", "online_reference": "ref-online", "production_master": "master"}
RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".psd", ".heic"}
PRODUCTION_MASTER_SUFFIXES = {
    ".ai", ".dxf", ".emb", ".eps", ".pdf", ".svg",
    ".dst", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".psd",
}
MASTER_CONSTRUCTIONS = ("user_supplied", "typeset", "vector_construction")
USER_REFERENCE_RIGHTS = ("unconfirmed", "third-party-inspiration-only", "user-owned-or-licensed")
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
    "rights",
    "rights_statement",
)
PACK_PATTERN = re.compile(r"^pack-v\d{3,}$")
URL_PATTERN = re.compile(r"^https://\S+$")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_raster(path: str) -> bool:
    return Path(path).suffix.lower() in RASTER_SUFFIXES


def _is_dxf(data: bytes) -> bool:
    """Binary DXF sentinel, or ASCII group-code pairs opening with `0` / `SECTION`.

    ASCII DXF stores (group code, value) line pairs, so a drawing starts with the
    code `0` followed by `SECTION`, optionally after `999` comment pairs. Both LF
    and CRLF line endings are valid.
    """
    if data.startswith(b"AutoCAD Binary DXF\r\n\x1a\x00"):
        return True
    text = data[3:] if data.startswith(b"\xef\xbb\xbf") else data  # tolerate a UTF-8 BOM
    lines = [line.strip() for line in text[:4096].splitlines()]
    index = 0
    while index + 1 < len(lines) and lines[index] == b"999":
        index += 2
    return index + 1 < len(lines) and lines[index] == b"0" and lines[index + 1] == b"SECTION"


def _master_container_problem(path: Path) -> str | None:
    """Return a basic container/signature error; producer software remains authoritative."""
    data = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix == ".svg":
        try:
            root = ET.fromstring(data)
        except (ET.ParseError, ValueError):
            return "SVG masters must contain well-formed XML."
        if root.tag.rsplit("}", 1)[-1].lower() != "svg":
            return "SVG masters must have an `svg` root element."
        return None
    if suffix == ".dxf":
        return None if _is_dxf(data) else "`.dxf` master content is not an ASCII or binary DXF drawing."
    signatures = {
        ".pdf": (b"%PDF-",),
        ".eps": (b"%!PS-Adobe",),
        ".ai": (b"%PDF-", b"%!PS-Adobe"),
        ".png": (b"\x89PNG\r\n\x1a\n",),
        ".jpg": (b"\xff\xd8\xff",),
        ".jpeg": (b"\xff\xd8\xff",),
        ".tif": (b"II*\x00", b"MM\x00*"),
        ".tiff": (b"II*\x00", b"MM\x00*"),
        ".psd": (b"8BPS",),
        ".dst": (b"LA:",),
    }
    expected = signatures.get(suffix)
    if expected and not any(data.lstrip().startswith(signature) for signature in expected):
        return f"`{suffix}` master content does not match its expected file signature."
    return None


def _generated_ancestors(entry: dict, files: dict[str, dict]) -> list[dict]:
    """Every generated concept in the entry's content lineage (the entry itself included)."""
    found, stack, seen = [], [entry], set()
    while stack:
        current = stack.pop()
        if current["id"] in seen:
            continue
        seen.add(current["id"])
        if current.get("origin") in GENERATED_ORIGINS:
            found.append(current)
        stack.extend(files[parent] for parent in current.get("parents") or [] if parent in files)
    return found


def _ancestors_with_origin(entry: dict, files: dict[str, dict], origin: str) -> list[dict]:
    """Return transitive parent entries with the requested origin."""
    found, stack, seen = [], list(entry.get("parents") or []), set()
    while stack:
        parent_id = stack.pop()
        if parent_id in seen or parent_id not in files:
            continue
        seen.add(parent_id)
        parent = files[parent_id]
        if parent.get("origin") == origin:
            found.append(parent)
        stack.extend(parent.get("parents") or [])
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
        if Path(entry["path"]).suffix.lower() not in PRODUCTION_MASTER_SUFFIXES:
            problems.append(
                {
                    "code": "master_unsupported_format",
                    "message": f"`{name}` is not a recognised production artwork format.",
                    "id": entry["id"],
                }
            )
        for key in MEASUREMENT_KEYS:
            value = entry.get(key)
            invalid = value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
                or (key != "offset_mm" and value == 0)
            )
            if invalid:
                problems.append(
                    {
                        "code": "master_invalid_measurement",
                        "message": f"`{entry['id']}` has an invalid `{key}` measurement.",
                        "id": entry["id"],
                        "field": key,
                    }
                )
        references = _ancestors_with_origin(entry, files, "user_reference")
        online_references = _ancestors_with_origin(entry, files, "online_reference")
        for reference in online_references:
            problems.append(
                {
                    "code": "master_online_reference_not_clearable",
                    "message": (
                        f"`{name}` derives from online reference `{reference['id']}`; "
                        "online references are inspiration only."
                    ),
                    "id": entry["id"],
                }
            )
        for reference in references:
            if reference.get("rights") != "user-owned-or-licensed":
                problems.append(
                    {
                        "code": "master_reference_rights_unconfirmed",
                        "message": f"`{name}` derives from `{reference['id']}`, whose reuse rights are not cleared.",
                        "id": entry["id"],
                    }
                )
        construction = entry.get("construction")
        if construction not in MASTER_CONSTRUCTIONS:
            problems.append(
                {
                    "code": "master_construction_unknown",
                    "message": f"`{entry['id']}` must state how it was made: {', '.join(MASTER_CONSTRUCTIONS)}.",
                    "id": entry["id"],
                }
            )
        elif construction == "user_supplied" and (
            entry.get("rights") != "user-owned-or-licensed"
            or not str(entry.get("rights_statement") or "").strip()
            or not references
        ):
            problems.append(
                {
                    "code": "master_user_supplied_rights_unconfirmed",
                    "message": f"`{name}` needs a user-owned-or-licensed source reference and rights statement.",
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
        elif _is_raster(entry["path"]):
            if (
                entry.get("rights") != "user-owned-or-licensed"
                or not str(entry.get("rights_statement") or "").strip()
                or not references
            ):
                problems.append(
                    {
                        "code": "master_raster_rights_unconfirmed",
                        "message": f"`{name}` needs a user-owned-or-licensed source reference and a rights statement.",
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
    if origin == "production_master":
        if absolute.suffix.lower() not in PRODUCTION_MASTER_SUFFIXES:
            raise ValidationError(
                "Unsupported production-master format.",
                field="path",
                path=relative,
                recovery=(
                    "Use a recognised artwork or embroidery format such as SVG, PDF, AI, EPS, "
                    "DXF, DST, EMB, PNG, TIFF, JPEG, or PSD."
                ),
            )
        if absolute.stat().st_size == 0:
            raise ValidationError(
                "Production masters cannot be empty files.",
                field="path",
                path=relative,
                recovery="Export or save the actual artwork, then register that file.",
            )
        container_problem = _master_container_problem(absolute)
        if container_problem:
            raise ValidationError(
                container_problem,
                field="path",
                path=relative,
                recovery="Export the actual artwork in the selected format and verify that it opens before registration.",
            )
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
        rights = payload.get("rights", "unconfirmed")
        if rights not in USER_REFERENCE_RIGHTS:
            raise ValidationError(
                f"Reference rights must be one of: {', '.join(USER_REFERENCE_RIGHTS)}.",
                field="rights",
                recovery="Use `third-party-inspiration-only` unless the user confirms ownership or a licence.",
            )
        entry["rights"] = rights
        if payload.get("rights_statement") is not None:
            entry["rights_statement"] = payload["rights_statement"]
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
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValidationError(
                    f"`{key}` must be a finite, non-negative number of millimetres.",
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
        elif entry.get("origin") == "production_master" and path.stat().st_size == 0:
            error(
                "master_empty_file",
                f"`{entry['path']}` is an empty production master.",
                id=entry["id"],
                path=entry["path"],
            )
        elif entry.get("origin") == "production_master":
            container_problem = _master_container_problem(path)
            if container_problem:
                error(
                    "master_invalid_container",
                    container_problem,
                    id=entry["id"],
                    path=entry["path"],
                )

    # A contact sheet may be the only visual the user sees before approval, so it
    # is part of the review evidence even though it is not an approvable concept.
    for concept in state.get("concepts", []):
        relative = concept.get("contact_sheet")
        if not relative:
            continue
        path = project / relative
        if "contact_sheet_sha256" not in concept:
            warnings.append(
                {
                    "code": "legacy_contact_sheet_unhashed",
                    "message": (
                        f"`{relative}` predates hashed review evidence; create and show a new option round "
                        "before approving it."
                    ),
                    "path": relative,
                }
            )
            continue
        expected = concept.get("contact_sheet_sha256")
        if not path.is_file() or not expected or _sha256(path) != expected:
            error(
                "contact_sheet_hash_mismatch",
                f"`{relative}` changed or disappeared after the options were registered.",
                path=relative,
            )

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
    for item in pending_assumptions(state):
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
