from __future__ import annotations

import json


def render_project_yaml(state: dict) -> str:
    """Render deterministic JSON, which is a safe YAML 1.2 subset."""
    return json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_manifest(state: dict) -> str:
    """Render metadata/manifest.json from the canonical file records in state."""
    payload = {
        "schema_version": state.get("schema_version", 1),
        "layout_version": state.get("layout_version", 1),
        "path_base": state.get("path_base", "project_dir"),
        "files": state.get("files", []),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_decisions_md(events: list[dict]) -> str:
    lines = ["# Project decisions", ""]
    if not events:
        return "\n".join(lines + ["No decisions recorded.", ""])
    for index, event in enumerate(events, start=1):
        event_type = str(event.get("type", "event")).replace("_", " ").title()
        timestamp = event.get("timestamp", "unknown time")
        lines.extend([f"## {index}. {event_type}", "", f"- Time: `{timestamp}`"])
        for key in sorted(event):
            if key in {"type", "timestamp", "previous_hash", "event_hash"}:
                continue
            value = json.dumps(event[key], ensure_ascii=False, sort_keys=True)
            lines.append(f"- {key.replace('_', ' ').title()}: `{value}`")
        lines.append("")
    return "\n".join(lines)
