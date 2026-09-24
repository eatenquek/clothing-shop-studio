# Release record — clothing-shop-studio presentation commands

The `feature/presentation-commands` branch is complete. Tasks 1–9, the independent task reviews, the final whole-branch audit, and the audit's final polish are all finished. Nothing is pending.

## Repository state

- **Branch:** `feature/presentation-commands`, based on `main` at `ac191fc`. `main` is unchanged.
- **Not pushed, merged, or installed.** Do any of these only when the user explicitly asks.
- **Local records (git-ignored):** task reports, the progress ledger, review packages, and eval transcripts are in `.superpowers/sdd/2026-09-25-presentation-commands/` on this machine.

## What the branch adds

| Area | Commits |
|---|---|
| Design spec and implementation plan | `9d57b9e`, `0eec6ab` |
| Presentation foundation: lazy state, image checks, rights lineage, decisions | `fcdcfa7`, `01bc4ef` |
| Standard-library PNG colour reader | `d21cbd9` |
| `extract`: garment inventory, confirmation, consent, square ≥1200 px white-background cut-outs, catalogue page | `fffbd4a`, `2837af3` |
| `create_models`: fictional AI-model library, four defaults, project-scoped candidate ids, pinning | `d20c5e9`, `00c2486` |
| `try_on`: front / three-quarter / back jobs on pinned models | `f374da8` |
| `create_listing`: Taobao-style listing concept with no prices or claims | `0262ef5`, `b60710e` |
| CLI commands and schema | `e2314c7` |
| Skill router, trigger wording, presentation docs, evals, full seller notice rule | `985b7ab`, `78f79bd` |
| Handoff refresh after Task 9 | `65224be` |
| Final polish (see below) | this commit |

**Guarantees:**
- **Nothing presentational reaches production.** Presentation images are never production-eligible and never become production masters.
- **Only your own images get used.** Outputs keep their provenance. Third-party, online, and unconfirmed sources are refused for try-on and listings, and listing cut-outs must descend from the listed approved version.
- **Models are fictional.** Real people and lookalikes are refused.
- **Listings carry no claims.** Listing concepts show only the recorded project name, grey placeholder bars, and the tag "Concept — not a live listing".
- **Seller notice.** The full Singapore seller notice is reproduced word for word after every generated visual, before the single closing question.

## Final polish from the audit

1. **Missing-project rule.** SKILL.md now tells the agent to ask the user for `project_dir` when a project is not in the workspace or the remembered project root, and not to search the home directory or unrelated folders.
2. **`try_on` reference images option.** `try_on plan` accepts an optional `reference_images_supported` (strict boolean, default `true`).
   - With `true`, the plan reports `identity_lock: "reference_image"` and sends the pinned model and garment images as inputs.
   - With `false`, it reports `"description_only"`, sends no images, and keeps the written identity anchors in the prompt.
   - A value that is not a boolean is refused before anything is written.
   - `references/presentation.md` tells the caller to pass `false` when the image tool cannot take reference images, and to warn the user that the model may drift between shots.
   - The change is backward-compatible: omitting the option behaves exactly as before.

## Verification (final commit)

- **Source suite:** 207/207 passed on Python 3.14.5 and on Python 3.9.6.
- **Tools suite:** 5/5 passed on both versions, including the public-path hygiene check.
- **Skill validator:** "Skill is valid!".
- **Whitespace:** `git diff --check` and `git diff --check main...HEAD` are clean.
- **Task 9 release checks (at `78f79bd`; the final polish does not affect them):**
  - A project made with the old `0eaf353` scripts validates clean and accepts `extract` inventory.
  - The example project's `validate --for_export` reports only `no_current_production_master`.
  - The live near-miss eval (mug background) did not trigger the skill and created no project.
  - A live listing build on a scratch approved project produced the concept without inventing images, and replied in the order visual → full seller notice → exactly one question.
- **Caches:** removed, and the tracked tree is clean.

## Remaining non-blocking limitations

- **The `presentation-listing` eval has no approved-project fixture.** It cannot reach a visual; the approved-project run was supplemental.
- **Image-based steps are tested only offline.** Extraction, model, and try-on ordering is covered by tests and docs, but no live headless run could exercise them, because that session has no image tool.
- **Possible hardening:**
  - PNG checksum checks;
  - colour-bucket precision;
  - richer cut-out metadata and error text;
  - linking photos of physical samples to a design;
  - a read-only `try_on plan`;
  - stricter matching of `register_tryon` garments to the plan;
  - a policy for mixed-garment try-ons.

## Install (only if the user asks)

```bash
rsync -a --delete --exclude '__pycache__/' --exclude '*.pyc' skill/clothing-shop-studio/ ~/.codex/skills/clothing-shop-studio/
```

For Claude Code, use `~/.claude/skills/clothing-shop-studio/` as the destination. Start a new agent session afterwards so the updated skill loads.
