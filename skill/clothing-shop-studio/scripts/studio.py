#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from studio_core import SCHEMA_VERSION
from studio_core.config import resolve_storage_root, save_storage_root
from studio_core.errors import StudioError, ValidationError
from studio_core.approval import approve_design
from studio_core.export import export_blockers, export_production_pack
from studio_core.interview import load_graph, next_question
from studio_core.options import merge_concept, next_round, plan_options, register_options
from studio_core.store import append_event, create_project, load_state, status
from studio_core.validation import register_file, validate_project

BUNDLE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path.home() / ".config/clothing-shop-studio/config.json"


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValidationError(
            f"Invalid command line: {message}",
            field="command",
            recovery="Choose a supported command and pass command data as one JSON object on stdin.",
        )


def _next_question(state: dict) -> dict | None:
    return next_question(state, load_graph(BUNDLE_DIR))


def _required(payload: dict, field: str):
    value = payload.get(field)
    if value is None or value == "":
        raise ValidationError(
            f"{field.replace('_', ' ').title()} is required.",
            field=field,
            recovery=f"Provide `{field}` and retry.",
        )
    return value


def command_create_project(payload: dict) -> dict:
    if "config_path" in payload:
        raise ValidationError(
            "The command payload cannot choose the application config path.",
            field="config_path",
            recovery="Remove `config_path`; provide `root` to choose this project's storage location.",
        )
    requested = Path(payload["root"]) if payload.get("root") else None
    config_path = DEFAULT_CONFIG
    root = resolve_storage_root(requested, BUNDLE_DIR, os.environ, config_path)
    if payload.get("remember_root"):
        save_storage_root(root, config_path)
    now = payload.get("now") or __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    state = create_project(root, _required(payload, "name"), BUNDLE_DIR, now)
    return {
        **state,
        "project_dir": str(root / state["project_slug"]),
        "next_question": _next_question(state),
    }


def command_resume_project(payload: dict) -> dict:
    state = load_state(Path(_required(payload, "project_dir")))
    return {**state, "next_question": _next_question(state)}


def command_record_answer(payload: dict) -> dict:
    """Append one answer event and return the new state plus exactly one next question."""
    project = Path(_required(payload, "project_dir"))
    if "value" not in payload:
        raise ValidationError(
            "Value is required; send null to decline an optional question.",
            field="value",
            recovery="Provide `value` and retry.",
        )
    event = {
        "type": "answer",
        "field": _required(payload, "field"),
        "value": payload["value"],
        "source": payload.get("source", "user"),
        "confirmed": payload.get("confirmed", True),
    }
    for key in ("evidence", "user_quote"):
        if payload.get(key) is not None:
            event[key] = payload[key]
    state = append_event(project, event, payload.get("now"))
    return {"state": state, "next_question": _next_question(state)}


def command_generate_options(payload: dict) -> dict:
    """`plan` returns A/B/C/W slots; `register` records four renders; `merge` records a combination."""
    project = Path(_required(payload, "project_dir"))
    mode = payload.get("mode")
    if mode == "plan":
        state = load_state(project)
        decision_id = _required(payload, "decision_id")
        return plan_options(
            decision_id,
            payload.get("axes"),
            payload.get("constraints") or {},
            briefs=payload.get("briefs"),
            round_number=next_round(state, decision_id),
        )
    if mode == "register":
        return {"entries": register_options(project, payload, payload.get("now"))}
    if mode == "merge":
        return {"entry": merge_concept(project, payload, payload.get("now"))}
    raise ValidationError(
        "Mode must be `plan`, `register`, or `merge`.",
        field="mode",
        recovery="Plan the four options first, render them, then register the files.",
    )


def command_approve_design(payload: dict) -> dict:
    project = Path(_required(payload, "project_dir"))
    target = approve_design(project, payload.get("concept_ids"), payload.get("statement"), payload.get("now"))
    record = next(item for item in load_state(project)["approvals"] if item["version"] == target.name)
    return {"version": target.name, "path": str(target), "approval": record}


def command_register_file(payload: dict) -> dict:
    return register_file(Path(_required(payload, "project_dir")), payload, payload.get("now"))


def command_export_production_pack(payload: dict) -> dict:
    project = Path(_required(payload, "project_dir"))
    target = export_production_pack(project, payload.get("now"))
    pack = next(item for item in load_state(project)["production"]["packs"] if item["version"] == target.name)
    return {"pack_version": target.name, "path": str(target), "pack": pack}


def command_validate(payload: dict) -> dict:
    project = Path(_required(payload, "project_dir"))
    if payload.get("for_export"):
        errors, warnings = export_blockers(project, master_ids=payload.get("master_ids"))
        return {"ok": not errors, "errors": errors, "warnings": warnings}
    return validate_project(project, master_ids=payload.get("master_ids"), for_export=False)


def command_status(payload: dict) -> dict:
    project = Path(_required(payload, "project_dir"))
    summary = status(project)
    report = validate_project(project)
    return {
        **summary,
        "next_question": _next_question(load_state(project)),
        "blockers": report["errors"],
        "warnings": report["warnings"],
    }


COMMANDS = {
    "create_project": command_create_project,
    "resume_project": command_resume_project,
    "record_answer": command_record_answer,
    "generate_options": command_generate_options,
    "approve_design": command_approve_design,
    "export_production_pack": command_export_production_pack,
    "register_file": command_register_file,
    "validate": command_validate,
    "status": command_status,
}


def parse_args(argv=None):
    parser = JsonArgumentParser(description="Clothing Shop Studio project command shell")
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--input", help="Read the JSON payload from this file instead of stdin")
    return parser.parse_args(argv)


def emit(payload: dict) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


def error_response(command: str, exc: StudioError) -> dict:
    return {
        "ok": False,
        "command": command,
        "schema_version": SCHEMA_VERSION,
        "error": exc.as_dict(),
    }


def main(argv=None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    command = raw_args[0] if raw_args and raw_args[0] in COMMANDS else "command_error"
    try:
        args = parse_args(raw_args)
        command = args.command
        if args.input:
            input_path = Path(args.input)
            try:
                payload = json.loads(input_path.read_text("utf-8"))
            except OSError as exc:
                raise ValidationError(
                    "Command input file could not be read.",
                    path=str(input_path),
                    recovery="Provide a readable JSON input file or send the payload on stdin.",
                ) from exc
        else:
            payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValidationError(
                "Command input must be a JSON object.",
                recovery="Provide an object containing the command fields.",
            )
        result = COMMANDS[args.command](payload)
        emit(
            {
                "ok": True,
                "command": args.command,
                "schema_version": SCHEMA_VERSION,
                "data": result,
            }
        )
        return 0
    except json.JSONDecodeError as exc:
        wrapped = ValidationError(
            "Command input is not valid JSON.",
            recovery="Correct the JSON payload and retry.",
        )
        emit(error_response(command, wrapped))
        return wrapped.exit_code
    except StudioError as exc:
        emit(error_response(command, exc))
        return exc.exit_code
    except Exception:
        # Keep the JSON command contract even when an unexpected implementation
        # defect occurs; do not expose internal paths or object names to callers.
        exc = StudioError(
            "The command failed unexpectedly.",
            recovery="Retry once, then run the skill validator and report the command if it persists.",
        )
        emit(error_response(command, exc))
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
