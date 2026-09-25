# Clothing Studio canonical-root implementation plan

> **Execution:** implement inline with `superpowers:executing-plans`, use test-first changes, and install only after the full verification gate passes.

**Goal:** Make `$HOME/Documents/Clothing-Shop-Studio` the sole runtime root, keep project memory under `projects/`, place every asset in its category tree, support explicit legacy migration, and install a verified generated copy.

**Architecture:** Add one `StudioPaths` boundary used by the CLI and storage modules. New state is layout v2 with studio-root-relative paths. Legacy v1 projects remain readable but all writes fail until the explicit inventory/apply migration succeeds.

**Constraints:** Python 3.9+, standard library only, no home-directory search, no persisted personal absolute paths, no writes outside the canonical root except the explicitly requested Codex skill installation.

---

## Task 1: Canonical path boundary

- Add `scripts/studio_core/paths.py` with canonical root resolution, idempotent layout creation, project guards, category containment, safe relative conversion, and `.work` routing.
- Add focused tests for layout creation, traversal/cross-project rejection, symlink escape rejection, and missing-project errors.
- Route CLI project creation and every `project_dir` command through the guard; keep `remember_root` as a no-op and reject noncanonical `root` values.

## Task 2: Layout-v2 project storage

- Change new state and manifest output to `schema_version: 2`, `layout_version: 2`, and `path_base: studio_root`.
- Create only project memory files beneath `projects/<slug>` and create asset roots through `StudioPaths`.
- Add shared helpers for resolving and serialising asset paths; update registration, concepts, approval, extraction, model, try-on, listing, validation, and production-export paths.
- Update tests and fixtures to build files at the canonical category locations and assert that manifests contain only studio-root-relative paths.

## Task 3: Legacy migration and safe imports

- Permit v1 reads/validation while raising `migration_required` before mutation.
- Add `migrate_layout inventory|apply` with a hash-verified journal under `.work/migrations`, affirmative approval, idempotent copy/resume, event-based state rewrite, post-copy validation, and removal only after successful verification.
- Extend reference import support with project-scoped destinations and SHA-256 duplicate rejection.

## Task 4: Scratch routing and installer

- Move ignored review records beneath `.work/reviews` and retain only a compatibility symlink if required by the review tooling.
- Route eval output to `.work/evals`.
- Add `tools/install_skill.py` with clean-tree/test/validator gates, cache-excluding staging, source/stage/installed tree-hash comparison, backup/rollback, and `INSTALLED_FROM.json`.
- Test staging, rollback, marker creation, cache exclusion, and temporary-home installation.

## Task 5: Verification and release

- Run the source suite, tools suite, skill validator, public-path hygiene scan, and a representative CLI workflow using a temporary `HOME`.
- Inspect the full branch diff for path leaks, mixed-layout writes, and installation safety.
- Commit the implementation, run the installer against `~/.codex/skills/clothing-shop-studio/`, then re-run validator and installed-copy smoke tests.
