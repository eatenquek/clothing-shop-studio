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


def four_results(project: Path) -> list[dict]:
    output = project / "concepts" / "generated"
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for label in ("A", "B", "C", "W"):
        path = output / f"option-{label}.svg"
        path.write_text(f"<svg><text>{label}</text></svg>", encoding="utf-8")
        results.append({"label": label, "path": str(path.relative_to(project))})
    return results


def four_complete_briefs() -> list[dict]:
    return [
        {"label": label, "axis": f"axis-{label}", "brief": f"Direction {label}"}
        for label in ("A", "B", "C", "W")
    ]


def register_file(project: Path, relative: str, content: bytes = b"file") -> dict:
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {
        "path": relative,
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def register_reference_text(project: Path, text: str = "reference") -> dict:
    record = register_file(project, "references/user/reference.txt", text.encode("utf-8"))
    return {**record, "origin": "user_reference"}


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
