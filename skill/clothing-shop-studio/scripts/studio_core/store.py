from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from .config import ensure_external
from .errors import StorageError, ValidationError
from .interview import record_answer
from .views import render_decisions_md, render_manifest, render_project_yaml

SCHEMA_VERSION = 1
PROJECT_DIRS = (
    "metadata",
    "references/user",
    "references/online",
    "concepts/generated",
    "designs/approved",
    "production",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slugify(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip().lower()
    value = re.sub(r"[^\w-]+", "-", value, flags=re.UNICODE)
    value = re.sub(r"[-_]+", "-", value).strip("-")
    if not value:
        raise ValidationError(
            "Project name must contain at least one letter or number.",
            field="name",
            recovery="Provide a short project name.",
        )
    return value


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, dir=path.parent) as handle:
            temporary = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError as exc:
        if temporary is not None:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass
        raise StorageError(
            "Could not safely update project storage.",
            path=str(path),
            recovery="Check disk space and permissions, then retry. Existing state was preserved.",
        ) from exc


def _state_template(name: str, slug: str, now: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "project_name": name,
        "project_slug": slug,
        "created_at": now,
        "updated_at": now,
        "phase": "intake",
        "answers": {},
        "assumptions": [],
        "references": [],
        "concepts": [],
        "approvals": [],
        "files": [],
        "production": {},
        "events_count": 1,
    }


def create_project(root: Path, name: str, skill_dir: Path, now: str) -> dict:
    if not isinstance(name, str) or not name.strip():
        raise ValidationError(
            "Project name is required.",
            field="name",
            recovery="Provide a short project name.",
        )
    resolved_root = ensure_external(Path(root), Path(skill_dir))
    slug = _slugify(name)
    project = resolved_root / slug
    if project.exists():
        raise ValidationError(
            "A project with this name already exists.",
            field="name",
            path=str(project),
            recovery="Resume the existing project or choose a different name.",
        )
    try:
        for relative in PROJECT_DIRS:
            (project / relative).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StorageError(
            "Could not create the project folders.",
            path=str(project),
            recovery="Choose a writable project root and retry.",
        ) from exc

    event = {"type": "project_created", "name": name.strip(), "timestamp": now}
    state = _state_template(name.strip(), slug, now)
    try:
        write_atomic(
            project / "metadata/decisions.jsonl",
            (json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
        )
        write_atomic(
            project / "metadata/state.json",
            (json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        write_atomic(project / "metadata/manifest.json", render_manifest(state).encode("utf-8"))
        write_atomic(project / "project.yaml", render_project_yaml(state).encode("utf-8"))
        write_atomic(project / "decisions.md", render_decisions_md([event]).encode("utf-8"))
    except StorageError:
        raise
    return state


def load_state(project_dir: Path) -> dict:
    path = Path(project_dir) / "metadata/state.json"
    try:
        state = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StorageError(
            "Project state is missing or corrupted.",
            path=str(path),
            recovery="Restore metadata/state.json from backup or create a new project.",
        ) from exc
    if state.get("schema_version") != SCHEMA_VERSION:
        raise ValidationError(
            "This project uses an unsupported schema version.",
            field="schema_version",
            recovery="Run a compatible migration before resuming the project.",
        )
    return state


def _load_events(project_dir: Path) -> list[dict]:
    path = Path(project_dir) / "metadata/decisions.jsonl"
    try:
        return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        raise StorageError(
            "The project decision log is missing or corrupted.",
            path=str(path),
            recovery="Restore metadata/decisions.jsonl from backup before continuing.",
        ) from exc


def _add_files(state: dict, entries: list[dict]) -> None:
    """Append file records, rejecting ids already present (checked under the project lock)."""
    existing = {item.get("id") for item in state.get("files", [])}
    clashes = sorted(entry["id"] for entry in entries if entry["id"] in existing)
    if clashes:
        raise ValidationError(
            f"File id already registered: {', '.join(clashes)}.",
            field="id",
            recovery="Resume the project and register the next round.",
        )
    state.setdefault("files", []).extend(entries)


def _apply_event(state: dict, event: dict) -> dict:
    next_state = json.loads(json.dumps(state, ensure_ascii=False))
    event_type = event.get("type")
    if event_type == "answer":
        # Delegate to the interview engine so the log and live calls derive identical state.
        next_state = record_answer(
            next_state,
            event.get("field"),
            event.get("value"),
            source=event["source"],
            evidence=event.get("evidence"),
            confirmed=event["confirmed"],
        )
    elif event_type == "options_registered":
        entries = event.get("entries") or []
        _add_files(next_state, entries)
        next_state.setdefault("concepts", []).append(
            {
                "decision_id": event.get("decision_id"),
                "round": event.get("round"),
                "ids": [entry["id"] for entry in entries],
                "contact_sheet": event.get("contact_sheet"),
            }
        )
    elif event_type == "concept_merged":
        _add_files(next_state, [event["entry"]])
    elif event_type == "phase_changed":
        next_state["phase"] = event.get("phase", next_state.get("phase"))
    elif event_type == "assumption":
        next_state.setdefault("assumptions", []).append(event.get("assumption", {}))
    next_state["updated_at"] = event["timestamp"]
    next_state["events_count"] = int(state.get("events_count", 0)) + 1
    return next_state


def append_event(project_dir: Path, event: dict, now: str | None = None) -> dict:
    if not isinstance(event, dict) or not event.get("type"):
        raise ValidationError(
            "Event type is required.",
            field="type",
            recovery="Provide a recognized event type.",
        )
    project = Path(project_dir)
    lock_path = project / "metadata/.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state = load_state(project)
        events = _load_events(project)
        enriched = dict(event)
        enriched["timestamp"] = enriched.get("timestamp") or now or _utc_now()
        if enriched["type"] == "answer":
            # Store defaults explicitly so the log is self-describing on replay.
            enriched.setdefault("source", "user")
            enriched.setdefault("confirmed", True)
        next_state = _apply_event(state, enriched)
        next_events = events + [enriched]
        targets = {
            project / "metadata/decisions.jsonl": "".join(
                json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
                for item in next_events
            ).encode("utf-8"),
            project / "metadata/state.json": (
                json.dumps(next_state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8"),
            project / "metadata/manifest.json": render_manifest(next_state).encode("utf-8"),
            project / "project.yaml": render_project_yaml(next_state).encode("utf-8"),
            project / "decisions.md": render_decisions_md(next_events).encode("utf-8"),
        }
        previous = {path: path.read_bytes() if path.exists() else None for path in targets}
        changed: list[Path] = []
        try:
            for path, data in targets.items():
                write_atomic(path, data)
                changed.append(path)
        except StorageError:
            for path in changed:
                original = previous[path]
                try:
                    if original is None:
                        path.unlink(missing_ok=True)
                    else:
                        path.write_bytes(original)
                except OSError:
                    pass
            raise
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return next_state


def status(project_dir: Path) -> dict:
    state = load_state(project_dir)
    return {
        "project_name": state["project_name"],
        "project_slug": state["project_slug"],
        "phase": state["phase"],
        "updated_at": state["updated_at"],
        "answered_fields": sorted(state.get("answers", {})),
        "assumption_count": len(state.get("assumptions", [])),
        "approval_count": len(state.get("approvals", [])),
    }
