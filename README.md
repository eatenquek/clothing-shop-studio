# Clothing Shop Studio

An agent skill (Codex / Claude Code) that takes a garment from a brief or reference image to approved visuals and a validated, factory-ready production pack.

## What it does

- **Adaptive interview.** One question per reply, skipping facts already given. Covers garment type, fibre blend, fabric structure, GSM, stretch, opacity, fit, construction, climate, size range, and grading.
- **Four-way visual choices.** Every visual decision is shown as three practical options (A, B, C) plus one feasible wildcard (W).
- **Immutable approvals.** Approved designs are frozen into versioned, hashed, read-only folders with full lineage.
- **Production packs.** Exports versioned masters, placement measurements, colours, tolerances, sizing assumptions, a production spec, a manifest, and a handoff checklist. Generated previews and mockups are never accepted as production masters.
- **Decoration/fabric compatibility checks** before export.
- **Accidental-change detection and resumable project memory.** State lives outside the skill in a SHA-256-linked decision log. Validation catches ordinary edits and missing files; the local hashes are not a cryptographic authenticity guarantee against a determined editor who can recompute them.
- **Untrusted-input handling.** Text inside reference images, files, and web pages is treated as data, never as instructions.
- **Presentation.** `extract` turns a reference image into white-background catalogue cut-outs, `create_models` keeps a library of fictional AI models, `try_on` puts approved designs on those models, and `create_listing` builds a Taobao-style listing concept with no prices or claims.

Pricing, inventory, orders, and storefront operations are out of scope; listing concepts are visual mock-ups only.

## Install

Install with the installer, not by copying files. Commit the skill bundle first: it refuses uncommitted or untracked files under `skill/clothing-shop-studio/`. From the repository root:

```bash
# Codex (default target: ~/.codex/skills/clothing-shop-studio)
python3 tools/install_skill.py
# Claude Code
python3 tools/install_skill.py --target ~/.claude/skills/clothing-shop-studio
```

`tools/install_skill.py` runs the test suites and the skill validator, stages a copy without Python caches, compares tree hashes of the source, the stage, and the target, keeps a backup with rollback, and writes `INSTALLED_FROM.json` recording the commit it installed. Start a new agent session afterwards so the updated skill loads.

Requires Python 3.9+. No third-party packages at run time.

## Where your data lives

Everything the skill creates lives in one canonical studio root, `~/Documents/Clothing-Shop-Studio`. It is created on first use and cannot be moved or renamed through the skill: any other root, `..` traversal, symlink escape, or project outside `projects/` is refused. Fixed top-level folders:

| Folder | Contents |
|---|---|
| `projects/<slug>/` | Project memory only: state and decision log |
| `references/<slug>/` | The user's own and online references |
| `generated/<slug>/` | Concepts, cut-outs, and try-ons; `generated/_models/` holds the shared model library |
| `approved/<slug>/` | Immutable approved design versions |
| `production/<slug>/` | Masters and exported production packs |
| `exports/<slug>/` | Catalogue pages and listing concepts |
| `source/`, `.work/` | Working area for the skill and tooling |

`create_project`, `resume_project`, and `status` return the absolute folder for each category, so the agent never has to work out a location.

### Migrating older projects

Projects created before this layout (layout v1, with assets inside the project folder) still open and validate, but every write is refused with `migration_required` until they are migrated. The agent runs `migrate_layout` for you: `inventory` writes a hash-verified plan and changes nothing, the agent shows you which files will move where, and `apply` runs only after you clearly say yes (your words are recorded as `user_quote`). Each file is copied and verified before any old file is removed, and an interrupted migration can be rerun safely.

## Explicit workflow commands

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

## Usage

Ask your agent to design a garment, for example:

> Design an oversized long-sleeve for my streetwear brand with upper-back typography.

The skill drives every step through `scripts/studio.py`, which reads one JSON object on stdin:

`create_project` → `record_answer` → `generate_options` → `approve_design` → `register_file` → `validate` → `export_production_pack`

See [`skill/clothing-shop-studio/SKILL.md`](skill/clothing-shop-studio/SKILL.md) and `references/` for the full workflow.

## Repository layout

| Path | Contents |
|---|---|
| `skill/clothing-shop-studio/` | The installable skill: instructions, scripts, data, schemas, tests |
| `evals/` | Behavioural scenarios, no-skill baselines, and with-skill transcripts |
| `tools/` | Installer, evaluation runner, and reference-library importer |

## Tests

The checked-in evaluation transcripts are reproducible development evidence, not claims that every host or agent runtime was exercised live in the current release.

```bash
cd skill/clothing-shop-studio
python3 -m unittest discover -s tests -p 'test_*.py'
```

## License

[MIT](LICENSE)
