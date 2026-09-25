"""Load and validate the generated Clothing Shop Studio command family."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path


NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
CODE_SPAN = re.compile(r"`([^`]+)`")


def load_manifest(repo: Path, path: Path | None = None) -> dict:
    source = Path(path) if path is not None else Path(repo) / "tools/wrappers.json"
    try:
        manifest = json.loads(source.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not load wrapper manifest: {source}") from exc
    validate_manifest(Path(repo), manifest)
    return manifest


def _studio_commands(repo: Path) -> set[str]:
    scripts = Path(repo) / "skill/clothing-shop-studio/scripts"
    module_path = scripts / "studio.py"
    spec = importlib.util.spec_from_file_location("clothing_studio_manifest_commands", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load studio command table")
    module = importlib.util.module_from_spec(spec)
    original = list(sys.path)
    try:
        sys.path.insert(0, str(scripts))
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = original
    return set(module.COMMANDS)


def _normal_heading(value: str) -> str:
    return re.sub(r"`([^`]+)`", r"\1", value).strip()


def _sections(path: Path) -> dict[str, str]:
    text = path.read_text("utf-8")
    matches = list(HEADING.finditer(text))
    result = {}
    for index, match in enumerate(matches):
        level = len(match.group(1))
        end = len(text)
        for following in matches[index + 1:]:
            if len(following.group(1)) <= level:
                end = following.start()
                break
        result[_normal_heading(match.group(2))] = text[match.end():end]
    return result


def _all_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _all_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _all_strings(item)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def validate_manifest(repo: Path, manifest: dict) -> None:
    repo = Path(repo)
    _require(isinstance(manifest, dict), "manifest must be an object")
    _require(manifest.get("family") == "clothing-shop-studio", "invalid family")
    _require(isinstance(manifest.get("family_version"), int), "invalid family_version")
    _require(isinstance(manifest.get("family_interface"), int), "invalid family_interface")
    _require(manifest.get("core") == "clothing-shop-studio", "invalid core")
    wrappers = manifest.get("wrappers")
    _require(isinstance(wrappers, list) and wrappers, "wrappers must be a non-empty list")
    commands = _studio_commands(repo)
    names = set()
    for wrapper in wrappers:
        name = wrapper.get("name", "")
        _require(isinstance(name, str) and len(name) <= 64 and NAME.fullmatch(name), f"{name!r}: invalid name")
        _require(name not in names, f"duplicate wrapper name: {name}")
        names.add(name)
        for field in ("description", "display_name", "short_description", "starts", "default_prompt"):
            _require(isinstance(wrapper.get(field), str) and wrapper[field].strip(), f"{name}: missing {field}")
        minimum = wrapper.get("core_interface_min")
        maximum = wrapper.get("core_interface_max")
        _require(isinstance(minimum, int), f"{name}: missing core_interface_min")
        _require(isinstance(maximum, int), f"{name}: missing core_interface_max")
        _require(minimum <= maximum, f"{name}: invalid interface range")
        operations = wrapper.get("operations")
        _require(isinstance(operations, list) and operations, f"{name}: missing operations")
        references = wrapper.get("references")
        _require(isinstance(references, list) and references, f"{name}: missing references")

        documented = []
        for reference in references:
            relative = reference.get("path", "")
            path = repo / "skill/clothing-shop-studio" / relative
            _require(path.is_file(), f"{name}: missing reference {relative}")
            sections = _sections(path)
            for heading in reference.get("sections", []):
                normalized = _normal_heading(heading)
                _require(normalized in sections, f"{name}: missing heading {heading}")
                documented.extend(CODE_SPAN.findall(sections[normalized]))

        for operation in operations:
            command = operation.get("command")
            _require(command in commands, f"{name}: unknown command {command}")
            modes = operation.get("modes")
            _require(isinstance(modes, list), f"{name}: modes must be a list")
            for mode in modes:
                exact_json = f'"mode": "{mode}"'
                _require(
                    any(token == mode or exact_json in token for token in documented),
                    f"{name}: undocumented mode {mode}",
                )

        scripts = wrapper.get("scripts")
        _require(isinstance(scripts, list), f"{name}: scripts must be a list")
        for relative in scripts:
            _require((repo / "skill/clothing-shop-studio" / relative).is_file(), f"{name}: missing script {relative}")
        _require(isinstance(wrapper.get("gates"), list), f"{name}: gates must be a list")
        _require(isinstance(wrapper.get("scope"), list), f"{name}: scope must be a list")
        _require(isinstance(wrapper.get("visual"), bool), f"{name}: visual must be boolean")
        _require(
            not any("http://" in text or "https://" in text for text in _all_strings(wrapper)),
            f"{name}: URL copied into wrapper manifest",
        )


def ordered_members(repo: Path, manifest: dict) -> list[dict]:
    validate_manifest(Path(repo), manifest)
    core = {
        "name": manifest["core"],
        "role": "core",
        "source": Path(repo) / "skill" / manifest["core"],
        "family_interface": manifest["family_interface"],
    }
    wrappers = []
    for wrapper in manifest["wrappers"]:
        member = dict(wrapper)
        member.update({"role": "wrapper", "source": Path(repo) / "skill" / wrapper["name"]})
        wrappers.append(member)
    return [core, *wrappers]
