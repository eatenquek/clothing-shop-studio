# Codex handoff — presentation commands (Tasks 5–9 remaining)

Read this whole file before you touch anything, then continue from **Task 5**. Do not redo Tasks 1–4.

## Where things stand

- **Repo:** this directory, branch `feature/presentation-commands`. It has not been pushed, and `main` is at `ac191fc`.
- **Spec (approved by the user):** `docs/superpowers/specs/2026-09-25-presentation-commands-design.md`
- **Plan (approved by the user):** `docs/superpowers/plans/2026-09-25-presentation-commands.md`
  - The plan contains the full code and tests for every task.
  - Follow it task by task, test-first, and commit after each task.
- **Ledger and scratch (git-ignored):** `.superpowers/sdd/2026-09-25-presentation-commands/`
  - `progress.md` is the ledger.
  - `task-N-brief.md` and `task-N-report.md` hold each finished task's brief and report.
  - Append your own progress lines to `progress.md`.

| Task | Status | Commits |
|---|---|---|
| 1 Presentation core | done, reviewed | `fcdcfa7`, `01bc4ef` |
| 2 PNG colour reader | done, reviewed | `d21cbd9` |
| 3 `extract` | done, reviewed | `fffbd4a`, `2837af3` |
| 4 AI model library | done (self-reviewed; awaiting Codex review) | see `progress.md` |
| 5 `try_on` | **next** | — |
| 6 `create_listing` | todo | — |
| 7 CLI commands and schema | todo | — |
| 8 Router, docs, trigger description, evals | todo | — |
| 9 Release verification | todo | — |

Test status after Task 4: 163/163 passing on Python 3.14 and on `/usr/bin/python3` (3.9.6).

## Differences from the plan text (already on the branch)

These came from review rulings. Build on them; don't revert them.

1. **`validation.master_problems` names the ancestor's actual origin** in its generated-ancestor message. The error codes are unchanged.
2. **`presentation.image_size(path) -> tuple[int, int] | None`** reads PNG and JPEG dimensions from the headers only. It never raises.
3. **`extract.MIN_EXTRACT_SIZE = 1200`.**
   - `register_extraction` refuses images that are not square or are smaller than this.
   - `plan_extraction` uses the same constant for `min_size`.
   - `tests/test_extract.py` lowers the constant with a `small_extract()` `mock.patch` decorator, so its 4×4 fixtures still work.
   - The white background is not pixel-checked. It stays a prompt requirement plus user review. This was a deliberate ruling: a pure-Python decode of a 1200 px image is slow.
4. **`require_decision(quote, cues=APPROVAL_CUES)`** has a default for `cues`.

Tasks 5 and 6 import `GARMENT` and `ITEM` from `tests.test_extract`. Those still exist. Task 5 registers its garment fixtures directly, not through `register_extraction`, so the size rule does not affect it.

## Rules that bind all remaining work

These are copied from the plan's Global Constraints.

- **Python and tests:**
  - Python 3.9+ and the standard library only. Every new module starts with `from __future__ import annotations`.
  - Run tests from `skill/clothing-shop-studio`:
    - `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests`
    - The same command with `/usr/bin/python3`, for Python 3.9.
- **No network, no pricing, no size charts.** No network calls or third-party packages. No pricing, size chart, inventory, order, or storefront output anywhere.
- **Presentation files:**
  - Every presentation file is `production_eligible: false`.
  - New state keys are created only when first used. Do not change `store._state_template`, or older projects will be flagged as tampered.
- **Refusals:** every refusal is a `ValidationError` or `UnsafePathError`. Presentation refusals carry `details=[{"code": ..., "message": ...}]`, using the six codes listed in the plan.
- **User decisions** go through `interview.decision_problem` (a check on the whole reply): `CONFIRMATION_CUES` for confirmations and consent, `APPROVAL_CUES` for keep decisions.
- **Models and listings:**
  - Try-on uses fictional AI models only.
  - Listing concepts carry only the design name, grey placeholder bars, and the tag `Concept — not a live listing`.
- **Seller notice:** it goes after each generated visual and before the single closing question. This is covered by the Task 8 docs and evals.
- **Commits:** end each commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push or merge without the user's explicit request.
- **No personal paths:** keep machine-specific paths such as home or temp directories out of tracked files. `tools/test_public_hygiene.py` enforces this.

## Known issues to handle while building Tasks 5–9

- **`models.register_models`:** a non-integer `round` is now refused as a `ValidationError` on `round` (done in Task 4). `install_defaults` also skips stray files such as `.DS_Store` in `assets/models`.
- **Deferred minor notes** (the final review should decide which to fix):
  - PNG chunk CRCs are not verified.
  - Fixed-grid colour buckets can split a real secondary colour.
  - An inventory's `observed` and `unknowns` fields are not carried into the registered cut-out.
  - The "estimated colour" error is generic when a valid PNG cannot be decoded.

## How to finish

1. **Tasks 5–8:** implement them exactly as the plan's task sections describe, with tests first. After each task, re-read your own diff against that task's section, then commit.
2. **Task 9, release verification:**
   - Run both suites on both Pythons.
   - Run the skill validator: `quick_validate.py` from the skill-creator skill, which needs PyYAML on `PYTHONPATH`.
   - Run `git diff --check`.
   - Check that a project created with `0eaf353` still validates and accepts `extract` mode `inventory`.
   - Check that the example project's `validate --for_export` still reports only `no_current_production_master`.
   - Do one live headless run of `tools/run_eval.py` on `presentation-listing` and one near-miss eval.
3. **Final whole-branch review:** review `git diff ac191fc..HEAD` in full, triage the deferred minor notes above, then fix and re-test.
4. **Clean up:** remove all `__pycache__` folders, then report to the user with the commit SHAs and exact test evidence. Install into `~/.codex/skills/clothing-shop-studio`, using `rsync --delete` and excluding `__pycache__/` and `*.pyc`, only when the user asks.

## User preferences for this workstream

- Keep going between tasks without check-ins, and decide small ambiguities yourself. Record each decision in `progress.md` as `Ruling: <decision> — <why> — <cost if wrong>`.
- Stop when any usage limit reaches 90% used. Before stopping, write an updated handoff file.
- Report outcomes plainly, including anything that failed or was skipped.
