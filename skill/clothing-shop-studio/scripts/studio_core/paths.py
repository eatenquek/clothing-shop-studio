"""Canonical filesystem boundary for Clothing Shop Studio."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .errors import StorageError, UnsafePathError, ValidationError

TOP_LEVEL_DIRS = (
    "source",
    "projects",
    "references",
    "generated",
    "approved",
    "production",
    "exports",
    ".work",
)
ASSET_CATEGORIES = frozenset({"references", "generated", "approved", "production", "exports"})
WORK_PURPOSES = frozenset({"reviews", "evals", "migrations", "install-staging", "install-backups"})


def _within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False


def _component(value: str, field: str) -> str:
    safe = (
        isinstance(value, str)
        and 1 <= len(value) <= 128
        and Path(value).name == value
        and value not in {".", ".."}
        and value[0] != "-"
        and value[-1] != "-"
        and all(character.isalnum() or character == "-" for character in value)
    )
    if not safe:
        raise UnsafePathError(
            f"{field.replace('_', ' ').title()} is not a safe path component.",
            field=field,
            path=str(value),
            recovery="Use lowercase letters, numbers, and single hyphens only.",
        )
    return value


@dataclass(frozen=True)
class StudioPaths:
    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root).expanduser().resolve(strict=False))

    @staticmethod
    def default_root(home: Path | None = None) -> Path:
        return (Path(home) if home is not None else Path.home()) / "Documents/Clothing-Shop-Studio"

    @classmethod
    def canonical(cls, home: Path | None = None) -> "StudioPaths":
        return cls(cls.default_root(home))

    @classmethod
    def for_project(cls, project: Path) -> "StudioPaths":
        resolved = Path(project).expanduser().resolve(strict=False)
        if resolved.parent.name != "projects":
            raise UnsafePathError(
                "Project directory must be directly inside the studio projects folder.",
                field="project_dir",
                path=str(resolved),
                recovery="Open the project from Clothing-Shop-Studio/projects or provide its location.",
            )
        return cls(resolved.parent.parent)

    @property
    def projects_dir(self) -> Path:
        return self.root / "projects"

    def _contained(self, candidate: Path, parent: Path, field: str = "path") -> Path:
        resolved_parent = parent.resolve(strict=False)
        resolved = candidate.resolve(strict=False)
        if not _within(resolved, resolved_parent):
            raise UnsafePathError(
                "Path escapes the Clothing Studio location allowed for this operation.",
                field=field,
                path=str(candidate),
                recovery="Use a path inside the requested project category.",
            )
        return resolved

    def ensure_layout(self) -> "StudioPaths":
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            root = self.root.resolve()
            for name in TOP_LEVEL_DIRS:
                target = self.root / name
                if target.exists() and not _within(target.resolve(), root):
                    raise UnsafePathError(
                        "A Clothing Studio folder resolves outside the studio root.",
                        path=str(target),
                        recovery="Replace the escaping symlink with a real folder inside the studio root.",
                    )
                target.mkdir(parents=True, exist_ok=True)
        except UnsafePathError:
            raise
        except OSError as exc:
            raise StorageError(
                "Could not create the Clothing Studio folder layout.",
                path=str(self.root),
                recovery="Check folder permissions and available disk space.",
            ) from exc
        return self

    def project(self, slug: str) -> Path:
        return self._contained(self.projects_dir / _component(slug, "project_slug"), self.projects_dir)

    def require_project(self, project: Path) -> Path:
        candidate = self._contained(Path(project), self.projects_dir, "project_dir")
        if candidate.parent != self.projects_dir.resolve(strict=False) or not candidate.is_dir():
            raise ValidationError(
                "The requested clothing project was not found.",
                field="project_dir",
                path=str(candidate),
                recovery="Provide the project location under Clothing-Shop-Studio/projects.",
            )
        return candidate

    def asset_dir(self, category: str, slug: str) -> Path:
        if category not in ASSET_CATEGORIES:
            raise ValidationError(
                "Unknown Clothing Studio asset category.",
                field="category",
                recovery=f"Use one of: {', '.join(sorted(ASSET_CATEGORIES))}.",
            )
        base = self.root / category
        candidate = self._contained(base / _component(slug, "project_slug"), base)
        if candidate.exists() and not _within(candidate.resolve(), self.root):
            raise UnsafePathError(
                "Asset folder resolves outside the Clothing Studio root.",
                path=str(candidate),
                recovery="Replace the escaping symlink with a project folder inside the studio root.",
            )
        return candidate

    def from_relative(self, relative: str, *, category: str | None = None,
                      slug: str | None = None, allow_work: bool = False) -> Path:
        path = Path(relative)
        if not isinstance(relative, str) or not relative or path.is_absolute() or ".." in path.parts:
            raise UnsafePathError(
                "Stored paths must be safe paths relative to the studio root.",
                field="path",
                path=str(relative),
                recovery="Use a POSIX path inside this project's category folder.",
            )
        candidate = self._contained(self.root / path, self.root)
        if path.parts[0] == ".work" and not allow_work:
            raise UnsafePathError(
                "Project manifests cannot point into the temporary work area.",
                field="path",
                path=relative,
                recovery="Move durable output into its project category before registering it.",
            )
        if category is not None:
            expected = self.asset_dir(category, _component(slug or "", "project_slug"))
            self._contained(candidate, expected)
        elif slug is not None:
            if len(path.parts) < 2 or path.parts[0] not in ASSET_CATEGORIES or path.parts[1] != slug:
                raise UnsafePathError(
                    "Stored path belongs to another project or category.",
                    field="path",
                    path=relative,
                    recovery="Use a path within this project's asset folders.",
                )
        return candidate

    def to_relative(self, path: Path, *, category: str | None = None,
                    slug: str | None = None, allow_work: bool = False) -> str:
        resolved = self._contained(Path(path), self.root)
        relative = resolved.relative_to(self.root).as_posix()
        self.from_relative(relative, category=category, slug=slug, allow_work=allow_work)
        return relative

    def work_dir(self, purpose: str, run_id: str | None = None) -> Path:
        if purpose not in WORK_PURPOSES:
            raise ValidationError(
                "Unknown Clothing Studio work purpose.",
                field="purpose",
                recovery=f"Use one of: {', '.join(sorted(WORK_PURPOSES))}.",
            )
        target = self.root / ".work" / purpose
        if run_id is not None:
            target /= _component(run_id, "run_id")
        return self._contained(target, self.root / ".work")


def project_paths(project: Path) -> tuple[StudioPaths, Path, str]:
    paths = StudioPaths.for_project(project)
    resolved = paths.require_project(project)
    return paths, resolved, resolved.name


AREA_PARTS = {
    "references/user": ("references", "user"),
    "references/online": ("references", "online"),
    "concepts/generated": ("generated", "concepts"),
    "designs/approved": ("approved",),
    "production": ("production",),
    "production/masters": ("production", "masters"),
    "presentation/extracted": ("generated", "extracted"),
    "presentation/models": ("generated", "models"),
    "presentation/tryon": ("generated", "tryon"),
    "presentation/listing": ("exports", "listings"),
}


def project_area(project: Path, area: str) -> Path:
    """Return the v2 destination for a stable logical area name."""
    paths, resolved, slug = project_paths(project)
    key = area.strip("/")
    parts = AREA_PARTS.get(key)
    if parts is None:
        raise ValidationError("Unknown project storage area.", field="folder", path=area)
    category, *tail = parts
    return paths.asset_dir(category, slug).joinpath(*tail)


def stored_relative(project: Path, path: Path, *, category: str | None = None) -> str:
    paths, _, slug = project_paths(project)
    return paths.to_relative(path, category=category, slug=slug)


def area_relative(project: Path, area: str, *tail: str) -> str:
    target = project_area(project, area).joinpath(*tail)
    return stored_relative(project, target)


def resolve_stored(project: Path, relative: str) -> Path:
    """Resolve a v2 studio path, or a v1 path relative to a legacy project."""
    paths = StudioPaths.for_project(project)
    state_path = Path(project) / "metadata/state.json"
    try:
        import json
        state = json.loads(state_path.read_text("utf-8"))
    except (OSError, ValueError):
        state = {}
    if state.get("layout_version") == 2:
        raw = Path(relative)
        if len(raw.parts) >= 2 and raw.parts[0] in ASSET_CATEGORIES and raw.parts[1] == Path(project).name:
            return paths.from_relative(relative, slug=Path(project).name)
        for area in sorted(AREA_PARTS, key=len, reverse=True):
            prefix = Path(area)
            try:
                tail = raw.relative_to(prefix)
            except ValueError:
                continue
            return project_area(project, area) / tail
        return paths.from_relative(relative, slug=Path(project).name)
    candidate = (Path(project) / relative).resolve(strict=False)
    if not _within(candidate, Path(project).resolve(strict=False)):
        raise UnsafePathError("Legacy project path escapes its project.", path=relative)
    return candidate
