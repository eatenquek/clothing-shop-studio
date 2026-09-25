"""Same-filesystem, journaled installation transactions for a skill family."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path


IGNORED_NAMES = {"__pycache__", ".DS_Store", "INSTALLED_FROM.json"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(root).rglob("*")):
        relative = path.relative_to(root)
        if any(part in IGNORED_NAMES for part in relative.parts):
            continue
        if path.is_file() and path.suffix not in IGNORED_SUFFIXES:
            digest.update(relative.as_posix().encode("utf-8") + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def transaction_root(skills_dir: Path) -> Path:
    return Path(skills_dir).expanduser().resolve(strict=False).parent / ".clothing-shop-studio-install"


@contextmanager
def install_lock(skills_dir: Path):
    root = transaction_root(skills_dir)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / "install.lock"
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield root
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_journal(path: Path, value: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    descriptor = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _copy_bundle(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store", "INSTALLED_FROM.json"),
    )


def stage_members(members: list[dict], skills_dir: Path, marker_factory) -> list[dict]:
    skills_dir = Path(skills_dir).expanduser().resolve(strict=False)
    skills_dir.parent.mkdir(parents=True, exist_ok=True)
    root = transaction_root(skills_dir)
    root.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    staging = root / "staging" / run_id
    backups = root / "backups" / run_id
    staging.mkdir(parents=True)
    backups.mkdir(parents=True)
    if staging.stat().st_dev != skills_dir.parent.stat().st_dev:
        raise RuntimeError("staging directory is not on the skills filesystem")
    result = []
    for member in members:
        source = Path(member["source"]).resolve()
        source_hash = tree_hash(source)
        stage = staging / member["name"]
        _copy_bundle(source, stage)
        staged_hash = tree_hash(stage)
        if staged_hash != source_hash:
            raise RuntimeError(f"staged member differs from source: {member['name']}")
        marker = marker_factory(member, source_hash)
        (stage / "INSTALLED_FROM.json").write_text(
            json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        target = skills_dir / member["name"]
        result.append({
            "name": member["name"],
            "existed_before": target.exists(),
            "target": target,
            "backup": backups / member["name"],
            "stage": stage,
            "source_hash": source_hash,
            "staged_hash": staged_hash,
            "state": "pending",
            "remove": False,
        })
    return result


def _serializable(entry: dict) -> dict:
    return {key: str(value) if isinstance(value, Path) else value for key, value in entry.items()}


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _cleanup_journal(path: Path, journal: dict) -> None:
    for entry in journal.get("members", []):
        for key in ("stage", "backup"):
            value = entry.get(key)
            if value:
                try:
                    _remove_path(Path(value))
                except OSError:
                    pass
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    for name in ("staging", "backups"):
        parent = path.parent / name
        if parent.is_dir():
            for child in list(parent.iterdir()):
                if child.is_dir() and not any(child.iterdir()):
                    child.rmdir()


def recover_uncommitted(skills_dir: Path) -> None:
    path = transaction_root(skills_dir) / "journal.json"
    if not path.is_file():
        return
    try:
        journal = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("install journal is unreadable") from exc
    if journal.get("committed"):
        _cleanup_journal(path, journal)
        return

    inconsistent = []
    for raw in reversed(journal.get("members", [])):
        name = raw.get("name", "unknown")
        target = Path(raw["target"])
        backup = Path(raw["backup"])
        try:
            if raw.get("existed_before"):
                if backup.exists():
                    if target.exists() or target.is_symlink():
                        _remove_path(target)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(backup, target)
                elif not target.exists():
                    raise RuntimeError("target and backup are both missing")
                elif tree_hash(target) == raw.get("staged_hash"):
                    raise RuntimeError("new target exists but prior backup is missing")
            elif target.exists() or target.is_symlink():
                _remove_path(target)
        except (OSError, RuntimeError):
            inconsistent.append(name)
    if inconsistent:
        raise RuntimeError("rollback incomplete for: " + ", ".join(sorted(set(inconsistent))))
    _cleanup_journal(path, journal)


def _call(hook, label: str, entry: dict) -> None:
    if hook is not None:
        hook(label, entry)


def commit_staged(
    skills_dir: Path,
    staged: list[dict],
    obsolete: list[dict],
    *,
    hook=None,
) -> dict:
    skills_dir = Path(skills_dir).expanduser().resolve(strict=False)
    skills_dir.mkdir(parents=True, exist_ok=True)
    members = [dict(entry) for entry in staged]
    for entry in obsolete:
        item = dict(entry)
        item.setdefault("remove", True)
        item.setdefault("state", "pending")
        item.setdefault("stage", "")
        item.setdefault("source_hash", "")
        item.setdefault("staged_hash", "")
        members.append(item)
    path = transaction_root(skills_dir) / "journal.json"
    journal = {
        "family": "clothing-shop-studio",
        "committed": False,
        "members": [_serializable(entry) for entry in members],
    }
    write_journal(path, journal)
    try:
        for index, entry in enumerate(members):
            record = journal["members"][index]
            target, backup = Path(entry["target"]), Path(entry["backup"])
            _call(hook, "before_backup_intent", entry)
            record["state"] = "backup_intent"
            write_journal(path, journal)
            _call(hook, "after_backup_intent", entry)
            if target.exists() or target.is_symlink():
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, backup)
            _call(hook, "after_backup_move", entry)
            record["state"] = "backed_up"
            write_journal(path, journal)
            _call(hook, "after_backed_up", entry)

            if entry.get("remove"):
                record["state"] = "verified"
                write_journal(path, journal)
                _call(hook, "after_verified", entry)
                continue
            _call(hook, "before_swap_intent", entry)
            record["state"] = "swap_intent"
            write_journal(path, journal)
            _call(hook, "after_swap_intent", entry)
            os.replace(Path(entry["stage"]), target)
            _call(hook, "after_swap", entry)
            record["state"] = "swapped"
            write_journal(path, journal)
            _call(hook, "after_swapped", entry)
            _call(hook, "before_verify", entry)
            if tree_hash(target) != entry["staged_hash"]:
                raise RuntimeError(f"installed member differs from stage: {entry['name']}")
            record["state"] = "verified"
            write_journal(path, journal)
            _call(hook, "after_verified", entry)
        journal["committed"] = True
        write_journal(path, journal)
    except BaseException:
        try:
            recover_uncommitted(skills_dir)
        except RuntimeError as recovery_error:
            raise recovery_error
        raise
    _cleanup_journal(path, journal)
    return {"committed": True, "members": [entry["name"] for entry in members]}
