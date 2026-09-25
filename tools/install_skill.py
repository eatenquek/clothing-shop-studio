#!/usr/bin/env python3
"""Verify and install the Clothing Shop Studio skill as a generated Codex copy."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

try:
    from tools import build_wrappers
    from tools import install_transaction
    from tools.family_manifest import load_manifest, ordered_members
except ModuleNotFoundError:  # Direct `python3 tools/install_skill.py` execution.
    import build_wrappers
    import install_transaction
    from family_manifest import load_manifest, ordered_members

IGNORED_NAMES = {"__pycache__", ".DS_Store", "INSTALLED_FROM.json"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}


def _files(root: Path):
    for path in sorted(Path(root).rglob("*")):
        relative = path.relative_to(root)
        if any(part in IGNORED_NAMES for part in relative.parts):
            continue
        if path.is_file() and path.suffix not in IGNORED_SUFFIXES:
            yield path, relative


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path, relative in _files(Path(root)):
        digest.update(relative.as_posix().encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def member_marker(member: dict, source_hash: str, source_commit: str, manifest: dict) -> dict:
    marker = {
        "bundle_tree_sha256": source_hash,
        "family": manifest["family"],
        "family_version": manifest["family_version"],
        "role": member["role"],
        "source_commit": source_commit,
    }
    if member["role"] == "core":
        marker["family_interface"] = manifest["family_interface"]
    else:
        marker["core_interface_min"] = member["core_interface_min"]
        marker["core_interface_max"] = member["core_interface_max"]
    return marker


def is_legacy_core_marker(name: str, marker: dict) -> bool:
    return name == "clothing-shop-studio" and set(marker) == {
        "source_commit", "bundle_tree_sha256"
    }


def _read_marker(path: Path) -> dict | None:
    try:
        value = json.loads((Path(path) / "INSTALLED_FROM.json").read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def family_drift(
    repo: Path,
    skills_dir: Path,
    manifest: dict,
    *,
    include_journal: bool = True,
) -> list[str]:
    """Return deterministic family drift descriptions without changing the filesystem."""
    repo, skills_dir = Path(repo).resolve(), Path(skills_dir).expanduser().resolve(strict=False)
    drift = []
    expected_names = {member["name"] for member in ordered_members(repo, manifest)}
    journal = skills_dir.parent / ".clothing-shop-studio-install/journal.json"
    if include_journal and journal.is_file():
        try:
            content = json.loads(journal.read_text("utf-8"))
            if not content.get("committed"):
                drift.append("family: uncommitted journal")
        except (OSError, json.JSONDecodeError):
            drift.append("family: unreadable install journal")

    for member in ordered_members(repo, manifest):
        name = member["name"]
        target = skills_dir / name
        if not target.is_dir():
            drift.append(f"{name}: missing")
            continue
        source_hash = tree_hash(member["source"])
        target_hash = tree_hash(target)
        if target_hash != source_hash:
            drift.append(f"{name}: content hash differs")
        marker = _read_marker(target)
        if marker is None:
            drift.append(f"{name}: marker missing or invalid")
            continue
        expected = member_marker(member, source_hash, marker.get("source_commit", ""), manifest)
        for field, value in expected.items():
            if field == "source_commit":
                continue
            if marker.get(field) != value:
                drift.append(f"{name}: marker {field} differs")

    if skills_dir.is_dir():
        for target in sorted(skills_dir.iterdir(), key=lambda path: path.name):
            if not target.is_dir() or target.name in expected_names:
                continue
            marker = _read_marker(target)
            if marker and marker.get("family") == manifest["family"]:
                drift.append(f"{target.name}: obsolete family member")
    return sorted(set(drift))


def copy_bundle(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source, destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store", "INSTALLED_FROM.json"),
    )


def install_verified(source: Path, target: Path, work_root: Path, source_commit: str) -> dict:
    source, target, work_root = Path(source).resolve(), Path(target).expanduser().resolve(strict=False), Path(work_root).resolve()
    bundle_hash = tree_hash(source)
    stage = work_root / "install-staging" / target.name
    copy_bundle(source, stage)
    if tree_hash(stage) != bundle_hash:
        raise RuntimeError("staged skill differs from its source bundle")
    marker = {"source_commit": source_commit, "bundle_tree_sha256": bundle_hash}
    (stage / "INSTALLED_FROM.json").write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    target.parent.mkdir(parents=True, exist_ok=True)
    incoming = target.parent / f".{target.name}.installing-{uuid.uuid4().hex[:8]}"
    backup = work_root / "install-backups" / f"{target.name}-{uuid.uuid4().hex[:8]}"
    copy_bundle(stage, incoming)
    shutil.copy2(stage / "INSTALLED_FROM.json", incoming / "INSTALLED_FROM.json")
    had_target = target.exists()
    backup_created = False
    installed_new = False
    try:
        if had_target:
            backup.parent.mkdir(parents=True, exist_ok=True)
            os.replace(target, backup)
            backup_created = True
        os.replace(incoming, target)
        installed_new = True
        if tree_hash(target) != bundle_hash:
            raise RuntimeError("installed skill differs from its verified source bundle")
    except BaseException:
        if installed_new and target.exists():
            shutil.rmtree(target)
        if backup_created and backup.exists():
            os.replace(backup, target)
        if incoming.exists():
            shutil.rmtree(incoming)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    if backup.exists():
        try:
            shutil.rmtree(backup)
        except OSError:
            pass
    return {"target": str(target), "source_commit": source_commit, "bundle_tree_sha256": bundle_hash}


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    if completed.returncode:
        details = (completed.stdout + completed.stderr).strip()
        raise RuntimeError(f"verification failed: {' '.join(command)}\n{details}")
    return completed


def require_clean_source(repo: Path, source: Path) -> None:
    repo, source = Path(repo).resolve(), Path(source).resolve()
    try:
        relative = source.relative_to(repo)
    except ValueError as exc:
        raise RuntimeError("source bundle must be inside its Git repository") from exc
    completed = subprocess.run(
        ["git", "status", "--porcelain", "--", str(relative)],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(f"could not inspect source bundle status\n{completed.stderr.strip()}")
    if completed.stdout.strip():
        raise RuntimeError("source bundle has uncommitted or untracked files")


def require_clean_paths(repo: Path, paths: list[Path]) -> None:
    repo = Path(repo).resolve()
    relative = []
    for path in paths:
        try:
            relative.append(str(Path(path).resolve().relative_to(repo)))
        except ValueError as exc:
            raise RuntimeError("family source must be inside its Git repository") from exc
    completed = subprocess.run(
        ["git", "status", "--porcelain", "--", *relative],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(f"could not inspect family source status\n{completed.stderr.strip()}")
    if completed.stdout.strip():
        raise RuntimeError("family source has uncommitted or untracked files")


def validate_skill_without_pyyaml(source: Path) -> None:
    """Mirror quick_validate's release-critical checks without a YAML dependency."""
    skill_md = Path(source) / "SKILL.md"
    if not skill_md.is_file():
        raise RuntimeError("fallback skill validation failed: SKILL.md not found")
    content = skill_md.read_text("utf-8")
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if match is None:
        raise RuntimeError("fallback skill validation failed: invalid YAML frontmatter format")
    values: dict[str, str] = {}
    top_level_keys: set[str] = set()
    for line in match.group(1).splitlines():
        if not line or line[0].isspace() or line.lstrip().startswith("#"):
            continue
        field = re.match(r"^([A-Za-z][A-Za-z0-9-]*):(?:[ \t]*(.*))$", line)
        if field is None:
            raise RuntimeError("fallback skill validation failed: invalid YAML frontmatter")
        key, value = field.groups()
        top_level_keys.add(key)
        values[key] = value.strip().strip("'\"")
    allowed = {"name", "description", "license", "allowed-tools", "metadata"}
    unexpected = top_level_keys - allowed
    if unexpected:
        raise RuntimeError(f"fallback skill validation failed: unexpected keys {sorted(unexpected)}")
    name, description = values.get("name", ""), values.get("description", "")
    if not name or not description:
        raise RuntimeError("fallback skill validation failed: name and description are required")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
        raise RuntimeError("fallback skill validation failed: name must be valid hyphen-case")
    if len(description) > 1024 or "<" in description or ">" in description or description.startswith("[TODO:"):
        raise RuntimeError("fallback skill validation failed: description is invalid")
    body = content[match.end():]
    if any(re.fullmatch(r"[ ]{0,3}\[TODO:[^\n]*\][ \t]*", line) for line in body.splitlines()):
        raise RuntimeError("fallback skill validation failed: unfinished TODO placeholder")


def verify_source(repo: Path, source: Path, validator: Path | str) -> str:
    require_clean_source(repo, source)
    _run([sys.executable, "-m", "unittest", "discover", "-s", str(source / "tests"), "-p", "test_*.py"], repo)
    _run([sys.executable, "-m", "unittest", "discover", "-s", "tools", "-p", "test_*.py"], repo)
    if str(validator) == "fallback":
        validate_skill_without_pyyaml(source)
    else:
        try:
            _run([sys.executable, str(validator), str(source)], repo)
        except RuntimeError as exc:
            if "No module named 'yaml'" not in str(exc):
                raise
            validate_skill_without_pyyaml(source)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


def verify_family_source(repo: Path, manifest: dict, validator: Path | str) -> str:
    repo = Path(repo).resolve()
    members = ordered_members(repo, manifest)
    require_clean_paths(
        repo,
        [member["source"] for member in members]
        + [repo / "tools/wrappers.json", repo / "tools/family_manifest.py", repo / "tools/build_wrappers.py"],
    )
    _run([sys.executable, "-m", "unittest", "discover", "-s", "skill/clothing-shop-studio/tests", "-p", "test_*.py"], repo)
    _run([sys.executable, "-m", "unittest", "discover", "-s", "tools", "-p", "test_*.py"], repo)
    drift = build_wrappers.build(repo, check=True)
    if drift:
        raise RuntimeError("generated wrapper drift: " + ", ".join(drift))
    for member in members:
        if str(validator) == "fallback":
            validate_skill_without_pyyaml(member["source"])
        else:
            try:
                _run([sys.executable, str(validator), str(member["source"])], repo)
            except RuntimeError as exc:
                if "No module named 'yaml'" not in str(exc):
                    raise
                validate_skill_without_pyyaml(member["source"])
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


def classify_target(name: str, target: Path, manifest: dict) -> str:
    target = Path(target)
    if not target.exists() and not target.is_symlink():
        return "absent"
    marker = _read_marker(target)
    if marker and marker.get("family") == manifest["family"]:
        return "family"
    if marker and is_legacy_core_marker(name, marker):
        return "legacy_core"
    return "unmarked"


def obsolete_family_members(skills_dir: Path, manifest: dict) -> list[Path]:
    skills_dir = Path(skills_dir)
    if not skills_dir.is_dir():
        return []
    expected = {manifest["core"], *(wrapper["name"] for wrapper in manifest["wrappers"])}
    obsolete = []
    for target in sorted(skills_dir.iterdir(), key=lambda item: item.name):
        if target.name in expected or not target.is_dir():
            continue
        marker = _read_marker(target)
        if marker and marker.get("family") == manifest["family"]:
            obsolete.append(target)
    return obsolete


def _require_owned_or_adopted(
    members: list[dict], skills_dir: Path, manifest: dict, adopt_unmarked: bool
) -> None:
    refused = []
    for member in members:
        classification = classify_target(
            member["name"], Path(skills_dir) / member["name"], manifest
        )
        if classification == "unmarked" and not adopt_unmarked:
            refused.append(member["name"])
    if refused:
        raise RuntimeError(
            "refusing unrelated existing skill: " + ", ".join(sorted(refused))
            + "; use --adopt-unmarked to replace explicitly"
        )


def install_family(
    repo: Path,
    skills_dir: Path,
    manifest: dict,
    validator: Path | str,
    *,
    adopt_unmarked: bool = False,
) -> dict:
    """Recover, verify, stage, and commit the complete generated skill family."""
    repo = Path(repo).resolve()
    skills_dir = Path(skills_dir).expanduser().resolve(strict=False)
    root = install_transaction.transaction_root(skills_dir)
    root.mkdir(parents=True, exist_ok=True)
    with install_transaction.install_lock(skills_dir):
        install_transaction.recover_uncommitted(skills_dir)
        commit = verify_family_source(repo, manifest, validator)
        members = ordered_members(repo, manifest)
        _require_owned_or_adopted(members, skills_dir, manifest, adopt_unmarked)
        obsolete_targets = obsolete_family_members(skills_dir, manifest)
        staged = install_transaction.stage_members(
            members,
            skills_dir,
            lambda member, source_hash: member_marker(
                member, source_hash, commit, manifest
            ),
        )
        backup_root = staged[0]["backup"].parent
        obsolete = [
            {
                "name": target.name,
                "existed_before": True,
                "target": target,
                "backup": backup_root / target.name,
            }
            for target in obsolete_targets
        ]

        def verify_installed_family() -> None:
            drift = family_drift(
                repo, skills_dir, manifest, include_journal=False
            )
            if drift:
                raise RuntimeError(
                    "installed family verification failed: " + "; ".join(drift)
                )

        result = install_transaction.commit_staged(
            skills_dir, staged, obsolete, verify=verify_installed_family
        )
        result.update({"skills_dir": str(skills_dir), "source_commit": commit})
        return result


def _family_wrapper_names(skills_dir: Path, manifest: dict) -> list[str]:
    skills_dir = Path(skills_dir)
    if not skills_dir.is_dir():
        return []
    names = []
    for target in sorted(skills_dir.iterdir(), key=lambda item: item.name):
        if not target.is_dir():
            continue
        marker = _read_marker(target)
        if (
            marker
            and marker.get("family") == manifest["family"]
            and marker.get("role") == "wrapper"
        ):
            names.append(target.name)
    return names


def install_core(
    repo: Path,
    source: Path,
    target: Path,
    manifest: dict,
    validator: Path | str,
    *,
    adopt_unmarked: bool = False,
) -> dict:
    """Install only the core skill while refusing to strand family wrappers."""
    repo, source = Path(repo).resolve(), Path(source).resolve()
    target = Path(target).expanduser().resolve(strict=False)
    skills_dir = target.parent
    root = install_transaction.transaction_root(skills_dir)
    root.mkdir(parents=True, exist_ok=True)
    with install_transaction.install_lock(skills_dir):
        install_transaction.recover_uncommitted(skills_dir)
        wrappers = _family_wrapper_names(skills_dir, manifest)
        if wrappers:
            raise RuntimeError(
                "core-only install refused while family wrapper markers exist: "
                + ", ".join(wrappers)
            )
        classification = classify_target(target.name, target, manifest)
        if classification == "unmarked" and not adopt_unmarked:
            raise RuntimeError(
                f"refusing unrelated existing skill: {target.name}; "
                "use --adopt-unmarked to replace explicitly"
            )
        commit = verify_source(repo, source, validator)
        core = dict(ordered_members(repo, manifest)[0])
        core["name"] = target.name
        staged = install_transaction.stage_members(
            [core],
            skills_dir,
            lambda member, source_hash: member_marker(
                {**member, "role": "core"}, source_hash, commit, manifest
            ),
        )

        def verify_installed_core() -> None:
            if tree_hash(target) != tree_hash(source):
                raise RuntimeError("installed core differs from source")
            marker = _read_marker(target)
            expected = member_marker(core, tree_hash(source), commit, manifest)
            if marker != expected:
                raise RuntimeError("installed core marker differs")

        result = install_transaction.commit_staged(
            skills_dir, staged, [], verify=verify_installed_core
        )
        result.update({"target": str(target), "source_commit": commit})
        return result


def main(argv=None) -> int:
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=repo / "skill/clothing-shop-studio")
    parser.add_argument("--target", type=Path)
    parser.add_argument("--skills-dir", type=Path, default=Path.home() / ".codex/skills")
    parser.add_argument("--core-only", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--adopt-unmarked", action="store_true")
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--validator",
                        default=str(Path.home() / ".codex/skills/.system/skill-creator/scripts/quick_validate.py"))
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(repo)
        if args.check and (args.target or args.core_only or args.adopt_unmarked):
            raise RuntimeError("--check cannot be combined with install modes")
        if args.target and args.core_only:
            raise RuntimeError("--target and --core-only are alternative core-only modes")
        if not args.target and not args.core_only and args.work_root is not None:
            raise RuntimeError("--work-root is deprecated and cannot be used for family installation")
        if args.check:
            drift = family_drift(repo, args.skills_dir, manifest)
            for item in drift:
                print(f"DRIFT {item}")
            return 1 if drift else 0
        if args.target or args.core_only:
            target = args.target or (args.skills_dir / "clothing-shop-studio")
            print(json.dumps(install_core(
                repo,
                args.source,
                target,
                manifest,
                args.validator,
                adopt_unmarked=args.adopt_unmarked,
            ), sort_keys=True))
            return 0
        print(json.dumps(install_family(
            repo,
            args.skills_dir,
            manifest,
            args.validator,
            adopt_unmarked=args.adopt_unmarked,
        ), sort_keys=True))
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"install failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
