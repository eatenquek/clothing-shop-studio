# Clothing Shop Studio explicit command family implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish nine explicit-only Codex `$clothing-*` workflow skills around the existing Clothing Shop Studio core, with safe project discovery, one generated source of wrapper truth, an atomic recoverable family installer, and isolated behavioral release evidence.

**Architecture:** `clothing-shop-studio` remains the only executable skill. A validated JSON manifest generates nine small sibling wrappers and the README command table. The installer treats the core and wrappers as one versioned family, stages them on the destination filesystem, records mutation intent in a recoverable journal, and verifies family markers and hashes. A separate Codex evaluation harness installs into a throwaway home and records redacted release transcripts without touching real garment data.

**Tech Stack:** Python 3.9+ standard library, JSON, Markdown, YAML text generation without a runtime YAML dependency, POSIX `fcntl.flock`, `unittest`, the existing `studio.py` JSON CLI, and local `codex exec` for the explicit release evaluation.

**Spec:** `docs/superpowers/specs/2026-09-25-clothing-command-family-design.md`

## Global Constraints

- Keep all editable source in this repository; do not edit the installed copy during implementation.
- Runtime code remains Python 3.9 compatible and standard-library only.
- The canonical runtime root remains `~/Documents/Clothing-Shop-Studio`; no home-directory search is allowed.
- The nine wrappers are Codex-only, explicit-only, and contain only `SKILL.md` plus `agents/openai.yaml` in source.
- Wrapper business rules, scripts, schemas, assets, and seller-notice text remain in the core skill.
- Invocation never counts as approval, consent, migration authorization, or a keep decision.
- Family installation is core-first, same-filesystem, journaled, rollback-safe, and refuses unrelated existing skills unless `--adopt-unmarked` is explicit.
- `--check` is read-only and compares installed content, marker interfaces, versions, and membership; it never compares `source_commit` with `HEAD`.
- Codex release evals use a throwaway `HOME` and `CODEX_HOME`; they never read the user's real `auth.json` or alter real clothing data.
- Run deterministic tests with `PYTHONDONTWRITEBYTECODE=1` on Python 3.9 and the current Python.

## Review Focus

1. **A path-like, symlinked, corrupt, unreadable, or unsupported project child must never escape discovery or cause a write.** Task 1 adds direct-child, empty-root, skip-code, stable-order, and no-write tests.
2. **A wrapper/core mismatch must stop before any project command executes.** Tasks 2 and 3 assert sibling resolution, family/interface checks, required command checks, explicit-only policy, and no copied seller URLs.
3. **A process death can occur between every journal intent and filesystem mutation.** Task 5 injects failures and restarts after each state, including rollback failures and targets that did not previously exist.
4. **An unrelated skill occupying any family name must survive by default.** Task 6 tests refusal, explicit adoption with backup, legacy-core upgrade, safe obsolete-member removal, and core-only wrapper protection.
5. **The model-backed harness must preserve evidence without leaking credentials or touching real garment data.** Tasks 7 and 8 test redaction, cleanup on success/failure, real-data snapshots, fixture isolation, and the sole durable `--out` path.

---

## File structure

| File | Responsibility |
|---|---|
| Modify `skill/clothing-shop-studio/scripts/studio.py` | Add read-only `list_projects` dispatch and payload validation. |
| Modify `skill/clothing-shop-studio/schemas/command-io.schema.json` | Admit `list_projects` responses. |
| Modify `skill/clothing-shop-studio/SKILL.md` and `references/workflow.md` | Document project discovery and wrapper routing. |
| Create `tools/wrappers.json` | Sole command-family metadata, interface ranges, commands, modes, scripts, references, gates, and UI metadata. |
| Create `tools/family_manifest.py` | Parse and validate the manifest; expose ordered core/wrapper source members. |
| Create `tools/build_wrappers.py` | Deterministically render/check wrappers and the README command block. |
| Create `skill/clothing-{new,resume,options,approve,production-pack,extract,ai-models,try-on,listing-concept}/` | Generated `SKILL.md` and `agents/openai.yaml` only. |
| Modify `README.md` | Generated explicit command table and revised family-install instructions. |
| Create `tools/install_transaction.py` | Lock, journal, staging, swap, rollback, recovery, and marker primitives. |
| Rewrite `tools/install_skill.py` | Family preflight, ownership policy, modes, check report, and CLI orchestration. |
| Create `tools/run_codex_family_eval.py` | Isolated Codex explicit-entry harness and redacted transcript writer. |
| Create `evals/family/*.json` and `evals/fixtures/family/` | Six explicit-entry scenarios and deterministic seed inputs. |
| Create `tools/test_family_manifest.py`, `tools/test_build_wrappers.py`, `tools/test_install_transaction.py`, `tools/test_codex_family_eval.py` | Focused tooling tests. |
| Modify `tools/test_install_skill.py`, `tools/test_public_hygiene.py`, `skill/clothing-shop-studio/tests/test_cli.py`, and `tests/test_structure.py` | End-to-end contracts and release gates. |

---

### Task 1: Read-only canonical project discovery

**Files:**
- Modify: `skill/clothing-shop-studio/scripts/studio.py:20-305`
- Modify: `skill/clothing-shop-studio/schemas/command-io.schema.json:9-29`
- Modify: `skill/clothing-shop-studio/SKILL.md:20-30`
- Modify: `skill/clothing-shop-studio/references/workflow.md:15-42`
- Test: `skill/clothing-shop-studio/tests/test_cli.py`

**Interfaces:**
- Produces: `command_list_projects(payload: dict) -> {"projects": list[dict], "skipped": list[dict]}`.
- Produces: CLI command `studio.py list_projects` accepting exactly `{}`.
- Each project item contains `name`, `project_slug`, `project_dir`, `phase`, `updated_at`, `layout_version`, and `migration_required`.

- [ ] **Step 1: Write failing CLI tests for the complete discovery contract**

Add a helper that invokes `list_projects`, then tests for absent root, unknown keys, direct children, descending `updated_at` with ascending-slug ties, layout-v1 migration flags, ignored files, missing/corrupt state, unsupported schema, and symlink refusal. The central assertion is:

```python
completed, response = self.run_cli("list_projects", {})
self.assertEqual(completed.returncode, 0, completed.stderr)
self.assertEqual(
    [item["project_slug"] for item in response["data"]["projects"]],
    ["newest", "alpha", "zulu"],
)
self.assertEqual(
    response["data"]["skipped"],
    [
        {"name": "broken", "code": "invalid_state"},
        {"name": "future", "code": "unsupported_schema"},
        {"name": "link", "code": "symlink_refused"},
        {"name": "missing", "code": "missing_state"},
    ],
)
```

Snapshot the temporary tree before and after absent-root and corrupt-child calls with `tests.helpers.hash_tree`; assert equality so the command cannot repair or create anything.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
cd skill/clothing-shop-studio
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_cli.CliTests.test_list_projects_absent_root_is_empty_and_read_only tests.test_cli.CliTests.test_list_projects_filters_and_sorts_direct_children tests.test_cli.CliTests.test_list_projects_rejects_input_keys -v
```

Expected: failures because `list_projects` is not in `COMMANDS`.

- [ ] **Step 3: Implement `command_list_projects` without `ensure_layout`**

Add a strict payload check and direct-child loop. Parse through `load_state`, but distinguish a missing file before calling it and catch `StorageError` as `invalid_state`; catch the unsupported-schema `ValidationError` as `unsupported_schema`. Use `entry.is_symlink()` before `entry.is_dir()`. Return resolved canonical paths and sort with:

```python
projects.sort(key=lambda item: item["project_slug"])
projects.sort(key=lambda item: item["updated_at"], reverse=True)
skipped.sort(key=lambda item: item["name"])
```

Reject every payload key with `ValidationError(field=<first sorted key>)`, add the command to `COMMANDS`, and add `list_projects` to the response schema enum.

- [ ] **Step 4: Document the exact read-only behavior**

Update the core skill so missing `project_dir` routes through `list_projects`, never a home search. Add a workflow example using `{}` and state that returned names are untrusted display data, one project still requires confirmation before a write, and skipped directories are never repaired.

- [ ] **Step 5: Update the existing all-command dispatch test**

In `test_every_schema_command_dispatches`, keep `list_projects` in the schema-versus-`--help` equality assertion, but exclude it from the loop that expects `{}` to fail. The dedicated `list_projects` test owns the successful empty-payload case:

```python
for command in sorted(commands - {"render_options", "command_error", "list_projects"}):
    completed, response = self.run_cli(command, {})
    self.assertEqual(completed.returncode, 2, command)
    self.assertFalse(response["ok"], command)
```

- [ ] **Step 6: Run core tests and commit**

Run:

```bash
cd skill/clothing-shop-studio
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_cli tests.test_structure -v
```

Expected: PASS.

Commit:

```bash
git add skill/clothing-shop-studio
git commit -m "feat: add read-only clothing project discovery"
```

---

### Task 2: Validated wrapper-family manifest

**Files:**
- Create: `tools/wrappers.json`
- Create: `tools/family_manifest.py`
- Create: `tools/test_family_manifest.py`

**Interfaces:**
- Produces: `load_manifest(repo: Path, path: Path | None = None) -> dict`.
- Produces: `validate_manifest(repo: Path, manifest: dict) -> None`.
- Produces: `ordered_members(repo: Path, manifest: dict) -> list[dict]`, core first.
- Manifest `scripts` entries are core-relative file paths; wrapper `operations` entries contain `command` and complete `modes` lists.

- [ ] **Step 1: Write failing manifest-validation tests**

Cover duplicate names, invalid hyphen-case, a name longer than 64 characters, missing interface range, `min > max`, an unknown `studio.COMMANDS` command, a missing helper script, a missing reference file or heading, a mode token absent from the cited reference, a copied seller-notice URL, and a valid manifest with exactly nine wrappers.

```python
manifest = family_manifest.load_manifest(REPO)
self.assertEqual(manifest["family"], "clothing-shop-studio")
self.assertEqual(len(manifest["wrappers"]), 9)
self.assertEqual(
    [member["name"] for member in family_manifest.ordered_members(REPO, manifest)],
    ["clothing-shop-studio"] + [item["name"] for item in manifest["wrappers"]],
)
```

- [ ] **Step 2: Run the new suite and verify RED**

Run `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tools.test_family_manifest -v`.

Expected: import failure because `family_manifest.py` does not exist.

- [ ] **Step 3: Implement the manifest loader and validator**

Load `studio.py` with `importlib.util.spec_from_file_location` after temporarily adding the core `scripts/` directory to `sys.path`, then compare operation names against `studio.COMMANDS`. Normalize Markdown headings by stripping inline-code backticks before comparing them with manifest section names. A mode is documented only when a backtick span in a cited Markdown section either equals the mode or contains the exact JSON fragment `"mode": "<mode>"`; unrelated prose substrings do not count. Use one `RuntimeError` per invalid manifest with the wrapper name and field in the message.

The committed manifest must encode these exact members:

```json
{
  "family": "clothing-shop-studio",
  "family_version": 1,
  "family_interface": 1,
  "core": "clothing-shop-studio",
  "wrappers": [
    {"name": "clothing-new"},
    {"name": "clothing-resume"},
    {"name": "clothing-options"},
    {"name": "clothing-approve"},
    {"name": "clothing-production-pack"},
    {"name": "clothing-extract"},
    {"name": "clothing-ai-models"},
    {"name": "clothing-try-on"},
    {"name": "clothing-listing-concept"}
  ]
}
```

Each wrapper object contains the approved spec's description, UI fields, `core_interface_min: 1`, `core_interface_max: 1`, reference headings, gate sentences, and these exact operation sets:

| Wrapper | Operations and modes | Helper scripts |
|---|---|---|
| `clothing-new` | `create_project`, `register_file`, `record_answer` | none |
| `clothing-resume` | `list_projects`, `resume_project`, `status`, `migrate_layout` (`inventory`, `apply`) | none |
| `clothing-options` | `generate_options` (`plan`, `register`, `merge`), `record_answer` | `scripts/render-options.py` |
| `clothing-approve` | `approve_design` | none |
| `clothing-production-pack` | `register_file`, `validate`, `export_production_pack` | none |
| `clothing-extract` | `extract` (`inventory`, `confirm`, `consent`, `plan`, `register`, `decide`) | none |
| `clothing-ai-models` | `create_models` (`install_defaults`, `plan`, `plan_reference`, `register`, `keep`) | none |
| `clothing-try-on` | `try_on` (`plan`, `register`, `decide`) | none |
| `clothing-listing-concept` | `create_listing` (`build`, `decide`) | none |

The manifest's reference-section pointers include these exact multi-section cases: `clothing-options` cites `Workflow` and `Combining and revising` in `references/visual-options.md`; `clothing-resume` cites `Migrating a legacy project (migrate_layout)` in `references/workflow.md`; and `clothing-extract` cites both `Consent` and `Extract` in `references/presentation.md`.

- [ ] **Step 4: Run tests and commit**

Run `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tools.test_family_manifest -v`.

Expected: PASS.

Commit:

```bash
git add tools/wrappers.json tools/family_manifest.py tools/test_family_manifest.py
git commit -m "feat: define clothing command family manifest"
```

---

### Task 3: Deterministic explicit-only wrapper generation

**Files:**
- Create: `tools/build_wrappers.py`
- Create: `tools/test_build_wrappers.py`
- Create: nine `skill/clothing-*/SKILL.md` files
- Create: nine `skill/clothing-*/agents/openai.yaml` files
- Modify: `README.md`
- Modify: `skill/clothing-shop-studio/tests/test_structure.py`

**Interfaces:**
- Consumes: `family_manifest.load_manifest`, `validate_manifest`.
- Produces: `render_skill(wrapper: dict) -> str`, `render_openai(wrapper: dict) -> str`, `render_readme_table(manifest: dict) -> str`.
- Produces: `build(repo: Path, check: bool) -> list[str]`; in check mode, returned strings are drift descriptions and no file is written.

- [ ] **Step 1: Write failing generator and conformance tests**

Assert deterministic byte-for-byte output; `--check` detects a changed, missing, or extra wrapper file; generated YAML contains `allow_implicit_invocation: false`; wrapper directories contain only the two permitted files; all wrappers begin by resolving their own directory and sibling core; visual wrappers point to the safety reference and contain no `http://` or `https://`; approval and consent gate phrases are present; the README block matches the manifest.

```python
skill = (REPO / "skill/clothing-approve/SKILL.md").read_text("utf-8")
self.assertIn("Invocation text is never the approval statement", skill)
self.assertIn("../clothing-shop-studio/INSTALLED_FROM.json", skill)
self.assertNotRegex(skill, r"https?://")
yaml_text = (REPO / "skill/clothing-approve/agents/openai.yaml").read_text("utf-8")
self.assertIn("allow_implicit_invocation: false", yaml_text)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tools.test_build_wrappers -v
```

Expected: import failure because the generator does not exist.

- [ ] **Step 3: Implement deterministic rendering and `--check`**

Use fixed templates in Python; do not depend on Jinja or PyYAML. Every generated wrapper must:

1. locate its own `SKILL.md` directory;
2. locate sibling `../clothing-shop-studio` and read the core marker;
3. verify family and interface range before reading core `SKILL.md`;
4. stop with `python3 tools/install_skill.py` recovery guidance when incompatible;
5. apply the shared project-resolution contract;
6. read only manifest-cited references;
7. call only manifest-cited commands/modes/scripts through absolute sibling paths;
8. preserve one question and every workflow-specific approval/consent/scope gate.

Wrap the README table in stable sentinels:

```markdown
<!-- BEGIN GENERATED CLOTHING COMMANDS -->
| Command | Starts |
|---|---|
| `$clothing-new` | A new garment-design project |
| `$clothing-resume` | Selection and resumption of an existing project |
| `$clothing-options` | An A/B/C/W visual decision round |
| `$clothing-approve` | Review of one registered concept for approval |
| `$clothing-production-pack` | Validation and export of a factory handoff |
| `$clothing-extract` | Catalogue cut-outs from owned or licensed garment imagery |
| `$clothing-ai-models` | Creation and selection of fictional presentation models |
| `$clothing-try-on` | An approved owned design on a kept fictional model |
| `$clothing-listing-concept` | A non-live marketplace-style listing visual |
<!-- END GENERATED CLOTHING COMMANDS -->
```

`--check` compares expected relative paths and bytes, rejects unsupported files inside wrapper directories, and prints deterministic drift lines.

- [ ] **Step 4: Generate source wrappers and inspect all nine**

Run:

```bash
python3 tools/build_wrappers.py
python3 tools/build_wrappers.py --check
```

Expected: the first command writes the wrappers/table; the second exits 0 with no drift.

- [ ] **Step 5: Run conformance tests and commit**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tools.test_build_wrappers -v
(cd skill/clothing-shop-studio && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_structure -v)
```

Commit:

```bash
git add tools/build_wrappers.py tools/test_build_wrappers.py README.md skill/clothing-*
git commit -m "feat: generate explicit clothing workflow skills"
```

---

### Task 4: Family inventory, provenance markers, preflight, and read-only drift checking

**Files:**
- Modify: `tools/install_skill.py`
- Modify: `tools/test_install_skill.py`
- Create: `tools/test_install_family.py`

**Interfaces:**
- Consumes: `family_manifest.ordered_members` and `build_wrappers.build(check=True)`.
- Produces: `member_marker(member: dict, source_hash: str, source_commit: str, manifest: dict) -> dict`.
- Produces: `family_drift(repo: Path, skills_dir: Path, manifest: dict) -> list[str]`.
- CLI adds `--skills-dir`, `--core-only`, `--check`, `--adopt-unmarked`, and the explicit validator selection `--validator fallback`; explicit `--target` remains deprecated core-only mode.

- [ ] **Step 1: Write failing marker, preflight, and check-mode tests**

Cover core and wrapper marker fields, legacy two-key core recognition, source dirtiness in any wrapper/manifest/generator, validation of every member, source-versus-installed tree drift, family/interface/version/membership drift, deterministic line order, `--check` exit 0/1, no lock acquisition, and reporting an uncommitted journal as a single drift item.

```python
self.assertEqual(
    marker,
    {
        "bundle_tree_sha256": "a" * 64,
        "family": "clothing-shop-studio",
        "family_interface": 1,
        "family_version": 1,
        "role": "core",
        "source_commit": "abc123",
    },
)
```

For a wrapper, replace `family_interface` with `core_interface_min` and `core_interface_max`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tools.test_install_skill tools.test_install_family -v`.

Expected: failures for missing family functions and flags.

- [ ] **Step 3: Refactor verification around ordered family members**

Keep `tree_hash`, cache exclusions, fallback skill validation, and old single-bundle helpers until their callers are migrated. The parser accepts either a validator path or the literal `fallback`; the latter calls `validate_skill_without_pyyaml` directly and is covered by a test. Add preflight that:

- checks Git status for the core, every generated wrapper, `tools/wrappers.json`, `tools/family_manifest.py`, and `tools/build_wrappers.py`;
- runs the complete core and tools suites once;
- validates each family member with the supplied validator or narrow fallback;
- runs wrapper generation in check mode;
- returns one source commit for every marker.

Do not compare marker `source_commit` with `HEAD` in `family_drift`.

- [ ] **Step 4: Implement read-only `--check`**

Resolve `--skills-dir` without creating it. Compare expected source hashes with installed hashes excluding `INSTALLED_FROM.json`, validate marker family/role/version/interface fields, report missing/extra family members, and detect a live or abandoned uncommitted journal by content only. Print sorted lines as `DRIFT <member-or-family>: <reason>` and exit 1 when the list is non-empty.

- [ ] **Step 5: Run tests and commit**

Run `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tools.test_install_skill tools.test_install_family -v`.

Expected: PASS.

Commit:

```bash
git add tools/install_skill.py tools/test_install_skill.py tools/test_install_family.py
git commit -m "feat: verify clothing skill family installs"
```

---

### Task 5: Same-filesystem transaction journal, rollback, and crash recovery

**Files:**
- Create: `tools/install_transaction.py`
- Create: `tools/test_install_transaction.py`
- Modify: `tools/install_skill.py`

**Interfaces:**
- Produces: `transaction_root(skills_dir: Path) -> Path` as `<skills-dir parent>/.clothing-shop-studio-install`.
- Produces: `install_lock(skills_dir: Path)` context manager using exclusive `fcntl.flock`.
- Produces: `recover_uncommitted(skills_dir: Path) -> None`.
- Produces: `stage_members(members: list[dict], skills_dir: Path, marker_factory) -> list[dict]`.
- Produces: `commit_staged(skills_dir: Path, staged: list[dict], obsolete: list[dict]) -> dict`.

- [ ] **Step 1: Write the state-machine and failure-injection tests**

The journal fixture must contain:

```json
{
  "committed": false,
  "family": "clothing-shop-studio",
  "members": [{
    "name": "clothing-shop-studio",
    "existed_before": true,
    "target": "<skills-dir>/clothing-shop-studio",
    "backup": "<skills-dir parent>/.clothing-shop-studio-install/backups/<run-id>/clothing-shop-studio",
    "source_hash": "0000000000000000000000000000000000000000000000000000000000000000",
    "staged_hash": "0000000000000000000000000000000000000000000000000000000000000000",
    "state": "pending"
  }]
}
```

The test replaces the angle-bracket example values with paths derived from `tempfile.TemporaryDirectory()`; no literal machine or system-temporary path is committed.

Inject an exception before and after every `backup_intent`, backup move, `backed_up`, `swap_intent`, swap, `swapped`, verification, and `verified` transition. Restart recovery and assert the old family is restored, newly introduced members are removed, the journal remains only when recovery itself fails, and recovery is idempotent when called twice.

- [ ] **Step 2: Run the transaction suite and verify RED**

Run `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tools.test_install_transaction -v`.

Expected: import failure because the transaction module does not exist.

- [ ] **Step 3: Implement atomic journal writes and recovery-first locking**

Write JSON to a sibling temporary file, `flush`, `os.fsync`, then `os.replace`. Create the transaction root and acquire the lock before preflight. Record intent before every mutation. Recovery must inspect target and backup existence plus hashes rather than trust `state`; `existed_before` chooses restore versus removal. A committed journal is cleanup-only. A rollback failure preserves the journal and raises an error listing inconsistent members.

Stage under `transaction_root(skills_dir) / "staging" / run_id`, back up under `transaction_root(skills_dir) / "backups" / run_id`, and ensure both resolve to the same device as `skills_dir.parent` before swapping.

- [ ] **Step 4: Add concurrency and process-kill coverage**

Spawn one helper process that holds the flock and assert a second installer blocks until release. For each journal state, run a subprocess that exits with `os._exit(91)` at the injection point, then run recovery and compare the complete skills tree with the pre-install snapshot.

- [ ] **Step 5: Integrate transaction entry ordering**

In normal install mode, perform these calls in order: create transaction root → lock → recover → preflight → stage → initial journal → core swap → wrapper swaps → obsolete-member removals → full-family verification → mark committed → best-effort cleanup. `--check` bypasses the lock and all writes.

- [ ] **Step 6: Run tests and commit**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tools.test_install_transaction tools.test_install_skill tools.test_install_family -v
```

Expected: PASS.

Commit:

```bash
git add tools/install_transaction.py tools/test_install_transaction.py tools/install_skill.py
git commit -m "feat: add recoverable clothing family installation"
```

---

### Task 6: Ownership, upgrade compatibility, core-only modes, and complete installer matrix

**Files:**
- Modify: `tools/install_skill.py`
- Modify: `tools/test_install_family.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 5 transaction primitives.
- Produces: default full-family install at `--skills-dir`; core-only install at `<skills-dir>/clothing-shop-studio`; legacy exact-path core install with `--target`.

- [ ] **Step 1: Add failing ownership and mode tests**

Cover fresh family install, idempotent reinstall, upgrade of a core with exactly the two legacy marker keys, refusal of any other unmarked collision, `--adopt-unmarked` backing up every collision, removal of marked obsolete family members, preservation of unmarked obsolete names, core-only refusal when wrappers exist, legacy exact `--target`, cleanup failure after verification, and final `--check` success.

Assert the install order begins with `clothing-shop-studio` and that a failure after any wrapper restores the entire prior family.

- [ ] **Step 2: Run the installer matrix and verify RED**

Run `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tools.test_install_family -v`.

Expected: failures in unimplemented ownership/mode branches.

- [ ] **Step 3: Implement ownership classification and obsolete-member handling**

Classify targets as `absent`, `family`, `legacy_core`, or `unmarked`. Accept `legacy_core` only for directory name `clothing-shop-studio` with a marker containing exactly `source_commit` and `bundle_tree_sha256`. Refuse `unmarked` unless `--adopt-unmarked`; when adopted, include it in the transaction like any other prior member. Discover obsolete members only by markers whose `family` equals `clothing-shop-studio`.

- [ ] **Step 4: Implement CLI mode validation**

The parser must reject incompatible combinations before mutation:

- default: install the full family into `--skills-dir`;
- `--core-only`: install only `<skills-dir>/clothing-shop-studio`;
- `--target PATH`: deprecated core-only at exactly `PATH`;
- `--check`: read-only family comparison, incompatible with `--target`, `--core-only`, and `--adopt-unmarked`;
- both core-only forms refuse when sibling family wrapper markers exist.

Family mode ignores the legacy `--work-root`; retain the argument only long enough to emit a deprecation error when combined with family mode.

- [ ] **Step 5: Update installation documentation and run all deterministic tests**

Document default family install, `--core-only`, Claude Code's exact `--target`, `--check`, ownership refusal, and the fact that installation is generated from committed source only.

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s skill/clothing-shop-studio/tests -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools -p 'test_*.py'
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/install_skill.py tools/test_install_family.py README.md
git commit -m "feat: complete clothing family installer modes"
```

---

### Task 7: Isolated Codex family evaluation harness

**Files:**
- Create: `tools/run_codex_family_eval.py`
- Create: `tools/test_codex_family_eval.py`
- Create: `evals/fixtures/family/approved-owned-project.json`
- Create: `evals/fixtures/family/presentation-project.json`

**Interfaces:**
- Produces: `real_boundary_snapshot(home: Path) -> dict`.
- Produces: `evaluation_environment(workspace: Path, base_env: dict) -> tuple[dict, Path, Path]`.
- Produces: `prepare_auth(env: dict, codex_bin: str, codex_home: Path) -> str`, returning `environment` or `throwaway-auth-json`.
- Produces: `seed_fixture(scenario: dict, env: dict, core_dir: Path) -> Path`.
- CLI: `run_codex_family_eval.py SCENARIO --out DIR [--codex-bin codex]`.

- [ ] **Step 1: Probe the installed Codex authentication mechanism without writing user state**

In a temporary `HOME` and nested `CODEX_HOME`, run a single harmless `codex exec` probe with an existing `OPENAI_API_KEY`. If environment-only auth fails specifically as unauthenticated, pipe the key to `codex login --with-api-key` with stdin and retry. Record the selected mechanism in the module docstring before continuing implementation. Do not print the key or subprocess environment.

- [ ] **Step 2: Write failing isolation, redaction, cleanup, and auth tests**

Mock subprocesses so tests cover missing key, environment success, throwaway-login fallback, login failure, transcript redaction, cleanup on success and exception, sole durable `--out` writes, and unchanged real-boundary snapshots. The snapshot must hash the six real studio data folders recursively and collect only top-level names for real `HOME` and real `~/.codex/skills`.

```python
before = run_codex_family_eval.real_boundary_snapshot(real_home)
with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
    run_codex_family_eval.main([str(scenario), "--out", str(out)])
self.assertEqual(run_codex_family_eval.real_boundary_snapshot(real_home), before)
self.assertFalse(any(path.name == "auth.json" for path in real_home.rglob("auth.json")))
```

- [ ] **Step 3: Run the focused suite and verify RED**

Run `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tools.test_codex_family_eval -v`.

Expected: import failure because the harness does not exist.

- [ ] **Step 4: Implement the throwaway environment and installer call**

Use `tempfile.TemporaryDirectory`; set `HOME=<temp>/home` and `CODEX_HOME=<temp>/home/.codex`; install with:

```bash
python3 tools/install_skill.py --skills-dir "$CODEX_HOME/skills" --validator fallback
```

Seed projects only through deterministic `studio.py` commands under the throwaway home. Write raw command output inside the temporary workspace, redact environment/key-shaped text, add core/wrapper tree hashes and auth mechanism, then copy only the final Markdown/JSON evidence to `--out` before the context manager removes the temporary directory.

- [ ] **Step 5: Implement boundary verification and commit**

Take the real-boundary snapshot before workspace creation and after cleanup. Exclude `source/`, `.work/`, explicit `--out`, system temp, and caches by never walking them. Raise before publishing evidence if the snapshots differ.

Run `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tools.test_codex_family_eval -v`.

Expected: PASS.

Commit:

```bash
git add tools/run_codex_family_eval.py tools/test_codex_family_eval.py evals/fixtures/family
git commit -m "feat: add isolated Codex family evaluation"
```

---

### Task 8: Six explicit-entry scenarios and release transcript gate

**Files:**
- Create: `evals/family/approve-requires-reply.json`
- Create: `evals/family/extract-requires-consent.json`
- Create: `evals/family/resume-lists-canonical-projects.json`
- Create: `evals/family/try-on-refuses-shopper-garment.json`
- Create: `evals/family/listing-refuses-price-publish.json`
- Create: `evals/family/visual-notice-one-question.json`
- Modify: `tools/test_codex_family_eval.py`
- Create after live run: `evals/green/family-*.md`

**Interfaces:**
- Consumes: Task 7 harness and deterministic fixtures.
- Produces: six redacted transcripts with tested tree hashes and explicit pass/fail assertions.

- [ ] **Step 1: Add scenario-schema and assertion tests**

Each scenario has `id`, `skill`, `query`, `fixture` or `seed`, `followups`, and `assertions`. Restrict `skill` to the nine manifest names. Implement assertion types `contains`, `not_contains`, `tool_called`, `tool_not_called`, `exactly_one_question`, and `seller_notice_after_visual`.

- [ ] **Step 2: Author the six scenarios with deterministic setup**

Use invocation text that cannot itself satisfy approval or consent. The resume fixture contains two projects with fixed timestamps. The try-on scenario names a third-party branded shopper garment. The listing scenario asks for a live price and immediate publish. The visual scenario uses `render-options.py` to produce A/B/C/W files and checks seller-notice ordering plus one terminal question.

- [ ] **Step 3: Run deterministic scenario tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tools.test_codex_family_eval tools.test_build_wrappers -v
```

Expected: PASS without invoking a model.

- [ ] **Step 4: Run all six live Codex evaluations**

With `OPENAI_API_KEY` already present, run each scenario into `evals/green/`. A scenario failure is release-blocking. Confirm each transcript records `$` discovery, sibling-core load, the expected gate/refusal, auth mechanism, core hash, and all wrapper hashes.

- [ ] **Step 5: Freeze evidence and prove source trees did not change afterward**

Run `python3 tools/build_wrappers.py --check` and compare transcript hashes to current `tree_hash` values. Do not change any core or wrapper file after this point; documentation/evidence-only commits remain allowed.

- [ ] **Step 6: Commit scenarios and evidence**

```bash
git add evals/family evals/green tools/test_codex_family_eval.py
git commit -m "test: record explicit clothing command workflows"
```

---

### Task 9: Dual-Python release validation and publishability review

**Files:**
- Modify only if a deterministic release blocker is found; any fix returns to the owning task's RED/GREEN cycle and requires regenerating Task 8 evidence when core or wrapper trees change.

**Interfaces:**
- Produces: a clean branch with installer `--check` success and no uncommitted generated drift.

- [ ] **Step 1: Run current-Python gates**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s skill/clothing-shop-studio/tests -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools -p 'test_*.py'
python3 tools/build_wrappers.py --check
python3 tools/test_public_hygiene.py
```

Expected: all pass.

- [ ] **Step 2: Run Python 3.9 gates**

First verify the machine's dedicated compatibility interpreter:

```bash
/usr/bin/python3 --version
```

Expected: `Python 3.9.x`. If it is not 3.9, stop and report that the required compatibility interpreter is unavailable; do not substitute a different minor version.

```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest discover -s skill/clothing-shop-studio/tests -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest discover -s tools -p 'test_*.py'
```

Expected: all pass.

- [ ] **Step 3: Exercise fresh, upgrade, rollback, recovery, and check workflows in temporary skills directories**

Run the installer tests' subprocess fixtures, then a manual temporary-directory smoke install. Verify only the temporary directory; do not install into `~/.codex/skills` as part of this plan.

- [ ] **Step 4: Verify Git and generated-source hygiene**

```bash
git diff --check
git status --short
git log --oneline --decorate -12
```

Expected: no uncommitted changes, no generated drift, and task commits present.

- [ ] **Step 5: Request an independent whole-branch blocker review**

The reviewer compares the branch to the approved spec and reports only release blockers with file-and-line evidence. Implement only verified blockers through the owning task's tests. If core or wrapper bytes change, rerun both complete suites and all six live evaluations before the final verdict.

- [ ] **Step 6: Declare the branch publishable or not publishable**

PUBLISHABLE requires all nine spec acceptance items, including exact transcript hashes and a clean `--check`. Do not push, merge, or install unless the user separately requests that action after reviewing the completed implementation.
