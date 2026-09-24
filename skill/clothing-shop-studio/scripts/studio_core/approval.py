"""Immutable, versioned design approvals."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from pathlib import Path

from .errors import StorageError, ValidationError
from .interview import is_delegation
from .store import _utc_now, append_event, load_state, write_atomic

APPROVED_DIR = Path("designs/approved")
VERSION_PATTERN = re.compile(r"^v(\d{3,})$")
READ_ONLY = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def next_version(project_dir: Path, state: dict) -> str:
    """Next vNNN after every version on disk or on record, so a number is never reused."""
    numbers = [int(item["version"][1:]) for item in state.get("approvals", [])]
    approved = Path(project_dir) / APPROVED_DIR
    if approved.is_dir():
        numbers += [int(match.group(1)) for path in approved.iterdir() if (match := VERSION_PATTERN.match(path.name))]
    return f"v{max(numbers, default=0) + 1:03d}"


def approve_design(project_dir: Path, concept_ids: list[str], statement: str, now: str | None = None) -> Path:
    """Freeze the chosen concepts into a new designs/approved/vNNN/ and record the approval."""
    project = Path(project_dir)
    if not isinstance(statement, str) or not statement.strip():
        raise ValidationError(
            "Record the user's approval statement.",
            field="statement",
            recovery="Quote what the user said when approving, for example `Approve A`.",
        )
    if is_delegation(statement):
        raise ValidationError(
            "A hand-off such as 'continue' or 'you decide' is not an approval.",
            field="statement",
            recovery="Show the design and ask the user whether they approve it.",
        )
    if not isinstance(concept_ids, list) or not concept_ids or len(set(concept_ids)) != len(concept_ids):
        raise ValidationError(
            "Approve one or more distinct concept ids.",
            field="concept_ids",
            recovery="Use ids returned by generate_options.",
        )
    state = load_state(project)
    files = {item["id"]: item for item in state.get("files", [])}
    concepts = []
    for concept_id in concept_ids:
        entry = files.get(concept_id)
        if entry is None or entry.get("origin") != "generated_concept":
            raise ValidationError(
                f"`{concept_id}` is not a registered concept.",
                field="concept_ids",
                recovery="Register the preview through generate_options before approving it.",
            )
        source = project / entry["path"]
        if not source.is_file() or _sha256(source) != entry["sha256"]:
            raise ValidationError(
                f"`{concept_id}` changed or disappeared after it was shown to the user.",
                field="concept_ids",
                path=entry["path"],
                recovery="Register the current preview as a new round and show it before approving.",
            )
        concepts.append(entry)

    timestamp = now or _utc_now()
    version = next_version(project, state)
    target = project / APPROVED_DIR / version
    try:
        target.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise StorageError(
            f"Approved version {version} already exists.",
            path=str(target),
            recovery="Resume the project and approve again; a new version number will be used.",
        ) from exc

    try:
        entries = []
        for concept in concepts:
            copy = target / f"{concept['id']}{Path(concept['path']).suffix}"
            shutil.copyfile(project / concept["path"], copy)
            entries.append(
                {
                    "id": f"{version}-{concept['id']}",
                    "origin": "approved_design",
                    "version": version,
                    "path": copy.relative_to(project).as_posix(),
                    "sha256": _sha256(copy),
                    "parents": [concept["id"]],
                    "registered_at": timestamp,
                    "production_eligible": False,
                }
            )
        approval = {
            "version": version,
            "concept_ids": list(concept_ids),
            "statement": statement.strip(),
            "approved_at": timestamp,
            "source_hashes": {concept["id"]: concept["sha256"] for concept in concepts},
            "lineage": {concept["id"]: list(concept.get("parents") or []) for concept in concepts},
            "files": [entry["id"] for entry in entries],
        }
        approval_bytes = (json.dumps(approval, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        write_atomic(target / "approval.json", approval_bytes)
        record = {**approval, "approval_sha256": hashlib.sha256(approval_bytes).hexdigest()}
        append_event(project, {"type": "design_approved", "approval": record, "entries": entries}, timestamp)
    except BaseException:
        # Nothing was recorded, so remove the half-built version rather than leave an orphan.
        shutil.rmtree(target, ignore_errors=True)
        raise

    for path in target.iterdir():
        os.chmod(path, READ_ONLY)
    return target
