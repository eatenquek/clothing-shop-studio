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

Sync the bundle into your agent's skills directory without local Python caches:

```bash
# Codex
rsync -a --delete --exclude '__pycache__/' --exclude '*.pyc' skill/clothing-shop-studio/ ~/.codex/skills/clothing-shop-studio/
# Claude Code
rsync -a --delete --exclude '__pycache__/' --exclude '*.pyc' skill/clothing-shop-studio/ ~/.claude/skills/clothing-shop-studio/
```

Requires Python 3.9+. No third-party packages.

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
| `tools/` | Evaluation runner and reference-library importer |

## Tests

The checked-in evaluation transcripts are reproducible development evidence, not claims that every host or agent runtime was exercised live in the current release.

```bash
cd skill/clothing-shop-studio
python3 -m unittest discover -s tests -p 'test_*.py'
```

## License

[MIT](LICENSE)
