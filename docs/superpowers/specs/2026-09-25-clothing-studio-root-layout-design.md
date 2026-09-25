# Clothing Studio canonical-root design

## Status

Approved direction: keep every editable source file, garment project, reference, generated image, approved design, production file, export, and scratch artifact under one Clothing Studio root. The only external copy is the installed Codex skill.

This specification defines the storage contract and the migration needed to move the current project-relative layout to that contract.

## Goals

- Use `$HOME/Documents/Clothing-Shop-Studio` as the canonical studio root. On the target machine this resolves to the user-specified absolute path.
- Keep the Git repository at `source/` and preserve its existing history.
- Store project memory separately from large visual and production assets.
- Resolve stored paths relative to the studio root. Never persist personal absolute paths.
- Create missing top-level folders when a studio command starts.
- Search for projects only in `projects/`.
- Require an inventoried, verified migration before moving legacy project files.
- Keep tests hermetic and compatible with Python 3.9+.
- Install only a generated copy of the skill at `~/.codex/skills/clothing-shop-studio/` after verification and explicit user authorization.

## Canonical layout

```text
Clothing-Shop-Studio/
├── source/                         Git repository: skill, tests, plans and tools
├── projects/<slug>/                project memory and manifests only
│   ├── metadata/
│   ├── project.yaml
│   └── decisions.md
├── references/<slug>/
│   ├── user/
│   └── online/
├── generated/<slug>/
│   ├── concepts/
│   ├── extracted/
│   ├── models/pinned/
│   └── tryon/
├── generated/_models/              shared fictional model library
├── approved/<slug>/<version>/      immutable approved designs and review evidence
├── production/<slug>/
│   ├── masters/
│   └── packs/<version>/
├── exports/<slug>/
│   ├── catalogues/
│   ├── listings/
│   └── deliveries/
└── .work/
    ├── reviews/
    ├── evals/
    ├── migrations/
    ├── install-staging/
    └── install-backups/
```

Each category owns one subdirectory per project slug. Shared fictional model assets live under `generated/_models`; `projects/` therefore contains projects only.

`.work/` contains disposable or resumable operational artifacts. Project manifests never point to `.work/`. A process may delete its own verified scratch directory, but it must not clear unrelated runs.

## Root and path API

Add `studio_core/paths.py` as the only module that knows the physical layout.

`StudioPaths` provides:

- `default_root(home=None)`: returns `<home>/Documents/Clothing-Shop-Studio`.
- `ensure_layout()`: creates the eight required top-level folders. It rejects a root or category that resolves through a symlink outside the studio root.
- `projects_dir` and `project(slug)`: resolve only `projects/<slug>`. Missing projects raise a structured error whose recovery asks the user for the project location. No command scans the home directory or unrelated folders.
- `asset_dir(category, slug)`: accepts only `references`, `generated`, `approved`, `production`, or `exports` and rejects traversal and cross-project paths.
- `from_relative(path, category=None, slug=None)` and `to_relative(path)`: convert between absolute paths and POSIX studio-root-relative paths after containment checks.
- `work_dir(purpose, run_id)`: resolves scratch storage below `.work/`.

The CLI builds one `StudioPaths` per request. The production default has no configurable arbitrary root. Tests set a temporary `HOME`, making the default resolve to a temporary `Documents/Clothing-Shop-Studio` without a production-only override.

The existing `root` field on `create_project` remains accepted only when it resolves to the canonical `projects/` directory. Any other value receives a structured validation error. `remember_root` becomes unnecessary and is accepted as a no-op for legacy callers. The application stops reading or writing `~/.config/clothing-shop-studio/config.json`.

Every CLI command that accepts `project_dir` verifies that it resolves to `projects/<slug>`. Core functions may take an injected `StudioPaths` in tests, but production callers must use the CLI guard.

## Project state and manifests

New projects use `layout_version: 2` and `path_base: studio_root` in state and manifest output. File entries store paths such as:

```text
references/kiki-kaka/user/reference-001.png
generated/kiki-kaka/concepts/back-typography/r01/a.png
approved/kiki-kaka/v001/v001-concept-a.png
production/kiki-kaka/masters/back-artwork.svg
exports/kiki-kaka/listings/v001/listing-concept.svg
```

No state, event, manifest, catalogue, or handoff stores an absolute path. Paths inside a self-contained production pack remain relative to that pack.

All file registration and validation routes through `StudioPaths`. Replace the independent containment logic in `config.resolve_inside`, `options._resolve_generated`, `render-options.py`, presentation helpers, approval, listing, validation, and export rather than maintaining parallel rules.

## Write destinations

- User and online references: `references/<slug>/user|online/`.
- Option renders, extractions, pinned models, and try-ons: the matching folder under `generated/<slug>/`.
- Shared fictional models: `generated/_models/<model-id>/`.
- Approved versions: `approved/<slug>/<version>/`.
- Production masters and factory packs: `production/<slug>/`.
- Catalogue HTML, listing SVG/HTML, presentations, and delivery bundles: `exports/<slug>/`.
- Review packages, eval workspaces, migration journals, installation staging, and temporary conversions: `.work/`.

Writers create their category and slug directories on demand. They stage multi-file operations under `.work/` or the destination filesystem and use atomic replacement after verification.

## Legacy compatibility

A project without `layout_version: 2` is a legacy project. Current projects store paths relative to the project and may contain `references/`, `concepts/`, `designs/`, and `production/` beneath `projects/<slug>`.

The new code may read and validate legacy projects with their existing path base. Any command that would write to a legacy project refuses with a structured `migration_required` error. This prevents a mixed layout.

Add a `migrate_layout` command with two modes:

1. `inventory` reads one named project, computes every source path, destination path, size, and SHA-256 hash, and writes a migration plan to `.work/migrations/`. It returns the mapping for the user to review. It never moves files.
2. `apply` requires the inventory id and the user's affirmative quote. It holds the project lock, copies each file to its destination, verifies hashes, rewrites file paths and layout metadata through a hash-chained `layout_migrated` event, re-validates the project, and only then removes old copies. An interrupted run resumes from its journal without duplicating files.

The migration restores read-only permissions on approved versions and production packs. It never migrates a project that is outside `projects/`; the user must first approve moving that project into the canonical root.

No garment projects currently exist under the new `projects/` directory, so this release does not need to migrate live project data. The migration command protects future imports and any legacy project the user later places there.

## Reference imports and deduplication

`import_references.py` writes only to `references/<slug>/user|online/`. Before copying, it checks registered SHA-256 hashes for that project and refuses a duplicate. It never creates a second copy merely because the source path differs.

Text inside imported references remains untrusted data. Rights and origin metadata continue to control production and listing eligibility.

## Repository scratch migration

Move the current ignored `.superpowers/sdd/` records to `.work/reviews/sdd/`. If Superpowers tooling requires the repository-local `.superpowers` path, keep a repository symlink that points to the canonical `.work/reviews/superpowers` directory; do not keep a second copy.

Top-level eval scenario sources remain the development source of truth. The skill-bundle copies are generated and must match byte for byte; the public-hygiene test enforces that relationship. This is an intentional build copy, not arbitrary project duplication.

## Installation

Add `tools/install_skill.py` for the one permitted external copy.

The installer:

1. Requires a clean tracked tree and a passing source suite, tools suite, and skill validator.
2. Copies `skill/clothing-shop-studio/` to `.work/install-staging/clothing-shop-studio/`, excluding caches.
3. Validates the staged skill and compares its tree hash with the source bundle.
4. Backs up an existing installation under `.work/install-backups/`, then atomically replaces `~/.codex/skills/clothing-shop-studio/`.
5. Writes `INSTALLED_FROM.json` with the source commit and bundle tree hash.
6. Re-validates the installed copy and removes the backup only after success. A failure restores the backup.

The installer never writes to `~/.claude/skills/`. Documentation may mention that destination only as an alternative platform, not an additional installed copy. The installer does not use destructive synchronization against an unmarked arbitrary target.

## Tests

Use tests-first implementation. Set `HOME` to a temporary directory in CLI subprocess tests and create the canonical layout beneath it.

Required coverage:

- all eight folders are created idempotently;
- new projects place only memory under `projects/<slug>` and assets under category roots;
- every stored path is studio-root-relative and resolves to the expected category and slug;
- absolute paths, `..`, cross-project paths, and symlink escapes are rejected;
- missing-project lookup does not enumerate other home directories;
- legacy projects remain readable and refuse writes before migration;
- migration inventory is non-mutating and contains verified source-to-destination hashes;
- migration apply requires affirmative approval, resumes safely, removes old files only after verification, and preserves immutable permissions;
- shared models no longer appear under `projects/`;
- reference import deduplication works by hash;
- `.work/` paths never enter project manifests;
- install staging, verification, rollback, marker generation, and cache exclusion work in a temporary home;
- tracked fixtures contain no personal absolute paths;
- the existing source and tools suites still pass on Python 3.14 and 3.9.

## Migration of the source repository

The approved repository move has been completed:

```text
old: Desktop/CS2100_Assg1/clothing-shop-studio-development/
new: Documents/Clothing-Shop-Studio/source/
```

The move preserved `.git`, branch `feature/presentation-commands`, commit `835ec1d`, and the configured remote. The old directory no longer exists.

## Non-goals

- No pricing, inventory, orders, fulfilment, or storefront management.
- No automatic discovery or migration of projects elsewhere on the machine.
- No second editable source tree.
- No installation before the implementation and verification gates pass.
