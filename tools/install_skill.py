#!/usr/bin/env python3
"""Verify and install the Clothing Shop Studio skill as a generated Codex copy."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

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
    try:
        if had_target:
            backup.parent.mkdir(parents=True, exist_ok=True)
            os.replace(target, backup)
        os.replace(incoming, target)
        if tree_hash(target) != bundle_hash:
            raise RuntimeError("installed skill differs from its verified source bundle")
        if backup.exists():
            shutil.rmtree(backup)
    except BaseException:
        if target.exists():
            shutil.rmtree(target)
        if backup.exists():
            os.replace(backup, target)
        if incoming.exists():
            shutil.rmtree(incoming)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return {"target": str(target), "source_commit": source_commit, "bundle_tree_sha256": bundle_hash}


def _run(command: list[str], cwd: Path) -> None:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    if completed.returncode:
        details = (completed.stdout + completed.stderr).strip()
        raise RuntimeError(f"verification failed: {' '.join(command)}\n{details}")


def verify_source(repo: Path, source: Path, validator: Path) -> str:
    _run(["git", "diff", "--quiet"], repo)
    _run(["git", "diff", "--cached", "--quiet"], repo)
    _run([sys.executable, "-m", "unittest", "discover", "-s", str(source / "tests"), "-p", "test_*.py"], repo)
    _run([sys.executable, "-m", "unittest", "discover", "-s", "tools", "-p", "test_*.py"], repo)
    _run([sys.executable, str(validator), str(source)], repo)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


def main(argv=None) -> int:
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=repo / "skill/clothing-shop-studio")
    parser.add_argument("--target", type=Path, default=Path.home() / ".codex/skills/clothing-shop-studio")
    parser.add_argument("--work-root", type=Path,
                        default=Path.home() / "Documents/Clothing-Shop-Studio/.work")
    parser.add_argument("--validator", type=Path,
                        default=Path.home() / ".codex/skills/.system/skill-creator/scripts/quick_validate.py")
    args = parser.parse_args(argv)
    try:
        commit = verify_source(repo, args.source, args.validator)
        print(json.dumps(install_verified(args.source, args.target, args.work_root, commit), sort_keys=True))
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"install failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
