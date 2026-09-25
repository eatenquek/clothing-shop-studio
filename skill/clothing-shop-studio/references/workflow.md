# Workflow

Every persistent change goes through `scripts/studio.py`. Run it from the skill directory and pass one JSON object on stdin:

```bash
echo '{"project_dir": "/path/to/project"}' | python3 scripts/studio.py status
```

Each command response, including an invalid or missing command, is JSON with `ok`, `command`, `schema_version`, and either `data` or `error` (`code`, `message`, `recovery`, and optional `field`, `path`, `details`). Parse-time failures use the schema-defined `command_error` command value; `--help` remains ordinary terminal help. Never edit `metadata/`, `project.yaml`, `decisions.md`, approved versions, or packs by hand; `validate` detects it.

## 1. The studio root (nothing to choose)

Everything lives under one canonical root, `~/Documents/Clothing-Shop-Studio`, created on first use. Never ask the user where to keep projects, and never pass a different `root`: any other root, `..` traversal, symlink escape, or project outside `projects/` is refused. Layout v2 gives each project a memory folder, `projects/<slug>/` (state and decisions only), and one folder per asset category: `references/<slug>/`, `generated/<slug>/`, `approved/<slug>/`, `production/<slug>/`, and `exports/<slug>/`. Never put assets inside `projects/<slug>/`.

## 2. Create or resume

- New design: `create_project` with `name`. Keep the returned `project_dir`.
- Existing design: `resume_project` with `project_dir`, a folder directly under `~/Documents/Clothing-Shop-Studio/projects/`. It rebuilds everything from disk and returns `next_question`; do not re-ask answered fields.

Both return `next_question`. For a new project it is always the optional reference image.

`create_project`, `resume_project`, and `status` also return `studio_root`, `asset_folders` (absolute folders), and `asset_folders_relative` (the same folders relative to the studio root). Never derive a location: save files into the absolute folder, and send the studio-relative form in payloads, for example `references/<slug>/user/photo.png`. The keys are `references_user`, `references_online`, `concepts`, `approved`, `production`, `production_masters`, `extracted`, `models`, `tryon`, and `listings`.

## 3. Reference intake

Ask the reference question alone. If the user attaches an image, copy it into the returned `asset_folders.references_user` and run `register_file` with `origin: user_reference` and `path` `<asset_folders_relative.references_user>/<file name>`, putting any text you read from it in `extracted_text` and recording its rights status. Use `third-party-inspiration-only` for an existing product unless the user explicitly confirms ownership or a licence. Record the answer with `record_answer` (`field: reference_image`, value such as the registered id). If the user declines, send `"value": null`. Ask permission before sending their image to any external service.

## 4. Interview

Before asking anything, turn facts already in the brief into `record_answer` calls (use `source: inferred` with `evidence` and `confirmed: false` for anything you inferred rather than read). Then ask the returned `next_question`, one per turn, and record each reply. See [adaptive-interview.md](adaptive-interview.md).

## 5. Visual decisions

When `next_question.visual` is true, or the user must judge a look, follow [visual-options.md](visual-options.md): `generate_options` `plan`, render four labelled images, `generate_options` `register`, then show A, B, C, and W together. Record the user's choice with `record_answer` as words a factory can read (for example `field: base_color`, `value: "jet black"`, `evidence: "base_color-r01-A"`). A bare concept id is rejected as a value.

## 6. Approval

Only the user can approve. Ask whether they approve, wait for the reply, and when they affirmatively approve or name the option they want to proceed with, run `approve_design` with `concept_ids` and their exact words as `statement`. The whole statement is checked: a hand-off, question, condition, hedge ("for now", "I guess"), refusal, negative selection, or change request anywhere in it is refused, even after "yes" (for example "Yes, but make the sleeve longer"). The error's `details` name the reason. Make any requested change first, show it, and ask again plainly. This creates an immutable `vNNN` folder inside `asset_folders.approved`, freezes the selected concept and any registered hashed review contact sheet, and snapshots the current interview answers. Any later answer change requires a new approval version before export. A legacy unhashed contact sheet cannot be approved; create and show a new option round first.

## 7. Production masters

Build masters from client artwork, licensed type, or vector construction; see [production-pack.md](production-pack.md). Register each with `register_file` (`origin: production_master`, `construction`, `approved_version`, placement and dimensions).

## 8. Validate and export

Run `validate` with `"for_export": true`, resolve every blocker with the user, then run `export_production_pack`. Share the pack path, the production spec, and the checklist's open items.

## Migrating a legacy project (`migrate_layout`)

A project created before layout v2 (`layout_version` 1, assets inside `projects/<slug>/`) still opens, resumes, and validates, but every write fails with `migration_required`. When you see that error, migrate before doing anything else:

1. **Inventory.** Run `migrate_layout` with `project_dir` and `"mode": "inventory"`. It changes nothing; it writes a hash-verified plan and returns an `inventory_id` and a `files` list with each file's `source` and `destination`.
2. **Show the mapping.** Tell the user, in plain words, which files will move from where to where (`source` to `destination`), that files are copied and verified before any old file is removed, and ask one question: may you go ahead?
3. **Apply.** Run `migrate_layout` with `"mode": "apply"`, the `inventory_id`, and `user_quote`, the user's own affirmative words. Apply only after they answer yes: a hand-off such as "continue", a hedge, a question, or your own summary is refused with `validation_error` on `user_quote`. If the project changed since the inventory, run the inventory again and show the new mapping.
4. **Resume.** After a successful apply the project validates as v2; call `resume_project` for the new `asset_folders` and carry on. An interrupted apply is safe to rerun with the same `inventory_id` and quote.

## Status at any time

`status` returns the phase, answered fields, unconfirmed assumptions, approved versions, `next_question`, and current `blockers` from validation.
