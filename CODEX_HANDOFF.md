# Codex handoff — presentation commands complete

This handoff records the final state of the `feature/presentation-commands` branch. The implementation is complete through Task 9. Do not redo Tasks 1–9.

## Repository state

- **Repo:** this repository
- **Branch:** `feature/presentation-commands`
- **Feature HEAD before this handoff refresh:** `78f79bd`
- **Base / unchanged `main`:** `ac191fc`
- **Remote state:** nothing from this workstream has been pushed or merged.
- **Installation state:** the branch has not been installed into the user's Codex skills directory. Install only when the user explicitly asks.

## Completed work

| Task | Result | Commits |
|---|---|---|
| 1 Presentation foundation and lineage | complete, independently reviewed | `fcdcfa7`, `01bc4ef` |
| 2 Standard-library PNG colour reader | complete, independently reviewed | `d21cbd9` |
| 3 Garment extraction and catalogue | complete, independently reviewed | `fffbd4a`, `2837af3` |
| 4 Fictional AI-model library and pinning | complete, independently reviewed | `d20c5e9`, `00c2486` |
| 5 AI-model try-on planning and registration | complete, independently reviewed | `f374da8` |
| 6 Listing-concept generation | complete, independently reviewed | `0262ef5`, `b60710e` |
| 7 CLI and schema wiring | complete, independently reviewed | `e2314c7` |
| 8 Router, documentation, safety notice and evals | complete, independently reviewed | `985b7ab`, `78f79bd` |
| 9 Release verification and live evals | complete | no code commit |

The branch adds `extract`, `create_models`, `try_on`, and `create_listing`. Presentation outputs remain non-production, preserve provenance, refuse unowned or unconfirmed source lineage, use fictional AI models only, omit price/size/fabric claims, and require the full Singapore seller notice word for word after every generated visual and before the single closing question.

## Verification evidence

At feature HEAD `78f79bd`:

- Source suite: **197/197 passed** on Python 3.14.5 and Python 3.9.6.
- Tools suite: **5/5 passed** on both Python versions, including public-path hygiene.
- Skill validator: **Skill is valid!**
- `git diff --check main...HEAD`: clean.
- Legacy-project compatibility: a project created with the old `0eaf353` scripts validates and accepts `extract` inventory mode.
- Example project: validation is clean; `validate --for_export` reports only `no_current_production_master`.
- Live near-miss eval: the skill did not trigger for a mug-background request and created no project.
- Supplemental approved-project listing eval: produced the listing SVG without inventing images and verified **visual → full seller notice → exactly one question**.
- Caches were removed and the tracked tree was clean before this handoff-only edit.

Task reports, the progress ledger, review package, and eval transcripts are under the git-ignored `.superpowers/sdd/2026-09-25-presentation-commands/` directory on this machine.

## Final independent audit

A fresh whole-branch Claude audit found no Critical code findings. Its only Important finding was that the old version of this file still described Tasks 5–9 as unfinished; this refresh resolves that publication blocker. The auditor otherwise found the production boundary, rights lineage, consent, duplicate-registration protection, backward compatibility, listing-copy restrictions, seller-notice rule, CLI/schema/docs alignment, and scope controls consistent.

## Non-blocking follow-ups

These were explicitly triaged as Minor or deferred, not release blockers:

- The checked-in `presentation-listing` eval starts without an approved-project fixture; the successful approved-project run is supplemental.
- Image-tool-dependent extraction, model, and try-on ordering is covered by tests and docs but was not exercised in the headless live eval.
- If a project is missing, the skill docs could state more explicitly that the agent must ask for `project_dir` instead of probing unrelated folders.
- `try_on plan` always reports `identity_lock: reference_image`; a later backward-compatible option could report `description_only` when the host image tool cannot accept reference images.
- PNG CRC checking, colour-bucket precision, richer cut-out metadata/error text, sample-photo-to-design linking, and stricter malformed-payload diagnostics remain possible hardening work.
- Listing selection is conservative for indirect try-on lineage; mixed-garment try-ons deserve a future explicit policy.

## Resume or install

No implementation work is required to publish this branch. After the five-hour usage window resets, perform a quick docs-only review of this refreshed handoff, run `git diff --check`, and commit it if it is not already committed.

Only if the user explicitly asks to install, copy `skill/clothing-shop-studio/` to `~/.codex/skills/clothing-shop-studio/` while excluding `__pycache__/` and `*.pyc`. Do not push, merge, or install without that request.

## Usage stop

Work stopped because the Codex five-hour window reached **97% used**, above the user's explicit 90% stop threshold. The weekly window was **44% used**. No reset credit was consumed.
