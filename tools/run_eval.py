#!/usr/bin/env python3
"""Run one behavioural scenario in a fresh headless Claude session with the skill installed.

The skill bundle is copied into a throwaway workspace as a project skill, so the session
must discover it from its description. User-level settings, hooks, plugins, and MCP
servers are excluded, and Bash is limited to the skill's own scripts. The scenario's
expected behaviours are never shown to the session.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

SKILL_NAME = "clothing-shop-studio"
REPO_ROOT = Path(__file__).resolve().parents[1]


def create_eval_workspace(studio_root: Path) -> Path:
    eval_root = Path(studio_root).resolve() / ".work/evals"
    eval_root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="css-eval-", dir=eval_root))


def evaluation_environment(workspace: Path, base_env: dict | None = None) -> tuple[dict, Path]:
    home = Path(workspace).resolve() / "home"
    home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ if base_env is None else base_env)
    env.pop("CLOTHING_SHOP_STUDIO_HOME", None)
    env["HOME"] = str(home)
    projects = home / "Documents/Clothing-Shop-Studio/projects"
    return env, projects


def allowed_tools(skill_dir: Path) -> list[str]:
    scripts = [skill_dir / "scripts/studio.py", skill_dir / "scripts/render-options.py"]
    rules = ["Read", "Glob", "Grep", "Write", "Edit", "Skill"]
    for prefix in ("echo", "printf", "cat", "ls", "cd", "mkdir", "cp"):
        rules.append(f"Bash({prefix}:*)")
    for script in scripts:
        relative = script.relative_to(skill_dir)
        rules += [f"Bash(python3 {script}:*)", f"Bash(python3 {relative}:*)", f"Bash(python3 ./{relative}:*)",
                  f"Bash(python3 .claude/skills/{SKILL_NAME}/{relative}:*)"]
    return rules


def run_turn(prompt: str, workspace: Path, skill_dir: Path, session: str | None, env: dict) -> dict:
    command = [
        "claude", "-p", prompt,
        "--output-format", "stream-json", "--verbose",
        "--setting-sources", "project",
        "--strict-mcp-config",
        "--permission-mode", "acceptEdits",
        "--allowedTools", *allowed_tools(skill_dir),
    ]
    if session:
        command += ["--resume", session]
    completed = subprocess.run(command, cwd=workspace, env=env, text=True, capture_output=True, timeout=900)
    tools, result = [], {}
    for line in completed.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    tools.append({"name": block["name"], "input": block.get("input", {})})
        elif event.get("type") == "result":
            result = event
    if not result:
        raise RuntimeError(f"claude produced no result (exit {completed.returncode}): {completed.stderr[-2000:]}")
    return {"text": result.get("result", ""), "session": result.get("session_id"), "tools": tools,
            "cost": result.get("total_cost_usd"), "turns": result.get("num_turns")}


def describe_tool(tool: dict) -> str:
    data = tool["input"]
    detail = data.get("command") or data.get("file_path") or data.get("skill") or data.get("pattern") or ""
    return f"{tool['name']}: {str(detail).strip()[:400]}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--extra-turns", type=int, default=0,
                        help="Append this many neutral follow-ups to observe later interview behaviour.")
    parser.add_argument("--extra-text", default="Use your recommendation and continue.")
    args = parser.parse_args(argv)

    scenario = json.loads(args.scenario.read_text("utf-8"))
    workspace = create_eval_workspace(REPO_ROOT.parent)
    skill_dir = workspace / ".claude/skills" / SKILL_NAME
    shutil.copytree(args.bundle, skill_dir, ignore=shutil.ignore_patterns("__pycache__", "tests", "evals"))
    env, projects = evaluation_environment(workspace)

    prompts = [scenario["query"]]
    if scenario.get("fixture"):
        fixture = (args.scenario.parent / scenario["fixture"]).resolve()
        shutil.copy(fixture, workspace / fixture.name)
        prompts[0] += f"\n\nAttached reference image: ./{fixture.name}"
    prompts += scenario.get("followups", [])
    prompts += [args.extra_text] * args.extra_turns

    lines = [f"# GREEN evaluation: {scenario['id']}", "", f"- Workspace: `{workspace}`",
             "- Harness: fresh headless `claude -p` session; skill installed as a project skill; "
             "user settings, hooks, plugins, and MCP servers excluded; Bash limited to the skill scripts.", ""]
    session = None
    for number, prompt in enumerate(prompts, start=1):
        turn = run_turn(prompt, workspace, skill_dir, session, env)
        session = turn["session"]
        lines += [f"## Turn {number}", "", "**User:**", "", *[f"> {row}".rstrip() for row in prompt.splitlines()], "",
                  "**Tool calls:**", ""]
        lines += [f"- `{describe_tool(tool)}`" for tool in turn["tools"]] or ["- none"]
        lines += ["", "**Assistant (verbatim):**", "", *[f"> {row}" if row else ">" for row in turn["text"].splitlines()], ""]

    lines += ["## Project state after the session", ""]
    for state_file in sorted(projects.glob("*/metadata/state.json")):
        state = json.loads(state_file.read_text("utf-8"))
        lines += [f"- Project `{state['project_slug']}`: phase `{state['phase']}`, "
                  f"{len(state['answers'])} answers, {len(state.get('files', []))} files, "
                  f"{len(state.get('approvals', []))} approvals",
                  f"- Answers: `{json.dumps(state['answers'], ensure_ascii=False, sort_keys=True)}`"]
    skill_mutations = sorted(str(path.relative_to(skill_dir)) for path in skill_dir.rglob("*")
                             if path.is_file() and not (args.bundle / path.relative_to(skill_dir)).exists())
    lines += [f"- Files added inside the installed skill: {skill_mutations or 'none'}", ""]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines).rstrip() + "\n", "utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
