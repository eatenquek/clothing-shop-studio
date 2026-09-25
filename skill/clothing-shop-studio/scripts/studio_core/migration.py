"""Explicit, hash-verified migration from project-relative layout v1 to layout v2."""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
from pathlib import Path

from .errors import StorageError, ValidationError
from .interview import APPROVAL_CUES, decision_problem
from .paths import StudioPaths, project_area
from .store import _load_events, append_event, canonical_json, load_state, write_atomic


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _destination(project: Path, relative: str) -> Path | None:
    path = Path(relative)
    mappings = (
        (Path("references/user"), "references/user"),
        (Path("references/online"), "references/online"),
        (Path("concepts/generated"), "concepts/generated"),
        (Path("designs/approved"), "designs/approved"),
        (Path("production/masters"), "production/masters"),
        (Path("presentation/extracted"), "presentation/extracted"),
        (Path("presentation/models"), "presentation/models"),
        (Path("presentation/tryon"), "presentation/tryon"),
        (Path("presentation/listing"), "presentation/listing"),
    )
    if len(path.parts) >= 2 and path.parts[0] == "production" and path.parts[1].startswith("pack-v"):
        return project_area(project, "production") / "packs" / Path(*path.parts[1:])
    for prefix, area in mappings:
        try:
            tail = path.relative_to(prefix)
        except ValueError:
            continue
        return project_area(project, area) / tail
    return None


def _plan_path(paths: StudioPaths, inventory_id: str) -> Path:
    return paths.work_dir("migrations", inventory_id) / "plan.json"


def inventory_migration(project_dir: Path) -> dict:
    project = Path(project_dir).resolve(strict=False)
    paths = StudioPaths.for_project(project).ensure_layout()
    paths.require_project(project)
    state = load_state(project)
    if state.get("layout_version") == 2:
        raise ValidationError(
            "This project already uses the canonical layout.", field="project_dir",
            recovery="Resume the project normally; no migration is required.",
        )
    files = []
    for source in sorted(project.rglob("*")):
        if not source.is_file() or source.is_symlink() or "metadata" in source.relative_to(project).parts[:1] \
                or source.name in {"project.yaml", "decisions.md"}:
            continue
        relative = source.relative_to(project).as_posix()
        destination = _destination(project, relative)
        if destination is None:
            raise ValidationError(
                "Legacy project contains a file with no safe canonical destination.",
                path=relative,
                recovery="Move the file into a recognised legacy asset folder and inventory again.",
            )
        files.append({
            "source": f"projects/{project.name}/{relative}",
            "source_project_relative": relative,
            "destination": destination.relative_to(paths.root).as_posix(),
            "size": source.stat().st_size,
            "sha256": _sha256(source),
        })
    body = {"project_slug": project.name, "layout_from": 1, "layout_to": 2, "files": files}
    inventory_id = "migration-" + hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()[:16]
    plan = {"inventory_id": inventory_id, **body, "status": "inventoried"}
    write_atomic(_plan_path(paths, inventory_id),
                 (json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return plan


def apply_migration(project_dir: Path, inventory_id: str, user_quote: str) -> dict:
    project = Path(project_dir).resolve(strict=False)
    paths = StudioPaths.for_project(project).ensure_layout()
    if decision_problem(user_quote, APPROVAL_CUES):
        raise ValidationError(
            "Layout migration requires a clear affirmative approval.", field="user_quote",
            recovery="Review the inventory mapping, then explicitly approve this migration.",
        )
    plan_path = _plan_path(paths, inventory_id)
    try:
        plan = json.loads(plan_path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "Migration inventory was not found or is damaged.", field="inventory_id",
            path=str(plan_path), recovery="Run migrate_layout inventory again.",
        ) from exc
    if plan.get("inventory_id") != inventory_id or plan.get("project_slug") != project.name:
        raise ValidationError("Migration inventory does not belong to this project.", field="inventory_id")
    if plan.get("status") == "applied":
        return {"migrated": True, "inventory_id": inventory_id, "files": len(plan["files"]), "resumed": True}

    mapping: dict[str, str] = {}
    copied: list[Path] = []
    try:
        for item in plan["files"]:
            source = paths.root / item["source"]
            destination = paths.root / item["destination"]
            source_valid = (
                source.is_file()
                and source.stat().st_size == item["size"]
                and _sha256(source) == item["sha256"]
            )
            destination_valid = destination.is_file() and _sha256(destination) == item["sha256"]
            resuming = plan.get("status") in {"state_migrated", "validated"}
            if not source_valid and not (resuming and destination_valid):
                raise ValidationError(
                    "A legacy source changed after inventory.", path=item["source"],
                    recovery="Run migrate_layout inventory again and review the new mapping.",
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and _sha256(destination) != item["sha256"]:
                raise StorageError(
                    "Migration destination already contains different content.", path=item["destination"],
                    recovery="Move the conflicting file aside, then apply the same inventory again.",
                )
            if not destination.exists():
                shutil.copy2(source, destination)
                copied.append(destination)
            if _sha256(destination) != item["sha256"]:
                raise StorageError("Copied migration file failed hash verification.", path=item["destination"])
            mapping[item["source_project_relative"]] = item["destination"]

        state = load_state(project)
        for pack in state.get("production", {}).get("packs", []):
            old_path = pack.get("path")
            if isinstance(old_path, str) and old_path.startswith("production/pack-v"):
                mapping[old_path] = f"production/{project.name}/packs/{Path(old_path).name}"
        if state.get("layout_version") != 2:
            append_event(project, {
                "type": "layout_migrated", "inventory_id": inventory_id,
                "user_quote": user_quote.strip(), "path_mapping": mapping,
            })
            plan["status"] = "state_migrated"
            write_atomic(plan_path, (json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        elif plan.get("status") not in {"state_migrated", "validated"}:
            recorded = next(
                (event for event in reversed(_load_events(project))
                 if event.get("type") == "layout_migrated" and event.get("inventory_id") == inventory_id),
                None,
            )
            if recorded is None:
                raise ValidationError(
                    "Project layout changed after this migration inventory was created.",
                    field="inventory_id",
                    recovery="Inspect the existing layout migration event before attempting another migration.",
                )
            plan["status"] = "state_migrated"
            write_atomic(plan_path, (json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))

        if plan.get("status") != "validated":
            from .validation import validate_project
            report = validate_project(project)
            if not report["ok"]:
                raise ValidationError(
                    "Migrated project did not pass validation; old files were preserved.",
                    field="project_dir",
                    details=report["errors"],
                    recovery="Correct the reported records, then apply this inventory again to resume safely.",
                )
            plan["status"] = "validated"
            write_atomic(plan_path, (json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        for item in plan["files"]:
            source = paths.root / item["source"]
            if source.exists():
                source.chmod(source.stat().st_mode | stat.S_IWUSR)
                source.parent.chmod(source.parent.stat().st_mode | stat.S_IWUSR | stat.S_IXUSR)
            source.unlink(missing_ok=True)
        for directory in sorted((item for item in project.rglob("*") if item.is_dir() and item.name != "metadata"),
                                key=lambda value: len(value.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
        plan["status"] = "applied"
        write_atomic(plan_path, (json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        return {"migrated": True, "inventory_id": inventory_id, "files": len(plan["files"])}
    except BaseException:
        # Sources remain in place until state has been durably rewritten. Copies
        # are safe to retain for resume only when they match the inventoried hash.
        raise
