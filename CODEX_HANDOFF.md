# Release record — clothing-shop-studio

## Current personal-release gate

The user explicitly replaced the six-transcript release requirement with a pragmatic personal-skill gate. Deterministic dual-Python suites, wrapper generation, hygiene, installer checks, and independent review remain mandatory. One current-login `$clothing-new` smoke transcript at `evals/green/personal-smoke-codex.md` is the model-backed release evidence. The six `evals/family/*.json` API-key scenarios remain available as optional post-release hardening and no longer block publication.

Run the smoke only from a clean committed tree:

```bash
python3 tools/run_codex_family_eval.py evals/personal/new-project-smoke.json \
  --auth-mode current-login --out evals/green/personal-smoke-codex.md
```

`feature/presentation-commands` carries the presentation commands (`extract`, `create_models`, `try_on`, `create_listing`), the move to one canonical studio root, and the release follow-up described below. The branch is not merged. The earlier installed baseline was `dd4a007`; use `git log -1` and the installed `INSTALLED_FROM.json` for the current published revision.

## Follow-up implementation

Open-work items 1–6 below are implemented by the current branch tip. The release returns canonical asset folders from create/resume/status, documents layout v2 and `migrate_layout`, isolates evals under `.work/evals`, applies the canonical project guard to `render-options.py`, closes the installer clean-tree/PyYAML/rollback test gaps, and updates the README. Targeted integration tests pass 43/43; the complete skill suite passes 227/227 and the tools suite 12/12 on Python 3.14 and 3.9; both the official and fallback validators pass. A fresh read-only Claude review found no genuine release blockers. Item 7 remains deferred as low-priority cleanup.

## Baseline repository state (`dd4a007`)

- **Branch:** `feature/presentation-commands` at `dd4a007`, based on `main` at `ac191fc`. `main` is unchanged.
- **Pushed:** tracks `origin/feature/presentation-commands`. No pull request is open and nothing is merged.
- **Installed (Codex):** `~/.codex/skills/clothing-shop-studio/` from `dd4a007` by `tools/install_skill.py`. `INSTALLED_FROM.json` records the commit and bundle tree hash `ea60f984…0ed105`, which matches the source tree.
- **Not installed for Claude Code.** `~/.claude/skills/clothing-shop-studio/` does not exist.
- **Local records (git-ignored):** task reports, review packages, and eval transcripts are in `.superpowers/` on this machine.

## What the branch adds

| Area | Commits |
|---|---|
| Presentation design spec and plan | `9d57b9e`, `0eec6ab` |
| Presentation foundation: lazy state, image checks, rights lineage, decisions | `fcdcfa7`, `01bc4ef` |
| Standard-library PNG colour reader | `d21cbd9` |
| `extract`: garment inventory, confirmation, consent, square ≥1200 px white-background cut-outs, catalogue page | `fffbd4a`, `2837af3` |
| `create_models`: fictional AI-model library, four defaults, project-scoped candidate ids, pinning | `d20c5e9`, `00c2486` |
| `try_on`: front / three-quarter / back jobs on pinned models | `f374da8` |
| `create_listing`: Taobao-style listing concept with no prices or claims | `0262ef5`, `b60710e` |
| CLI commands and schema | `e2314c7` |
| Skill router, trigger wording, presentation docs, evals, full seller notice rule | `985b7ab`, `78f79bd` |
| Missing-project rule and description-only try-on | `835ec1d` |
| Canonical root: design spec | `433edcb` |
| Canonical root: implementation, migration, installer | `dd4a007` |

### Canonical studio root (`dd4a007`)

- **One root.** All data lives under `$HOME/Documents/Clothing-Shop-Studio`, with fixed top-level folders `source`, `projects`, `references`, `generated`, `approved`, `production`, `exports`, and `.work`. `scripts/studio_core/paths.py` is the only filesystem boundary.
- **Layout v2.** New projects use `schema_version: 2`, `layout_version: 2`, and `path_base: studio_root`. `projects/<slug>` holds only project memory. Assets live in `<category>/<slug>/…`, for example `references/<slug>/user/photo.png`.
- **Guards.** `studio.py` rejects a non-canonical `root`, `..` traversal, projects outside `projects/`, symlink escapes, and missing projects. `remember_root` is accepted but does nothing.
- **Legacy projects.** v1 projects still read and validate, but every write raises `migration_required`. `migrate_layout inventory` writes a hash-verified plan to `.work/migrations/`. `migrate_layout apply` needs an affirmative `user_quote`, copies and verifies each file, rewrites state through a `layout_migrated` event, validates, and only then removes the old files. A rerun resumes safely.
- **Reference imports** are project-scoped and reject SHA-256 duplicates.
- **Installer.** `tools/install_skill.py` needs a clean tracked tree, runs both test suites and the skill validator, stages a copy without caches, compares tree hashes of source, stage, and target, keeps a backup with rollback, and writes `INSTALLED_FROM.json`.

**Guarantees (presentation):**
- **Nothing presentational reaches production.** Presentation images are never production-eligible and never become production masters.
- **Only your own images get used.** Outputs keep their provenance. Third-party, online, and unconfirmed sources are refused for try-on and listings, and listing cut-outs must descend from the listed approved version.
- **Models are fictional.** Real people and lookalikes are refused.
- **Listings carry no claims.** Listing concepts show only the recorded project name, grey placeholder bars, and the tag "Concept — not a live listing".
- **Seller notice.** The full Singapore seller notice is reproduced word for word after every generated visual, before the single closing question.

## Verification (`dd4a007`)

- **Reviews:** a scoped code and spec review found migration blockers; they were fixed, and a separate fresh review approved the fixes.
- **Suites (tree identical to `dd4a007`):** skill 214/214 and tools 6/6 on Python 3.14.5 and on Python 3.9.6. The installer gate re-ran both suites on Python 3.14.5 at `dd4a007` and they passed.
- **Skill validator:** "Skill is valid!" from all three local copies of `quick_validate.py` (Codex, Claude plugin, Claude synced), on both Python versions, for the source and the installed copy. See the PyYAML note below.
- **CLI smoke workflow (temporary `HOME`), 22 checks, source and installed copy, both Python versions:** create, answer, resume, status, validate, default models; no absolute paths in project memory; no asset folders inside `projects/<slug>`; a non-canonical root, traversal, an outside project, and a missing project are refused; a v1 project validates, blocks writes, refuses "continue" as approval, migrates on a clear approval, moves its reference into `references/legacy/user/`, validates as v2, and accepts writes. The real studio folder was unchanged.
- **Hygiene:** `git diff --check` clean; public-path scan of `skill/` and `tools/` found nothing; the installed copy has no `__pycache__`, `.pyc`, or `.DS_Store`.

### PyYAML and the skill validator at the baseline

`quick_validate.py` imports `yaml`, and neither local Python has PyYAML. The follow-up installer now detects that specific missing dependency and uses its built-in frontmatter validator. It still preserves every other official-validator failure.

## Open work (audit after install)

Ordered by impact. Items 1–3 affect real use of the installed skill.

1. **The skill docs still describe layout v1, so an agent following them fails.** Confirmed: copying a reference into `<project_dir>/references/user/` as `references/workflow.md:24` says, then running `register_file` with `references/user/photo.png`, returns "The file does not exist." The same file at `references/<slug>/user/photo.png` registers. No command response tells the agent where the v2 folders are.
   - `SKILL.md:26` and `references/workflow.md:11-13` still describe choosing a root, `CLOTHING_SHOP_STUDIO_HOME`, the config file, and `remember_root`.
   - v1 locations: `references/workflow.md:24,36`, `references/production-pack.md:15-18`, `references/presentation.md:33`, `references/visual-options.md:44,59-67,74,80`, `references/inspiration-library.md:25-26`, `references/safety-scope.md:11`, and the `scripts/render-options.py:5` docstring.
   - Fix: rewrite these for v2, and have `create_project`, `resume_project`, and `status` return the absolute asset folders, so the agent never has to derive them. Add a test that fails when a doc names a v1 location.
2. **`tools/run_eval.py` would write eval projects into the real studio.** Line 84 sets `CLOTHING_SHOP_STUDIO_HOME`, which the CLI no longer reads, and the headless session inherits the real `HOME`. Line 106 then reads the empty `workspace/projects`. The plan's "route eval output to `.work/evals`" step was not done. Fix: add an explicit studio-root override for tests and evals (or run the session with a throwaway `HOME`), point the report at it, and add a test.
3. **`migrate_layout` is not documented for the agent.** It appears only in the command schema and the `migration_required` recovery text. Add it to `SKILL.md` and `references/workflow.md`: when to run it, showing the inventory mapping to the user, and passing their words as `user_quote`.
4. **`render-options.py` uses a weaker project guard.** Line 64 checks only that the project is outside the skill. The rest of the path handling derives the root from wherever the folder sits, so any `…/projects/<slug>` with valid state is accepted. Use the same canonical `STUDIO.require_project` check as `studio.py`. Found by reading the code; not exercised.
5. **Installer gaps.**
   - `tools/install_skill.py:94` uses `git diff --quiet`, which ignores untracked files. An untracked file under `skill/` would be installed while `INSTALLED_FROM.json` names a commit that lacks it. Check `git status --porcelain -- skill/` instead.
   - Line 98 fails on machines without PyYAML. Consider a `--python` option for the validator, or vendoring a frontmatter check.
   - `tools/test_install_skill.py` covers only the happy path. Rollback, the clean-tree gate, and the verification failure path are untested, although Task 4 of the plan lists rollback.
6. **Stale docs outside the skill.** `README.md:18-29` still installs with `rsync` and says nothing of the canonical root or migration. `README.md:31` onwards should mention `migrate_layout`.
7. **Clean-ups (low).**
   - `scripts/studio_core/config.py:10,80-121`: `ENV_HOME`, `resolve_storage_root`, and `save_storage_root` are no longer used.
   - `scripts/studio_core/paths.py:33-48`: `_component` accepts uppercase, non-ASCII letters, and `--`, but its recovery text says "lowercase letters, numbers, and single hyphens only". Tighten the check or the message.
   - `scripts/studio_core/migration.py:61-62` skips any file named `project.yaml` or `decisions.md` at any depth, and skips symlinks without reporting them. Either leaves a file behind; validation then fails safely, but the message will not say why. Restrict the name check to the project top level and report skipped symlinks in the inventory.
   - `scripts/studio_core/migration.py:193-196`: `except BaseException: raise` does nothing; keep the comment and drop the handler.

## Remaining non-blocking limitations

- **The `presentation-listing` eval has no approved-project fixture.** It cannot reach a visual; the approved-project run was supplemental.
- **Image-based steps are tested only offline.** Extraction, model, and try-on ordering is covered by tests and docs, but no live headless run could exercise them, because that session has no image tool.
- **Locking is POSIX-only** (`fcntl`), so the scripts do not run on Windows.
- **Possible hardening:** PNG checksum checks; colour-bucket precision; richer cut-out metadata and error text; linking photos of physical samples to a design; a read-only `try_on plan`; stricter matching of `register_tryon` garments to the plan; a policy for mixed-garment try-ons.

## Install

Commit first; the installer refuses an uncommitted skill tree. From the repository root:

```bash
python3 tools/install_skill.py
```

This installs to `~/.codex/skills/clothing-shop-studio/`. For Claude Code, add `--target ~/.claude/skills/clothing-shop-studio`. Start a new agent session afterwards so the updated skill loads.
