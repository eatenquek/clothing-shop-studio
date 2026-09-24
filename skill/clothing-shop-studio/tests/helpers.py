from __future__ import annotations

import hashlib
import json
from pathlib import Path

FIXED_NOW = "2026-09-24T00:00:00Z"


def make_project(root: Path, name: str = "Test project") -> Path:
    from scripts.studio_core.store import create_project

    skill_dir = root / "installed-skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    state = create_project(root / "projects", name, skill_dir, FIXED_NOW)
    return root / "projects" / state["project_slug"]


def blank_state(name: str = "Test project") -> dict:
    return {
        "schema_version": 1,
        "project_name": name,
        "project_slug": "test-project",
        "created_at": FIXED_NOW,
        "updated_at": FIXED_NOW,
        "phase": "intake",
        "answers": {},
        "assumptions": [],
        "references": [],
        "concepts": [],
        "approvals": [],
        "production": {},
        "events_count": 0,
    }


def state_with_answers(**answers) -> dict:
    state = blank_state()
    state["answers"].update(answers)
    return state


def collect_question_ids(state: dict, graph: list[dict], limit: int = 10) -> list[str]:
    from scripts.studio_core.interview import next_question, record_answer

    working = json.loads(json.dumps(state, ensure_ascii=False))
    seen = []
    for _ in range(limit):
        question = next_question(working, graph)
        if question is None or question["id"] in seen:
            break
        seen.append(question["id"])
        working = record_answer(working, question["id"], "test-answer", source="user", user_quote="test reply")
    return seen


DEFAULT_AXES = ("density", "alignment", "distress", "scale")


def four_results(
    project: Path,
    axes=DEFAULT_AXES,
    decision_id: str = "back_typography",
    labels=("A", "B", "C", "W"),
) -> dict:
    """Write four labelled preview files and return a `register` payload for them."""
    output = project / "concepts" / "generated" / decision_id / "r01"
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for label, axis in zip(labels, axes):
        path = output / f"option-{label}.svg"
        path.write_text(f"<svg><text>{label}</text></svg>", encoding="utf-8")
        result = {
            "label": label,
            "axis": axis,
            "path": str(path.relative_to(project)),
            "renderer": "test-renderer",
            "prompt": f"Direction {label} varying {axis}",
        }
        if label == "W":
            result["convention_broken"] = "Type breaks the shoulder line"
        results.append(result)
    return {"decision_id": decision_id, "results": results}


def four_complete_briefs() -> list[dict]:
    return [
        {
            "label": label,
            "axis": axis,
            "title": f"Direction {label}",
            "brief": f"Vary the {axis}",
            "garment": "long_sleeve",
            "placement": "upper_back",
            "colors": ["#111111", "#F2F0EA"],
        }
        for label, axis in zip(("A", "B", "C", "W"), DEFAULT_AXES)
    ]


def register_file(
    project: Path,
    relative: str,
    content: bytes = b"file",
    origin: str | None = None,
    parent: str | None = None,
    **extra,
) -> dict:
    """Write a file and, when `origin` is given, record it directly in the event log.

    This deliberately bypasses the public registration checks, simulating a record
    that was mislabelled or renamed, so validation must catch the problem on its own.
    """
    from scripts.studio_core.store import append_event

    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    entry = {"path": relative, "sha256": hashlib.sha256(content).hexdigest()}
    if origin is None:
        return entry
    entry.update(
        {
            "id": f"raw-{Path(relative).stem}",
            "origin": origin,
            "parents": [parent] if parent else [],
            "registered_at": FIXED_NOW,
            "production_eligible": origin == "production_master",
            **extra,
        }
    )
    append_event(project, {"type": "files_registered", "entries": [entry]}, FIXED_NOW)
    return entry


def register_reference_text(project: Path, text: str = "reference") -> dict:
    """Register reference text through the public API, as the agent would."""
    from scripts.studio_core.validation import register_file as api_register_file

    path = project / "references/user/reference.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return api_register_file(
        project,
        {"origin": "user_reference", "path": "references/user/reference.txt", "extracted_text": text},
        FIXED_NOW,
    )


def register_concepts(project: Path) -> dict[str, dict]:
    """Register one A/B/C/W round and return the entries keyed by label."""
    from scripts.studio_core.options import register_options

    return {entry["label"]: entry for entry in register_options(project, four_results(project), FIXED_NOW)}


def register_vector_master(project: Path, name: str = "back-typography_MASTER.svg", **extra) -> dict:
    """Write a typeset SVG master and register it through the public API."""
    from scripts.studio_core.validation import register_file as api_register_file

    relative = f"production/masters/{name}"
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="300mm" height="120mm"><text>KIKI KAKA</text></svg>',
        encoding="utf-8",
    )
    payload = {"origin": "production_master", "path": relative, "construction": "typeset", **extra}
    return api_register_file(project, payload, FIXED_NOW)


def hash_tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != ".lock"
    }


READY_ANSWERS = {
    "reference_image": None,
    "garment_category": "long_sleeve",
    "intended_use": "everyday streetwear",
    "audience": "unisex young adult",
    "climate": "humid_tropical",
    "fit": "oversized relaxed",
    "fiber_blend": "100% combed cotton",
    "fabric_structure": "single jersey",
    "gsm": 220,
    "base_color": "black",
    "size_range": "S-XXL",
    "grading_strategy": "two print sizes: S-M at 280 mm, L-XXL at 320 mm wide",
    "artwork_content": "KIKI KAKA wordmark",
    "placement": "upper_back",
    "decoration_method": "plastisol screen print",
    "quantity": 100,
    "deliverables": "production_pack",
}

MASTER_SPEC = {
    "placement": "upper_back",
    "reference_point": "centre back, below the back neck seam",
    "offset_mm": 80,
    "print_width_mm": 300,
    "print_height_mm": 120,
    "colours": ["Off-white plastisol (match to approved strike-off)"],
    "decoration_method": "plastisol screen print",
}


def ready_project(
    root: Path,
    name: str = "Test project",
    assumptions: dict | None = None,
    answers: dict | None = None,
    master: dict | None = None,
) -> Path:
    """Build an export-ready project entirely through the public API.

    `assumptions` maps a field to overrides such as {"confirmed": False}; the field is
    then recorded as an unconfirmed inference instead of a user answer.
    """
    from scripts.studio_core.approval import approve_design
    from scripts.studio_core.store import append_event

    project = make_project(root, name)
    for field, value in {**READY_ANSWERS, **(answers or {})}.items():
        event = {"type": "answer", "field": field, "value": value}
        override = (assumptions or {}).get(field)
        if override is not None and not override.get("confirmed", True):
            event.update({"source": "inferred", "confirmed": False, "evidence": "test fixture"})
        append_event(project, event, FIXED_NOW)
    concepts = register_concepts(project)
    approve_design(project, [concepts["A"]["id"]], "Approve A", now=FIXED_NOW)
    register_vector_master(project, approved_version="v001", **{**MASTER_SPEC, **(master or {})})
    return project
