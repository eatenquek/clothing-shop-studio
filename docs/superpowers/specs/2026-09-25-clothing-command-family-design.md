# Clothing Shop Studio explicit command family

Date: 2026-09-25
Status: approved
Repository: `source/`
Core skill: `skill/clothing-shop-studio/`

## Goal

Expose the major Clothing Shop Studio workflows as memorable Codex `$skill-name` entrypoints while preserving one implementation, one canonical studio root, and the existing safety and approval rules.

The command family is additive. `$clothing-shop-studio` and natural-language activation continue to work. The wrappers provide explicit starting points; they do not replace the core skill, duplicate its scripts, or create a second source of project state.

## Agreed command family

| Explicit skill | User intent | Core operations it may coordinate |
|---|---|---|
| `$clothing-new` | Start a garment design | `create_project`, initial `register_file`, `record_answer` |
| `$clothing-resume` | Find and resume an existing design | `list_projects`, `resume_project`, `status`, and `migrate_layout` when required |
| `$clothing-options` | Create or revise an A/B/C/W visual round | `generate_options` plan/register/merge, `record_answer`, `render-options.py` fallback |
| `$clothing-approve` | Review a concept for possible approval | `approve_design` only after a separate affirmative user reply |
| `$clothing-production-pack` | Prepare and export a factory handoff | production-master `register_file`, export validation, `export_production_pack` |
| `$clothing-extract` | Produce garment catalogue cut-outs | `extract` inventory/confirm/consent/plan/register/decide modes |
| `$clothing-ai-models` | Create or manage fictional presentation models | `create_models` modes |
| `$clothing-try-on` | Put an owned, approved design on a fictional model | `try_on` plan/register/decide modes |
| `$clothing-listing-concept` | Build a non-live marketplace-style visual concept | `create_listing` build/decide modes |

`$clothing-status` is intentionally omitted. `$clothing-resume` runs both `resume_project` and `status`, so it already returns the project state, folders, approval versions, blockers, warnings, and `next_question`.

The longer names are deliberate boundaries:

- `production-pack` does not imply placing factory orders.
- `ai-models` does not imply language models or real-person casting.
- `listing-concept` does not imply publishing a live listing.

## Non-goals

- Replacing or renaming `$clothing-shop-studio`.
- Exposing every low-level CLI primitive as a `$` skill. `record_answer`, `register_file`, `validate`, and migration apply remain internal operations.
- Duplicating the core scripts, references, data, schemas, templates, or tests into each wrapper.
- Changing the canonical studio root or project layout.
- Adding pricing, inventory, orders, factory procurement, or storefront administration.
- Installing the explicit command family into Claude Code in this release. Claude Code continues to receive the core skill only because Codex's explicit-only invocation policy does not map cleanly to the current Claude skill format.

## Architecture

### Core and wrappers

`clothing-shop-studio` remains the only skill that owns business rules and executable code. Each wrapper contains only:

- a short `SKILL.md` defining one entry intent and its command-specific gates;
- `agents/openai.yaml` with `policy.allow_implicit_invocation: false`;
- an installation provenance marker added by the installer.

The first wrapper instruction is to locate the directory containing its own `SKILL.md`, resolve the sibling `../clothing-shop-studio/`, and read that sibling's `SKILL.md`. Its rules apply verbatim. The wrapper then reads only the relevant core reference and coordinates the relevant core CLI modes by calling the sibling core's scripts with resolved absolute paths.

Every installed family member has an `INSTALLED_FROM.json` containing `family: "clothing-shop-studio"`, `family_version`, `role` (`core` or `wrapper`), `source_commit`, and its bundle hash. The core marker also contains an integer `family_interface`. Wrapper markers contain `core_interface_min` and `core_interface_max`. The interface values and supported ranges are defined in `tools/wrappers.json`.

Before using the core, a wrapper reads the sibling core marker. It stops with installation recovery guidance when the marker is missing, names another family, reports a core interface outside its supported range, or the required core command is unavailable. Runtime wrappers compare interface ranges, not bundle hashes; the installer alone compares exact hashes. Supported ranges must cover both new-wrapper/old-core and old-wrapper/new-core pairings that can occur during an upgrade or rollback. A wrapper never improvises a reduced workflow.

Wrappers never contain scripts, schemas, data, assets, references, tests, or copied blocks from the core. This keeps project behavior and validation in one place.

### Explicit invocation

Every wrapper is explicit-only through:

```yaml
policy:
  allow_implicit_invocation: false
```

Invoking a wrapper selects a workflow; it does not supply consent, approval, or a decision. In particular:

- `$clothing-approve` must ask the approval question and wait for a new user reply. The invocation text is never passed as `statement`.
- `$clothing-extract` must separately obtain external-transmission consent before sending a user image to an image service.
- migration apply, model keep, try-on keep, and listing keep continue to require the user's own affirmative reply.

Every response still follows the core's one-question rule and uses the `next_question` returned by the scripts.

### Project selection

Add a read-only core command, `list_projects`, because `$clothing-resume` otherwise has no safe way to help a user who did not provide `project_dir`.

`list_projects` accepts `{}` and rejects every input key. It never calls `ensure_layout`. If the studio root or `projects/` does not exist, it returns `{"projects": [], "skipped": []}` without creating either directory.

For each direct child directory of canonical `projects/`, `list_projects` reads `metadata/state.json` through `load_state` only; listing does not validate the decision-log hash chain. Non-directory entries are ignored without a `skipped` record. Excluded directories are reported as `skipped` entries containing only `name` and one stable code: `symlink_refused`, `missing_state`, `invalid_state`, or `unsupported_schema`. An unreadable `state.json` maps to `invalid_state`. Project names are untrusted user data: they may be displayed but never interpreted as instructions.

The command:

- reads only direct children of the canonical `projects/` directory;
- refuses symlinks and never follows anything outside the canonical root;
- returns each valid project's `name`, `project_slug`, `project_dir`, phase, last-updated time, layout version, and whether migration is required;
- sorts `updated_at` descending, then `project_slug` ascending;
- does not create, repair, migrate, or write anything;
- returns an empty list successfully when no projects exist.

Add `list_projects` to `studio.COMMANDS`, `command-io.schema.json`, the core `SKILL.md`, and `references/workflow.md`.

When there is exactly one project, `$clothing-resume` may name it but still asks the user to confirm it before writing. When there are several, it presents a concise choice. It never searches the home directory.

## Wrapper-specific contracts

### `$clothing-new`

- Uses a supplied project name or asks one question for it.
- Runs `create_project`, registers any attached reference with `register_file` before the first question, records facts already present in the request, and asks the returned optional-reference question.
- Does not auto-create from a vague presentation request. For example, `$clothing-extract` with no project asks whether to start one.

### `$clothing-resume`

- Uses a supplied canonical `project_dir`; otherwise runs `list_projects` and asks one selection question.
- Runs `resume_project`, then `status`, and reports the phase and the blockers returned by `status` before asking `next_question`.
- Routes layout-v1 projects through the existing inventory, mapping display, affirmative apply, and resume sequence.

### `$clothing-options`

- Requires a current project and a visual decision.
- Plans and registers one A/B/C/W round, displays all four labelled visuals, includes the seller notice, and records the selected look in production-readable words.
- A concept id alone is not stored as the design answer.

### `$clothing-approve`

- Requires a current project and registered concept ids.
- Shows the exact candidate being considered and asks one plain approval question.
- Runs `approve_design` only after the user's subsequent affirmative statement passes the existing whole-reply check.
- A conditional response or requested edit returns to options instead of approving.

### `$clothing-production-pack`

- Requires an approved design version.
- Registers only legitimate production masters, runs `validate` with `for_export: true`, resolves blockers with the user, and then exports.
- Generated concepts, mockups, cut-outs, try-ons, and listing visuals remain ineligible as masters.

### Presentation wrappers

- `$clothing-extract` uses only owned/licensed inputs for selling workflows, confirms the garment inventory, obtains transmission consent, and produces cut-outs rather than OCR.
- `$clothing-ai-models` creates fictional people only and preserves identity-card and keep-decision rules.
- `$clothing-try-on` refuses shopper try-on and third-party branded garments; it uses approved owned designs and fictional models.
- `$clothing-listing-concept` creates a labelled non-live concept with no prices, sizes, or unconfirmed claims and does not publish anything.

Every newly generated visual is followed by the full Singapore seller notice before the one closing question.

### Project resolution for every wrapper

Every wrapper except `$clothing-new` follows the same project-resolution contract:

1. Use a canonical `project_dir` supplied by the user, or the project the user selected or created earlier in the current conversation. Merely appearing in a `list_projects` response does not select a project.
2. Otherwise run `list_projects` and ask one selection question. Even when only one project exists, the user confirms it before the wrapper performs a write.
3. If no project exists, ask one question about starting one. After an affirmative reply, follow the `$clothing-new` contract inline.
4. Wrappers never invoke or chain to another wrapper.
5. If a write returns `migration_required`, follow the core migration inventory, mapping display, affirmative apply, and resume steps inline, then continue the requested workflow.

## Source generation and drift control

The source repository stores all installable skills as direct children of `skill/`:

```text
skill/
  clothing-shop-studio/
  clothing-new/
  clothing-resume/
  clothing-options/
  clothing-approve/
  clothing-production-pack/
  clothing-extract/
  clothing-ai-models/
  clothing-try-on/
  clothing-listing-concept/
```

Wrapper source is generated from one reviewed manifest, `tools/wrappers.json`, by `tools/build_wrappers.py`. The manifest owns:

- `family_version`, `family_interface`, and each wrapper's supported core-interface range;
- name and description;
- display name, short description, and default prompt;
- relevant core commands, modes, helper scripts, and reference sections;
- workflow-specific gates and scope boundaries.

`build_wrappers.py --check` renders in memory and fails if committed wrapper files differ. The generator is deterministic and refuses duplicate names, unknown core commands, undocumented modes, missing helper scripts, missing reference headings, unsupported files, and implicit invocation. It imports `studio.COMMANDS` to validate command names. A separate manifest `scripts` field identifies helpers such as `scripts/render-options.py` and is validated by file existence under the core. Because presentation modes are dispatch-table keys rather than a public introspection API, every permitted mode must also appear in the cited workflow reference; the generator validates modes against those documented tokens.

Every wrapper that can generate a visual cites the seller-notice section of `references/safety-scope.md` by pointer. The notice and its URLs are never copied into wrapper files; a conformance test rejects any wrapper containing a URL from the notice.

The README command table is generated from the same manifest or checked against it, so documentation cannot silently drift from the installed family.

## Installation layout and transaction

Installed skills are flat siblings under the Codex skills directory:

```text
~/.codex/skills/
  clothing-shop-studio/
  clothing-new/
  clothing-resume/
  ...
  clothing-listing-concept/
```

The default installer publishes the complete Codex family. `--core-only` supports Claude Code and troubleshooting. The legacy `--target` option remains as a deprecated core-only form.

### Lock, recovery, and preflight

The installer's first step is to create `<skills-dir parent>/.clothing-shop-studio-install/`, take its exclusive POSIX `flock`, and recover any uncommitted journal. Nothing else, including tests, runs before recovery. After recovery and while retaining the lock, the installer:

1. Rejects uncommitted or untracked files in every family source directory and the wrapper manifest/generator.
2. Runs the complete core and tooling test suites.
3. Runs the skill validator on every family member, using the existing narrowly scoped no-PyYAML fallback.
4. Runs wrapper generation in `--check` mode and all family conformance tests.
5. Stages every member outside the scanned skills directory but on the same filesystem.
6. Hashes every source and staged member and writes one transaction journal atomically.

Read-only `--check` does not take the lock or recover anything. It reports a live or abandoned uncommitted journal as one drift item.

### Commit and rollback

- The journal, lock, staging directories, and backups live under `<skills-dir parent>/.clothing-shop-studio-install/`. This is on the same device as `<skills-dir>` by construction; family installs do not use the legacy `--work-root`.
- Each journal member records `existed_before`, target path, backup path, source hash, staged hash, and one state: `pending`, `backup_intent`, `backed_up`, `swap_intent`, `swapped`, or `verified`. The journal also has a final `committed` flag.
- Write intent atomically before each filesystem mutation, then update the member state after it. Recovery is idempotent and inspects the target, backup, marker, and hashes instead of trusting a possibly stale state alone. `existed_before` determines whether rollback restores a backup or removes a newly introduced member.
- Write the initial journal before the first swap. Install the core first, followed by wrappers, so a visible wrapper never lacks its core.
- Record the same source commit and family version in every marker. Record exact source and installed hashes for installer verification, plus the interface fields defined under Core and wrappers.
- After all swaps, re-hash every installed member and verify the markers as one family.
- On any failure, restore all prior members in reverse order and remove newly added members.
- Under the exclusive lock, startup recovery always rolls back an uncommitted journal and never rolls it forward. A committed journal is cleanup-only.
- If a rollback step fails, retain the journal, exit non-zero, and name every member left inconsistent. The next run resumes recovery before doing anything else.
- A directory named `clothing-shop-studio` whose marker contains exactly the legacy keys `source_commit` and `bundle_tree_sha256` is treated as this family's legacy core. It upgrades without `--adopt-unmarked`, and its backup is journaled.
- Refuse every other existing member directory unless its marker names this family. `--adopt-unmarked` explicitly adopts every otherwise-refused member in that run, backing up each one first.
- Obsolete members are directories whose marker names this family but whose name is absent from the current manifest. Remove them through the same journaled transaction. Never delete an unmarked directory.
- Cleanup failures after successful verification are best-effort and never roll back a verified family from a partially deleted backup.

Individual directory swaps are atomic; the complete family swap is not. Wrappers must therefore tolerate the immediately previous compatible core during the short transaction window. The journal guarantees recovery after interruption.

`--core-only` installs only `<skills-dir>/clothing-shop-studio`, where `--skills-dir` defaults to `~/.codex/skills`. Legacy `--target <path>` is equivalent to core-only installation at that exact path. Both forms refuse when the same skills directory already contains any wrapper marker naming this family, because replacing only the core could strand incompatible wrappers.

Add a read-only installer `--check` mode that reports source, installed, marker, and family-membership drift without changing files. It exits 0 only when tree hashes, family name, family version, interface ranges, and membership agree; otherwise it exits 1 and prints one deterministic line per drift item. `source_commit` remains provenance metadata and is not compared with `HEAD`, because a later evidence-only commit may leave every installable tree unchanged. Use `--skills-dir` for family installation.

## Validation and testing

### Static validation

- Run the official skill validator or the existing narrow fallback on every member.
- Require `allow_implicit_invocation: false` on every wrapper.
- Verify every wrapper name, directory name, `default_prompt`, and manifest entry agree.
- Verify wrapper descriptions distinguish their intended request from near misses.
- Verify every cited core command exists, every permitted mode appears in its cited reference, and every cited reference heading resolves.
- Verify wrappers contain only `SKILL.md` and `agents/openai.yaml` before installation markers are added.
- Verify generated wrappers and README content are current.
- Keep the existing repository-wide public-path hygiene test as a release gate.
- Assert required generated gate text from the manifest, including that approve never uses invocation text as `statement`, extract requires consent, and visual wrappers point to the seller notice without copying its URLs.

### Core behavior

Add unit and CLI tests for `list_projects`, including absent root, empty, multiple, unreadable, unsupported-schema, symlink, path-like child name, layout-v1, unknown input key, and stable-order cases. Existing project and presentation suites remain unchanged and must continue to pass on Python 3.9 and the current Python.

### Installer behavior

Use a temporary skills directory to cover:

- fresh family install and idempotent reinstall;
- upgrade from a core-only install;
- a failure at each staging, journal-write, backup, swap, hash, and marker phase;
- reverse-order rollback, rollback-step failure, journal recovery, and a process kill after every journal state;
- exclusive-lock behavior under a second concurrent installer;
- safe obsolete-member removal and refusal to delete an unmarked skill;
- explicit `--adopt-unmarked`, `--core-only`, and legacy `--target` behavior;
- cleanup failure after success;
- `--check` exit codes and deterministic drift reports.

### Behavioral evaluation

Add explicit-entry scenarios that verify:

- `$clothing-approve` never treats invocation as approval;
- `$clothing-extract` asks for transmission consent;
- `$clothing-resume` lists canonical projects or asks for `project_dir`, never searches;
- `$clothing-try-on` declines a shopper's third-party garment;
- `$clothing-listing-concept` declines price and publishing requests;
- every generated visual is followed by the seller notice and exactly one question.

Add a Codex-specific family evaluation runner rather than extending the Claude-only `tools/run_eval.py`. It creates a throwaway `HOME`, places `CODEX_HOME` underneath it, and installs the family with `--skills-dir "$CODEX_HOME/skills"`. This isolates the canonical studio root, installed family, and transcripts from the user's real home and real `~/Documents/Clothing-Shop-Studio`. The runner supplies the repository validator explicitly or uses the PyYAML-free fallback.

The runner retains an optional isolated API-key mode. It reads the key only from `OPENAI_API_KEY` in its environment and never reads, copies, or links a user's real Codex `auth.json`. It first tries `codex exec` with the environment key alone. If the installed Codex version does not accept that mechanism, the runner may pipe the key over stdin to `codex login --with-api-key`, writing `auth.json` only inside the throwaway `CODEX_HOME` under the throwaway `HOME`. It deletes the entire throwaway home before exiting, on success and on failure. The key is never written to the repository, a transcript, or any path outside the throwaway home, and the environment is redacted from transcripts.

The personal release gate instead runs one checked-in smoke scenario with `--auth-mode current-login`. This mode reuses the operator's existing Codex login without reading or copying `auth.json`, removes API-key and access-token variables from the child environment, installs the exact committed family under a throwaway workspace's `.agents/skills`, and gives garment scripts a throwaway `HOME`. It may update ordinary Codex CLI state inside the existing `CODEX_HOME`, but it must not change installed skills, the real studio folders, or the real home's top-level entries. The transcript records the authentication mode, exact core and wrapper tree hashes, prompts, tool calls, response, and assertion results.

The implementation plan's first evaluation-runner task must verify which authentication mechanism `codex exec` accepts on the installed Codex version and record the selected mechanism in the runner's module docstring.

Each scenario declares a checked-in fixture or a deterministic seed procedure composed of `studio.py` commands, all executed under the throwaway `HOME`. Fixtures cover the approved version, registered concepts, kept fictional model, and approved owned design required by later workflows. The visual-ordering scenario uses the deterministic `render-options.py` fallback when no raster image tool is available; the renderer output itself is test data, not a production master. The runner verifies actual `$name` discovery, explicit-only behavior, and sibling-core loading.

The runner takes a before-and-after snapshot of two boundaries and fails if either differs: (1) the real studio data folders `projects/`, `references/`, `generated/`, `approved/`, `production/`, and `exports/` under `~/Documents/Clothing-Shop-Studio`, recursively by path and content hash, including whether the root itself was created; and (2) the top-level entry names of the real home directory and real `~/.codex/skills`. The studio's `source/` and `.work/` folders, the explicit `--out` directory, and Codex system-temp and cache paths are excluded. The runner never modifies the real home.

Model-backed scenarios do not run inside the deterministic unit-test gate. One current-login new-project smoke transcript under `evals/green/personal-smoke-codex.md` is the personal-release behavioral gate. The six explicit-entry scenarios remain available as optional post-release hardening through the isolated API-key mode; missing `family-*.md` transcripts do not block a personal release. The deterministic suite verifies that generated wrapper text contains the manifest's required gate tokens. No core or wrapper bytes may change after the required smoke transcript is recorded without rerunning it.

## Compatibility and migration

- Existing projects require no data migration.
- Layout-v1 project migration remains unchanged and is entered through `$clothing-resume`.
- Existing `$clothing-shop-studio` invocations and natural-language activation remain valid.
- A core-only Codex installation upgrades by adding wrappers; no existing directory is renamed.
- The first published wrapper names are treated as stable; redirect wrappers are outside this release.
- Claude Code continues to install only `clothing-shop-studio` until an equivalent explicit-only policy is verified.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| A wrapper skips the core and loses shared rules | Mandatory first step to load and interface-check the sibling core; conformance tests and explicit-entry evals; scripts remain enforcement backstops |
| Invocation is mistaken for consent or approval | Wrapper prose forbids using command text as `statement` or `user_quote`; deterministic gate-token tests plus the required personal Codex smoke are the personal-release control, while the six explicit-entry evaluations remain optional hardening |
| Wrapper/core versions are mixed during installation | Core-first transaction, compatible wrappers, shared markers, journal, full-family verification and reverse rollback |
| Wrapper output drifts from source metadata | One manifest, deterministic generator, `--check`, and ownership/reference tests |
| Explicit entrypoints invite out-of-scope requests | Scope checks run before tool calls; narrow descriptions name cut-outs, fictional models, owned designs, and non-live concepts |
| Users cannot discover explicit-only skills | README and the core skill's interface prompt expose the command table; wrapper names remain stable |
| A crash leaves a discoverable staging skill | Stage and back up outside the scanned skills directory on the same filesystem |

## Release acceptance

The command family is publishable when:

1. All nine wrappers validate and are explicit-only.
2. `list_projects` satisfies its exact empty-root, payload, skip-code, ordering, schema, documentation, and canonical-boundary contract.
3. Generated wrapper files and documentation match the manifest.
4. Core, tool, family, and installer suites pass on Python 3.9 and the current Python.
5. Failure injection, process-kill, rollback-failure, recovery, and concurrent-installer tests preserve the previous family or retain an actionable recovery journal.
6. Source and installed hashes, interface ranges, family membership, and provenance markers agree for every member; installer `--check` exits 0.
7. The one-turn `$clothing-new` personal smoke has a committed Codex transcript recording the exact tested core and wrapper tree hashes, project-local `$` discovery, sibling-core loading, project creation, volunteered-fact recording, canonical-root behavior, and the one-question rule. The six explicit-entry API-key transcripts are optional post-release evidence.
8. The tested core and wrapper trees are unchanged after the required personal smoke transcript is recorded.
9. A fresh independent review finds no release blocker.
