"""Apply presentation events to project state.

Kept free of store imports so store.py can call it. Every key is created on first
use, so a project that never runs a presentation command replays to exactly the
state it had before these commands existed.
"""

from __future__ import annotations

PRESENTATION_EVENTS = {
    "inventory_recorded",
    "inventory_confirmed",
    "transmission_consent",
    "presentation_decision",
    "listing_built",
}


def apply_presentation_event(state: dict, event: dict) -> dict:
    kind = event["type"]
    if kind == "inventory_recorded":
        state.setdefault("presentation", {}).setdefault("inventories", []).append(dict(event["inventory"]))
    elif kind == "inventory_confirmed":
        for inventory in state.get("presentation", {}).get("inventories", []):
            if inventory["id"] == event["inventory_id"]:
                inventory["confirmed"] = True
                inventory["user_quote"] = event["user_quote"]
    elif kind == "transmission_consent":
        for entry in state.get("files", []):
            if entry["id"] == event["file_id"]:
                entry["external_transmission_consent"] = True
                entry["consent_quote"] = event["user_quote"]
    elif kind == "presentation_decision":
        state.setdefault("presentation", {}).setdefault("decisions", []).append(
            {key: event[key] for key in ("kind", "ids", "decision", "user_quote", "timestamp")}
        )
    elif kind == "listing_built":
        state.setdefault("presentation", {}).setdefault("listings", []).append(dict(event["listing"]))
    return state
