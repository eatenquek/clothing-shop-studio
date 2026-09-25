#!/usr/bin/env python3
"""Run one Clothing Shop Studio command-family scenario through Codex.

The default optional evaluation mode probes ``codex exec`` with
``OPENAI_API_KEY`` in a throwaway environment, falling back to a throwaway
``codex login --with-api-key`` when required. Personal release smoke mode uses
the operator's existing Codex login, removes API credentials from the child
environment, installs the committed family project-locally, and keeps garment
data under a throwaway ``HOME``. Every transcript records the selected mode and
the exact installed tree hashes.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from tools import install_transaction
    from tools.family_manifest import load_manifest
except ModuleNotFoundError:  # Direct ``python3 tools/run_codex_family_eval.py`` execution.
    import install_transaction
    from family_manifest import load_manifest


REPO_ROOT = Path(__file__).resolve().parents[1]
STUDIO_DATA_FOLDERS = ("projects", "references", "generated", "approved", "production", "exports")
AUTH_FAILURE_MARKERS = (
    "not logged in", "authentication", "unauthorized", "api key", "api_key", "401",
)
KEY_SHAPE = re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b")


def _top_level_names(path: Path) -> list[str]:
    try:
        return sorted(item.name for item in Path(path).iterdir())
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return []


def _folder_hashes(path: Path) -> dict[str, str]:
    result = {}
    if not path.is_dir():
        return result
    for item in sorted(path.rglob("*")):
        if not item.is_file() or item.is_symlink():
            continue
        try:
            result[item.relative_to(path).as_posix()] = hashlib.sha256(item.read_bytes()).hexdigest()
        except (OSError, PermissionError) as exc:
            result[item.relative_to(path).as_posix()] = f"unreadable:{type(exc).__name__}"
    return result


def real_boundary_snapshot(home: Path) -> dict:
    """Snapshot only the real boundaries the isolated evaluation must not change."""
    home = Path(home).expanduser().resolve(strict=False)
    studio = home / "Documents/Clothing-Shop-Studio"
    return {
        "home_top_level": _top_level_names(home),
        "skills_top_level": _top_level_names(home / ".codex/skills"),
        "studio_root_exists": studio.is_dir(),
        "studio_data": {
            name: {
                "exists": (studio / name).is_dir(),
                "files": _folder_hashes(studio / name),
            }
            for name in STUDIO_DATA_FOLDERS
        },
    }


def evaluation_environment(
    workspace: Path, base_env: dict | None = None
) -> tuple[dict, Path, Path]:
    workspace = Path(workspace).resolve()
    home = workspace / "home"
    codex_home = home / ".codex"
    codex_home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ if base_env is None else base_env)
    env.pop("CLOTHING_SHOP_STUDIO_HOME", None)
    env["HOME"] = str(home)
    env["CODEX_HOME"] = str(codex_home)
    return env, codex_home, home / "Documents/Clothing-Shop-Studio"


def personal_smoke_environment(
    workspace: Path, current_codex_home: Path, base_env: dict | None = None
) -> tuple[dict, Path, Path]:
    """Reuse an existing Codex login while isolating all garment project data."""
    workspace = Path(workspace).resolve()
    home = workspace / "home"
    codex_home = Path(current_codex_home).expanduser().resolve()
    home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ if base_env is None else base_env)
    for name in ("CLOTHING_SHOP_STUDIO_HOME", "OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"):
        env.pop(name, None)
    env["HOME"] = str(home)
    env["CODEX_HOME"] = str(codex_home)
    return env, codex_home, home / "Documents/Clothing-Shop-Studio"


def redact(value: str, secrets: list[str] | tuple[str, ...] = ()) -> str:
    result = str(value)
    for secret in secrets:
        if secret:
            result = result.replace(secret, "[REDACTED]")
    result = KEY_SHAPE.sub("[REDACTED]", result)
    result = re.sub(
        r"(?im)\b(OPENAI_API_KEY|CODEX_ACCESS_TOKEN)\s*=\s*[^\s]+",
        r"\1=[REDACTED]",
        result,
    )
    return result


def _auth_probe_command(codex_bin: str) -> list[str]:
    return [
        codex_bin,
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--ignore-rules",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "Reply exactly AUTH_OK.",
    ]


def prepare_auth(env: dict, codex_bin: str, codex_home: Path) -> str:
    key = env.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is required for live Codex family evaluation")
    codex_home = Path(codex_home)
    codex_home.mkdir(parents=True, exist_ok=True)
    probe = subprocess.run(
        _auth_probe_command(codex_bin),
        cwd=codex_home.parent,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=180,
    )
    if probe.returncode == 0:
        return "environment"
    diagnostic = (probe.stdout + "\n" + probe.stderr).lower()
    if not any(marker in diagnostic for marker in AUTH_FAILURE_MARKERS):
        raise RuntimeError(
            "Codex authentication probe failed for a non-authentication reason: "
            + redact((probe.stderr or probe.stdout)[-1000:], [key])
        )
    login = subprocess.run(
        [codex_bin, "login", "--with-api-key"],
        input=key + "\n",
        cwd=codex_home.parent,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=180,
    )
    if login.returncode:
        raise RuntimeError(
            "throwaway Codex login failed: "
            + redact((login.stderr or login.stdout)[-1000:], [key])
        )
    retry = subprocess.run(
        _auth_probe_command(codex_bin),
        cwd=codex_home.parent,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=180,
    )
    if retry.returncode:
        raise RuntimeError(
            "Codex remained unauthenticated after throwaway login: "
            + redact((retry.stderr or retry.stdout)[-1000:], [key])
        )
    return "throwaway-auth-json"


def prepare_current_login(env: dict, codex_bin: str) -> str:
    """Confirm that the selected real CODEX_HOME already has usable ChatGPT auth."""
    completed = subprocess.run(
        [codex_bin, "login", "status"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    diagnostic = (completed.stdout + completed.stderr).strip()
    if completed.returncode or "logged in" not in diagnostic.lower():
        raise RuntimeError(
            "existing Codex login is required for the personal smoke test: "
            + redact(diagnostic[-1000:])
        )
    return "existing-chatgpt-login"


def _expand(value, replacements: dict[str, str]):
    if isinstance(value, str):
        for token, replacement in replacements.items():
            value = value.replace(token, replacement)
        return value
    if isinstance(value, list):
        return [_expand(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item, replacements) for key, item in value.items()}
    return value


def seed_fixture(scenario: dict, env: dict, core_dir: Path) -> Path:
    """Seed project state only through deterministic ``studio.py`` commands."""
    home = Path(env["HOME"])
    studio_root = home / "Documents/Clothing-Shop-Studio"
    fixture_value = scenario.get("fixture")
    if fixture_value:
        fixture = json.loads(Path(fixture_value).read_text("utf-8"))
        commands = fixture.get("commands", [])
    else:
        commands = scenario.get("seed", [])
    replacements = {
        "${HOME}": str(home),
        "${STUDIO_ROOT}": str(studio_root),
        "${PROJECTS}": str(studio_root / "projects"),
        "${CORE_DIR}": str(Path(core_dir).resolve()),
    }
    for file_spec in fixture.get("files", []) if fixture_value else []:
        path = Path(_expand(file_spec["path"], replacements)).resolve(strict=False)
        try:
            path.relative_to(studio_root.resolve(strict=False))
        except ValueError as exc:
            raise RuntimeError("fixture file must stay inside the throwaway studio root") from exc
        path.parent.mkdir(parents=True, exist_ok=True)
        if "base64" in file_spec:
            path.write_bytes(base64.b64decode(file_spec["base64"], validate=True))
        else:
            path.write_text(file_spec.get("text", ""), encoding="utf-8")
    first_project = None
    script = Path(core_dir) / "scripts/studio.py"
    for step in commands:
        command = step.get("command")
        payload = _expand(step.get("payload", {}), replacements)
        completed = subprocess.run(
            [sys.executable, str(script), command],
            input=json.dumps(payload, ensure_ascii=False),
            cwd=home,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"fixture command produced invalid JSON: {command}") from exc
        if completed.returncode or not response.get("ok"):
            raise RuntimeError(
                f"fixture command failed: {command}: "
                + redact(completed.stdout + completed.stderr, [env.get("OPENAI_API_KEY", "")])
            )
        project_dir = response.get("data", {}).get("project_dir")
        if project_dir and first_project is None:
            first_project = Path(project_dir)
    return first_project or studio_root / "projects"


def _thread_and_turn(raw: str) -> tuple[str | None, str, list[str]]:
    thread_id = None
    messages = []
    tools = []
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        thread_id = event.get("thread_id") or thread_id
        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        kind = item.get("type", "")
        if kind in {"agent_message", "assistant_message"} and item.get("text"):
            messages.append(item["text"])
        if kind in {"command_execution", "mcp_tool_call", "tool_call"}:
            detail = item.get("command") or item.get("name") or json.dumps(item, sort_keys=True)
            tools.append(str(detail))
        message = event.get("message")
        if isinstance(message, str) and event.get("type") in {"agent_message", "assistant_message"}:
            messages.append(message)
    return thread_id, "\n".join(messages).strip(), tools


def _codex_turn_command(
    codex_bin: str,
    workspace: Path,
    prompt: str,
    thread_id: str | None,
) -> list[str]:
    if thread_id:
        return [
            codex_bin, "exec", "resume", "--skip-git-repo-check", "--ignore-user-config",
            "--ignore-rules", "--json", thread_id, prompt,
        ]
    return [
        codex_bin, "exec", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules",
        "--approve-for-me", "--color", "never", "--json", "-C", str(workspace), prompt,
    ]


def run_codex_turn(
    prompt: str,
    workspace: Path,
    env: dict,
    codex_bin: str,
    raw_path: Path,
    thread_id: str | None = None,
) -> dict:
    command = _codex_turn_command(codex_bin, workspace, prompt, thread_id)
    completed = subprocess.run(
        command,
        cwd=workspace,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=900,
    )
    raw_path.write_text(completed.stdout, encoding="utf-8")
    secret = env.get("OPENAI_API_KEY", "")
    if completed.returncode:
        raise RuntimeError(
            "Codex turn failed: " + redact((completed.stderr or completed.stdout)[-2000:], [secret])
        )
    new_thread, text, tools = _thread_and_turn(completed.stdout)
    if not text:
        raise RuntimeError("Codex turn completed without an assistant message")
    return {
        "thread_id": new_thread or thread_id,
        "text": redact(text, [secret]),
        "tools": [redact(tool, [secret]) for tool in tools],
    }


def _installed_hashes(skills_dir: Path) -> dict[str, str]:
    return {
        path.name: install_transaction.tree_hash(path)
        for path in sorted(Path(skills_dir).iterdir(), key=lambda item: item.name)
        if path.is_dir() and path.name.startswith("clothing-")
    }


def _resolve_scenario(path: Path) -> dict:
    scenario = json.loads(Path(path).read_text("utf-8"))
    fixture = scenario.get("fixture")
    if fixture:
        scenario["fixture"] = str((Path(path).parent / fixture).resolve())
    return scenario


ASSERTION_TYPES = (
    "contains", "not_contains", "tool_called", "tool_not_called",
    "exactly_one_question", "seller_notice_after_visual",
)
# Words that would let a scenario prompt itself stand in for the user's own approval
# or consent. The ``$skill`` entry token is removed before this check.
CONSENT_WORDS = re.compile(
    r"\b(yes|yep|yeah|approve[ds]?|consents?|agree[ds]?|go ahead|looks good|i confirm|confirmed?)\b",
    re.IGNORECASE,
)


def validate_scenario(scenario: dict, manifest: dict) -> None:
    for key in ("id", "skill", "query", "followups", "assertions"):
        if key not in scenario:
            raise RuntimeError(f"scenario is missing required field: {key}")
    if ("fixture" in scenario) == ("seed" in scenario):
        raise RuntimeError("scenario must declare exactly one of fixture or seed")
    names = {item["name"] for item in manifest["wrappers"]}
    if scenario["skill"] not in names:
        raise RuntimeError(f"unknown family skill: {scenario['skill']}")
    entry = "$" + scenario["skill"]
    if not re.search(re.escape(entry) + r"(?![\w-])", scenario["query"]):
        raise RuntimeError(f"scenario query must explicitly invoke {entry}")
    for prompt in [scenario["query"], *scenario["followups"]]:
        stripped = re.sub(r"\$[a-z][a-z0-9-]*", " ", prompt)
        if CONSENT_WORDS.search(stripped):
            raise RuntimeError(
                "scenario prompt must not supply approval or consent: " + prompt
            )
    for item in scenario["assertions"]:
        kind = item.get("type")
        if kind not in ASSERTION_TYPES:
            raise RuntimeError(f"unknown assertion type: {kind}")
        needed = ("visual", "notice") if kind == "seller_notice_after_visual" else (
            () if kind == "exactly_one_question" else ("value",)
        )
        for field in needed:
            if not isinstance(item.get(field), str) or not item[field]:
                raise RuntimeError(f"assertion {kind} requires field: {field}")


def _check_assertion(item: dict, turns: list[dict]) -> bool:
    kind = item["type"]
    text = "\n".join(turn["text"] for turn in turns)
    tools = "\n".join(tool for turn in turns for tool in turn["tools"])
    if kind == "contains":
        return item["value"].lower() in text.lower()
    if kind == "not_contains":
        return item["value"].lower() not in text.lower()
    if kind == "tool_called":
        return item["value"].lower() in tools.lower()
    if kind == "tool_not_called":
        return item["value"].lower() not in tools.lower()
    if kind == "exactly_one_question":
        return bool(turns) and turns[-1]["text"].count("?") == 1
    final = turns[-1]["text"] if turns else ""
    visual = re.search(item["visual"], final, re.IGNORECASE)
    notice = re.search(re.escape(item["notice"]), final, re.IGNORECASE)
    question = final.rfind("?")
    return bool(visual and notice and question >= 0
                and visual.start() < notice.start() < question)


def evaluate_assertions(scenario: dict, turns: list[dict]) -> list[dict]:
    results = []
    for item in scenario.get("assertions", []):
        passed = _check_assertion(item, turns)
        results.append({**item, "passed": passed})
    failed = [item for item in results if not item["passed"]]
    if failed:
        raise RuntimeError(
            "scenario assertion failed: "
            + "; ".join(
                f"{item['type']} {item.get('value') or item.get('visual', '')}".strip()
                for item in failed
            )
        )
    return results


def _transcript(
    scenario: dict, mechanism: str, hashes: dict, turns: list[dict], results: list[dict]
) -> str:
    lines = [
        f"# Codex family evaluation: {scenario['id']}",
        "",
        f"- Skill entry: `${scenario['skill']}`",
        f"- Authentication: `{mechanism}`",
        f"- Installed tree hashes: `{json.dumps(hashes, sort_keys=True)}`",
        "- Isolation: throwaway HOME and CODEX_HOME; only this redacted transcript is durable.",
        "",
    ]
    prompts = [scenario["query"], *scenario.get("followups", [])]
    for index, (prompt, turn) in enumerate(zip(prompts, turns), start=1):
        lines += [
            f"## Turn {index}", "", "**User:**", "",
            *[f"> {row}" for row in prompt.splitlines()], "", "**Tool calls:**", "",
            *([f"- `{tool}`" for tool in turn["tools"]] or ["- none"]),
            "", "**Assistant:**", "",
            *[f"> {row}" if row else ">" for row in turn["text"].splitlines()], "",
        ]
    lines += ["## Assertions", ""]
    for item in results:
        detail = item.get("value") or " / ".join(
            str(item[key]) for key in ("visual", "notice") if key in item
        )
        lines.append(
            f"- {'PASS' if item['passed'] else 'FAIL'} `{item['type']}`"
            + (f": {detail}" if detail else "")
        )
    if not results:
        lines.append("- none declared")
    return "\n".join(lines).rstrip() + "\n"


def run_isolated(
    scenario: dict,
    codex_bin: str,
    real_home: Path,
    *,
    auth_mode: str = "api-key",
    current_codex_home: Path | None = None,
) -> str:
    key = os.environ.get("OPENAI_API_KEY", "")
    if auth_mode == "api-key" and not key:
        raise RuntimeError("OPENAI_API_KEY is required for live Codex family evaluation")
    if auth_mode == "current-login" and current_codex_home is None:
        raise RuntimeError("current CODEX_HOME is required for the personal smoke test")
    work_parent = REPO_ROOT.parent / ".work"
    work_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="codex-family-", dir=work_parent) as folder:
        workspace = Path(folder)
        if auth_mode == "current-login":
            env, codex_home, _studio_root = personal_smoke_environment(
                workspace, Path(current_codex_home), dict(os.environ)
            )
            skills_dir = workspace / ".agents/skills"
        else:
            env, codex_home, _studio_root = evaluation_environment(workspace, dict(os.environ))
            skills_dir = codex_home / "skills"
        install = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "tools/install_skill.py"),
                "--skills-dir",
                str(skills_dir),
                "--validator",
                "fallback",
            ],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=900,
        )
        (workspace / "install.stdout").write_text(install.stdout, encoding="utf-8")
        if install.returncode:
            raise RuntimeError(
                "isolated family install failed: "
                + redact((install.stderr or install.stdout)[-2000:], [key])
            )
        mechanism = (
            prepare_current_login(env, codex_bin)
            if auth_mode == "current-login"
            else prepare_auth(env, codex_bin, codex_home)
        )
        seed_fixture(scenario, env, skills_dir / "clothing-shop-studio")
        turns = []
        thread_id = None
        prompts = [scenario["query"], *scenario.get("followups", [])]
        for index, prompt in enumerate(prompts, start=1):
            turn = run_codex_turn(
                prompt, workspace, env, codex_bin, workspace / f"turn-{index}.jsonl", thread_id
            )
            thread_id = turn["thread_id"]
            turns.append(turn)
        results = evaluate_assertions(scenario, turns)
        return _transcript(scenario, mechanism, _installed_hashes(skills_dir), turns, results)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument(
        "--auth-mode",
        choices=("api-key", "current-login"),
        default="api-key",
        help="Use an isolated API key run, or one personal smoke run with the existing Codex login.",
    )
    args = parser.parse_args(argv)
    real_home = Path.home().resolve(strict=False)
    try:
        if args.auth_mode == "api-key" and not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for live Codex family evaluation")
        scenario = _resolve_scenario(args.scenario)
        validate_scenario(scenario, load_manifest(REPO_ROOT))
        before = real_boundary_snapshot(real_home)
        current_codex_home = Path(
            os.environ.get("CODEX_HOME", str(real_home / ".codex"))
        ).expanduser().resolve(strict=False)
        transcript = run_isolated(
            scenario,
            args.codex_bin,
            real_home,
            auth_mode=args.auth_mode,
            current_codex_home=current_codex_home,
        )
        after = real_boundary_snapshot(real_home)
        if after != before:
            raise RuntimeError("real home, installed skills, or Clothing Shop Studio data changed")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(transcript, encoding="utf-8")
        print(f"wrote {args.out}")
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"evaluation failed: {redact(str(exc), [os.environ.get('OPENAI_API_KEY', '')])}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
