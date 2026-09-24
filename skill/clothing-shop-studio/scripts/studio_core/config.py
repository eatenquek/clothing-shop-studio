from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from .errors import StorageError, UnsafePathError, ValidationError

ENV_HOME = "CLOTHING_SHOP_STUDIO_HOME"


def _is_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False


def ensure_external(path: Path, skill_dir: Path) -> Path:
    resolved = path.expanduser().resolve(strict=False)
    installed = skill_dir.expanduser().resolve(strict=False)
    if resolved == installed or _is_within(resolved, installed):
        raise UnsafePathError(
            "The resolved project root is inside the installed skill directory.",
            field="root",
            path=str(resolved),
            recovery="Choose a writable directory outside the installed skill.",
        )
    return resolved


def resolve_inside(project: Path, relative, folder: str, field: str = "path") -> tuple[Path, str]:
    """Resolve a project-relative file and require it to exist inside `folder`.

    Returns the absolute path and the normalised POSIX path relative to the project.
    Symlinks and `..` segments are resolved first, so they cannot escape the folder.
    """
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValidationError(
            "File paths must be relative to the project directory.",
            field=field,
            recovery=f"Save the file under {folder} and send its relative path.",
        )
    project = Path(project).resolve()
    root = (project / folder).resolve()
    candidate = (project / relative).resolve()
    if not _is_within(candidate, root):
        raise UnsafePathError(
            f"This file must stay inside {folder}.",
            field=field,
            path=relative,
            recovery=f"Move the file into {folder} and retry.",
        )
    if not candidate.is_file():
        raise ValidationError(
            "The file does not exist.",
            field=field,
            path=relative,
            recovery="Create or copy the file before registering it.",
        )
    return candidate, candidate.relative_to(project).as_posix()


def resolve_storage_root(
    requested: Path | None,
    skill_dir: Path,
    env: Mapping[str, str],
    config_path: Path,
) -> Path:
    candidate = requested
    if candidate is None and env.get(ENV_HOME):
        candidate = Path(env[ENV_HOME])
    if candidate is None and config_path.is_file():
        try:
            payload = json.loads(config_path.read_text("utf-8"))
            candidate = Path(payload["root"])
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValidationError(
                "The saved clothing project root is invalid.",
                field="root",
                path=str(config_path),
                recovery="Repair the configuration or provide a project root explicitly.",
            ) from exc
    if candidate is None:
        raise ValidationError(
            "No clothing project storage root is configured.",
            field="root",
            recovery="Choose a writable directory outside the installed skill.",
        )
    return ensure_external(Path(candidate), skill_dir)


def save_storage_root(root: Path, config_path: Path) -> None:
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps({"root": str(root)}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise StorageError(
            "Could not save the clothing project root.",
            path=str(config_path),
            recovery="Choose a writable configuration location or continue without remembering the root.",
        ) from exc
