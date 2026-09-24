from __future__ import annotations

import hashlib
import json
from pathlib import Path

FIXED_NOW = "2026-09-24T00:00:00Z"


def make_project(root: Path, name: str = "Test project") -> Path:
    from scripts.studio_core.store import create_project

    skill_dir = root / "installed-skill"
    skill_dir.mkdir(exist_ok=True)
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
        working = record_answer(working, question["id"], "test-answer", source="user")
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


def ready_project(root: Path) -> Path:
    project = make_project(root)
    state_path = project / "metadata" / "state.json"
    state = json.loads(state_path.read_text("utf-8"))
    state["phase"] = "production"
    state["answers"].update(
        {
            "garment_type": "t-shirt",
            "material": "cotton jersey",
            "decoration_method": "screen_print",
            "quantity": 100,
            "size_range": "XS-XXL",
        }
    )
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return project
