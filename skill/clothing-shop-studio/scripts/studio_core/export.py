"""Decoration/fabric compatibility and versioned production-pack export."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from pathlib import Path
from string import Template

from .errors import StorageError, ValidationError
from .interview import CRITICAL_FIELDS, triggered_confirmations
from .store import _utc_now, append_event, canonical_json, load_state, write_atomic
from .validation import validate_project

BUNDLE_DIR = Path(__file__).resolve().parents[2]
RULES_PATH = BUNDLE_DIR / "data/compatibility-rules.json"
ASSETS_DIR = BUNDLE_DIR / "assets"
PRODUCTION_DIR = Path("production")
PACK_PATTERN = re.compile(r"^pack-v(\d{3,})$")
READ_ONLY = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
PLACEMENT_KEYS = ("placement", "reference_point", "offset_mm", "print_width_mm", "print_height_mm")
DARK_TONES = {"black", "charcoal", "navy", "dark", "graphite", "forest", "maroon", "burgundy", "brown", "olive"}
LIGHT_TONES = {"white", "cream", "off_white", "ivory", "bone", "natural", "ecru", "light", "pastel", "sand"}
PROOF_STEPS = {
    "screen_print": "Approve a physical strike-off on the production garment before bulk printing.",
    "water_based_screen_print": "Approve a physical strike-off on the production garment before bulk printing.",
    "embroidery": "Approve a physical sew-out on the production fabric before bulk embroidery.",
    "embroidery_patch": "Approve a physical sew-out of the patch before bulk production.",
}
DEFAULT_PROOF = "Approve a physical sample print on the production garment before bulk production."
DEFAULT_TOLERANCES = [
    "Print placement: within ±5 mm of the stated reference point and offset.",
    "Print size: within ±3 mm of the stated width and height.",
    "Horizontal alignment: centred on the garment centre line within ±5 mm, unless placement says otherwise.",
    "Colour: match the approved physical strike-off or sample; screen previews are not colour standards.",
    "Garment measurements: follow the producer's graded specification; agree tolerances with the producer.",
]


# --- Compatibility -----------------------------------------------------------

def _tokens(text) -> str:
    """Normalise free text to `_token_token_` so keywords match whole words only."""
    return "_" + re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_") + "_"


def _matches(text: str, matcher: dict) -> bool:
    has = lambda keyword: f"_{keyword}_" in text  # noqa: E731 - tiny local predicate
    return (
        all(has(keyword) for keyword in matcher.get("all", []))
        and (not matcher.get("any") or any(has(keyword) for keyword in matcher["any"]))
        and not any(has(keyword) for keyword in matcher.get("none", []))
    )


def load_rules(path: Path = RULES_PATH) -> dict:
    try:
        return json.loads(Path(path).read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "The compatibility rules are missing or unreadable.",
            path=str(path),
            recovery="Reinstall the skill bundle.",
        ) from exc


def fabric_tone(base_color) -> str | None:
    words = set(_tokens(base_color).strip("_").split("_"))
    if words & LIGHT_TONES:
        return "light"
    if words & DARK_TONES:
        return "dark"
    return None


def _conditions_hold(conditions: dict | None, facts: dict) -> tuple[bool, list[str]]:
    """Whether a rule's conditions hold, plus conditions that could not be checked.

    A missing count is reported as unverified rather than failing the rule; a missing
    fabric tone fails it, because tone-specific rules must not fire on a guess.
    """
    unverified = []
    for key, condition in (conditions or {}).items():
        actual = facts.get(key)
        if actual is None:
            if key == "fabric_tone":
                return False, []
            unverified.append(key)
            continue
        if isinstance(condition, dict):
            if not condition.get("min", actual) <= actual <= condition.get("max", actual):
                return False, []
        elif actual != condition:
            return False, []
    return True, unverified


def check_compatibility(facts: dict, rules: dict | None = None) -> dict:
    """Classify a decoration/fabric combination by the first matching rule."""
    rules = rules or load_rules()
    decoration_text = _tokens(facts.get("decoration"))
    fabric_text = _tokens(facts.get("fabric"))
    decoration = next(
        (name for name, matcher in rules["decorations"].items() if _matches(decoration_text, matcher)),
        None,
    )
    groups = [name for name, matcher in rules["fabric_groups"].items() if _matches(fabric_text, matcher)]
    for rule in rules["rules"]:
        if decoration not in rule["decorations"]:
            continue
        if rule.get("fabric_group") and rule["fabric_group"] not in groups:
            continue
        applies, unverified = _conditions_hold(rule.get("conditions"), facts)
        if not applies:
            continue
        status = rule["result"]
        return {
            "status": status,
            "compatible": {"compatible": True, "conditionally_compatible": True, "incompatible": False}[status],
            "rule_id": rule["id"],
            "decoration": decoration,
            "fabric_groups": groups,
            "alternatives": list(rule.get("alternatives", [])),
            "notes": rule["notes"],
            "confirm": rule["confirm"],
            "unverified_conditions": unverified,
        }
    return {
        "status": "unverified",
        "compatible": None,
        "rule_id": None,
        "decoration": decoration,
        "fabric_groups": groups,
        "alternatives": [],
        "notes": "No rule covers this combination.",
        "confirm": "Confirm feasibility with the producer, with a physical sample, before production.",
        "unverified_conditions": [],
    }


# --- Export ------------------------------------------------------------------

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _display(value) -> str:
    """Show canonical tokens such as `upper_back` as words for a factory reader."""
    text = str(value)
    return text.replace("_", " ") if re.fullmatch(r"[a-z]+(?:_[a-z]+)+", text) else text


def _value(answers: dict, field: str) -> str:
    value = answers.get(field)
    return "Not specified — confirm with the producer" if value in (None, "") else _display(value)


def _latest_approval(state: dict) -> dict | None:
    approvals = state.get("approvals", [])
    return approvals[-1] if approvals else None


def _masters(state: dict, approved_version: str | None = None) -> list[dict]:
    masters = [item for item in state.get("files", []) if item.get("origin") == "production_master"]
    if approved_version is not None:
        masters = [item for item in masters if item.get("approved_version") == approved_version]
    return masters


def _fabric_text(answers: dict) -> str:
    return " ".join(str(answers[key]) for key in ("fiber_blend", "fabric_structure") if answers.get(key))


def _compatibility(state: dict, masters: list[dict] | None = None) -> list[tuple[dict, dict]]:
    answers = state.get("answers", {})
    results = []
    for master in _masters(state) if masters is None else masters:
        colours = master.get("colours")
        facts = {
            "fabric": _fabric_text(answers),
            "decoration": master.get("decoration_method") or answers.get("decoration_method"),
            "spot_colors": len(colours) if isinstance(colours, list) and colours else None,
            "fabric_tone": fabric_tone(answers.get("base_color")),
        }
        results.append((master, check_compatibility(facts)))
    return results


def export_blockers(project_dir: Path) -> tuple[list[dict], list[dict]]:
    """Return (errors, warnings) that decide whether a production pack can be exported."""
    project = Path(project_dir)
    report = validate_project(project, for_export=True)
    errors, warnings = list(report["errors"]), list(report["warnings"])
    state = load_state(project)
    answers = state.get("answers", {})
    for field in triggered_confirmations(state):
        errors.append(
            {
                "code": "required_confirmation_pending",
                "message": f"`{field}` must be answered by the user before production export.",
                "field": field,
            }
        )
    for field in sorted(CRITICAL_FIELDS):
        if answers.get(field) in (None, ""):
            errors.append({"code": "missing_critical_answer", "message": f"`{field}` has not been answered.", "field": field})
    latest = _latest_approval(state)
    if latest is None:
        errors.append({"code": "no_approved_design", "message": "No design has been approved with approve_design."})
    else:
        answers_sha256 = hashlib.sha256(canonical_json(answers).encode("utf-8")).hexdigest()
        if latest.get("answers_sha256") != answers_sha256:
            errors.append(
                {
                    "code": "approval_answers_changed",
                    "message": "Project answers changed after the latest design approval.",
                    "version": latest["version"],
                }
            )
    masters = _masters(state, latest["version"] if latest else None)
    if not masters:
        errors.append(
            {
                "code": "no_current_production_master" if latest else "no_production_master",
                "message": "Register at least one production master for the latest approved version.",
            }
        )
    approved = {item["version"] for item in state.get("approvals", [])}
    for master in masters:
        missing = [key for key in PLACEMENT_KEYS if master.get(key) in (None, "")]
        if missing:
            errors.append(
                {
                    "code": "master_missing_dimensions",
                    "message": f"`{master['id']}` is missing {', '.join(missing)}.",
                    "id": master["id"],
                }
            )
        if master.get("approved_version") not in approved:
            errors.append(
                {
                    "code": "master_not_linked_to_approval",
                    "message": f"`{master['id']}` must name the approved version it implements.",
                    "id": master["id"],
                }
            )
    for master, result in _compatibility(state, masters):
        finding = {"id": master["id"], "rule_id": result["rule_id"], "message": f"{result['notes']} {result['confirm']}"}
        if result["status"] == "incompatible":
            errors.append({"code": "incompatible_production_method", **finding, "alternatives": result["alternatives"]})
        elif result["status"] != "compatible" or result["unverified_conditions"]:
            warnings.append({"code": f"compatibility_{result['status']}", **finding})
    if answers.get("grading_strategy") in (None, ""):
        warnings.append(
            {"code": "no_grading_strategy", "message": "Confirm whether one print size suits the whole size range."}
        )
    return errors, warnings


def next_pack_version(project_dir: Path, state: dict) -> str:
    numbers = [int(pack["version"].split("pack-v")[1]) for pack in state.get("production", {}).get("packs", [])]
    root = Path(project_dir) / PRODUCTION_DIR
    if root.is_dir():
        numbers += [int(match.group(1)) for path in root.iterdir() if (match := PACK_PATTERN.match(path.name))]
    return f"pack-v{max(numbers, default=0) + 1:03d}"


def _master_filename(state: dict, master: dict, pack_version: str, used: set[str]) -> str:
    placement = re.sub(r"[^\w-]+", "-", str(master.get("placement") or "artwork").replace("_", "-")).strip("-")
    stem = f"{state['project_slug']}_{master.get('approved_version')}_{placement}_MASTER_{pack_version}"
    name, suffix, counter = stem, Path(master["path"]).suffix, 2
    while f"{name}{suffix}" in used:
        name = f"{stem}-{counter}"
        counter += 1
    used.add(f"{name}{suffix}")
    return f"{name}{suffix}"


def _template(name: str) -> Template:
    try:
        return Template((ASSETS_DIR / name).read_text("utf-8"))
    except OSError as exc:
        raise ValidationError(f"Template {name} is missing.", recovery="Reinstall the skill bundle.") from exc


def _render_spec(state: dict, pack_version: str, copies: list[tuple[dict, str]], warnings: list[dict], now: str) -> str:
    answers = state.get("answers", {})
    latest = _latest_approval(state)
    approvals = latest["version"] if latest else "None"
    garment = "\n".join(
        f"- {label}: {_value(answers, field)}"
        for label, field in (
            ("Category", "garment_category"),
            ("Subtype", "garment_subtype"),
            ("Intended use", "intended_use"),
            ("Audience", "audience"),
            ("Climate", "climate"),
            ("Fit", "fit"),
            ("Length", "length"),
            ("Construction", "construction"),
        )
    )
    material = "\n".join(
        f"- {label}: {_value(answers, field)}"
        for label, field in (
            ("Fibre blend", "fiber_blend"),
            ("Fabric structure", "fabric_structure"),
            ("Weight (GSM)", "gsm"),
            ("Hand-feel", "handfeel"),
            ("Stretch", "stretch"),
            ("Opacity", "opacity"),
            ("Care", "care"),
        )
    )
    placement_rows = ["| Master | Placement | Reference point | Offset | Print size |", "|---|---|---|---|---|"]
    colour_lines = [f"- Garment colour: {_value(answers, 'base_color')}"]
    for master, filename in copies:
        placement_rows.append(
            f"| `{_cell(filename)}` | {_cell(_display(master['placement']))} | {_cell(master['reference_point'])} | "
            f"{master['offset_mm']:g} mm | {master['print_width_mm']:g} × {master['print_height_mm']:g} mm |"
        )
        colours = master.get("colours") or ["Not specified — confirm with the producer"]
        colour_lines.append(f"- `{_cell(filename)}`: {'; '.join(str(colour) for colour in colours)}")
    colour_lines.append(
        "- Limitation: hex, RGB, and CMYK values are screen approximations. Colour-critical items must match an "
        "approved physical proof; Pantone codes are listed only where the client supplied them."
    )
    filenames = {master["id"]: filename for master, filename in copies}
    decoration_lines = []
    for master, result in _compatibility(state, [master for master, _ in copies]):
        decoration_lines.append(
            f"- `{_cell(filenames[master['id']])}`: "
            f"{master.get('decoration_method') or _value(answers, 'decoration_method')} — "
            f"{result['notes']} {result['confirm']}"
        )
    sizing = "\n".join(
        [
            f"- Size range: {_value(answers, 'size_range')}",
            f"- Artwork scaling: {_value(answers, 'grading_strategy')}",
            f"- Fit and length: {_value(answers, 'fit')}; {_value(answers, 'length')}",
            "- Assumption: garment dimensions follow the producer's graded size chart until a measured spec is agreed.",
        ]
    )
    tolerances = answers.get("tolerances")
    tolerance_lines = [f"- {line}" for line in (tolerances if isinstance(tolerances, list) else DEFAULT_TOLERANCES)]
    if not isinstance(tolerances, list):
        tolerance_lines.append("- These are proposed tolerances; confirm them with the producer.")
    file_rows = ["| File | Role | Construction | Implements | SHA-256 |", "|---|---|---|---|---|"]
    for master, filename in copies:
        file_rows.append(
            f"| `masters/{_cell(filename)}` | Production master | {_cell(master.get('construction'))} | "
            f"{_cell(master.get('approved_version'))} | `{master['sha256'][:12]}…` |"
        )
    file_rows.append("| `handoff-checklist.md` | Factory checklist | — | — | see manifest.json |")
    proofs = {
        PROOF_STEPS.get(result["decoration"], DEFAULT_PROOF)
        for _, result in _compatibility(state, [master for master, _ in copies])
    } or {DEFAULT_PROOF}
    unconfirmed = [item for item in warnings if item["code"] == "unconfirmed_assumption"]
    assumptions = "\n".join(f"- {item['message']}" for item in unconfirmed) or "- All recorded assumptions are confirmed."
    other = [item for item in warnings if item["code"] != "unconfirmed_assumption"]
    notes = "\n".join(f"- {item['message']}" for item in other) or "- No open compatibility warnings."
    return _template("production-spec-template.md").substitute(
        project_name=state["project_name"],
        pack_version=pack_version,
        approved_versions=approvals,
        exported_at=now,
        garment_section=garment,
        material_section=material,
        placement_section="\n".join(placement_rows),
        colour_section="\n".join(colour_lines),
        decoration_section="\n".join(decoration_lines),
        sizing_section=sizing,
        tolerances_section="\n".join(tolerance_lines),
        files_section="\n".join(file_rows),
        proofs_section="\n".join(f"- {line}" for line in sorted(proofs)),
        assumptions_section=assumptions,
        notes_section=notes,
    )


def _render_checklist(state: dict, pack_version: str, warnings: list[dict], masters: list[dict]) -> str:
    answers = state.get("answers", {})
    proofs = sorted(
        {PROOF_STEPS.get(result["decoration"], DEFAULT_PROOF) for _, result in _compatibility(state, masters)}
    )
    open_items = "\n".join(f"- [ ] {item['message']}" for item in warnings) or "- [ ] None recorded at export."
    return _template("handoff-checklist-template.md").substitute(
        project_name=state["project_name"],
        pack_version=pack_version,
        approved_versions=_latest_approval(state)["version"],
        size_range=_value(answers, "size_range"),
        decoration=_value(answers, "decoration_method"),
        fabric=_fabric_text(answers) or "Not specified — confirm with the producer",
        gsm=_value(answers, "gsm"),
        quantity=_value(answers, "quantity"),
        proof_steps="\n".join(f"- [ ] {line}" for line in proofs or [DEFAULT_PROOF]),
        open_items=open_items,
    )


def export_production_pack(project_dir: Path, now: str | None = None) -> Path:
    """Validate the project and write a new, read-only production/pack-vNNN/."""
    project = Path(project_dir)
    errors, warnings = export_blockers(project)
    if errors:
        raise ValidationError(
            "Production export is blocked: " + ", ".join(sorted({item["code"] for item in errors})) + ".",
            recovery="Resolve each blocker in `details`, then export again.",
            details=errors,
        )
    state = load_state(project)
    timestamp = now or _utc_now()
    version = next_pack_version(project, state)
    target = project / PRODUCTION_DIR / version
    try:
        target.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise StorageError(f"{version} already exists.", path=str(target), recovery="Export again.") from exc
    try:
        (target / "masters").mkdir()
        used: set[str] = set()
        copies = []
        latest = _latest_approval(state)
        masters = _masters(state, latest["version"])
        for master in masters:
            filename = _master_filename(state, master, version, used)
            shutil.copyfile(project / master["path"], target / "masters" / filename)
            if _sha256(target / "masters" / filename) != master["sha256"]:
                raise ValidationError(f"`{master['id']}` changed while exporting.", recovery="Validate and export again.")
            copies.append((master, filename))
        write_atomic(target / "production-spec.md", _render_spec(state, version, copies, warnings, timestamp).encode("utf-8"))
        write_atomic(target / "handoff-checklist.md", _render_checklist(state, version, warnings, masters).encode("utf-8"))
        files = [
            {"path": f"masters/{filename}", "role": "production_master", "source_id": master["id"], "sha256": _sha256(target / "masters" / filename)}
            for master, filename in copies
        ] + [
            {"path": name, "role": role, "source_id": None, "sha256": _sha256(target / name)}
            for name, role in (("production-spec.md", "production_spec"), ("handoff-checklist.md", "handoff_checklist"))
        ]
        manifest = {
            "schema_version": 1,
            "project_name": state["project_name"],
            "pack_version": version,
            "approved_versions": [latest["version"]],
            "exported_at": timestamp,
            "files": files,
            "warnings": warnings,
        }
        manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        write_atomic(target / "manifest.json", manifest_bytes)
        record = {
            "version": version,
            "path": target.relative_to(project).as_posix(),
            "files": files,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "approved_versions": manifest["approved_versions"],
            "exported_at": timestamp,
        }
        append_event(project, {"type": "production_exported", "pack": record}, timestamp)
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    for path in target.rglob("*"):
        if path.is_file():
            os.chmod(path, READ_ONLY)
    return target
