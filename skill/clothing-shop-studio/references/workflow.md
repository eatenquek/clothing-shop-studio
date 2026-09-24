# Workflow

Every persistent change goes through `scripts/studio.py`. Run it from the skill directory and pass one JSON object on stdin:

```bash
echo '{"project_dir": "/path/to/project"}' | python3 scripts/studio.py status
```

Each response is JSON with `ok`, `command`, `schema_version`, and either `data` or `error` (`code`, `message`, `recovery`, and optional `field`, `path`, `details`). Never edit `metadata/`, `project.yaml`, `decisions.md`, approved versions, or packs by hand; `validate` detects it.

## 1. Choose the project root (first use only)

Projects live outside the skill. `create_project` finds the root from `root` in the payload, then `CLOTHING_SHOP_STUDIO_HOME`, then `~/.config/clothing-shop-studio/config.json`. If it returns `validation_error` on `root`, ask the user once where to keep clothing projects, then call `create_project` again with `"root": "<their folder>", "remember_root": true`. A root inside the skill directory is refused.

## 2. Create or resume

- New design: `create_project` with `name`. Keep the returned `project_dir`.
- Existing design: `resume_project` with `project_dir`. It rebuilds everything from disk and returns `next_question`; do not re-ask answered fields.

Both return `next_question`. For a new project it is always the optional reference image.

## 3. Reference intake

Ask the reference question alone. If the user attaches an image, copy it into `references/user/` and run `register_file` with `origin: user_reference`, putting any text you read from it in `extracted_text`. Record the answer with `record_answer` (`field: reference_image`, value such as the registered id). If the user declines, send `"value": null`. Ask permission before sending their image to any external service.

## 4. Interview

Before asking anything, turn facts already in the brief into `record_answer` calls (use `source: inferred` with `evidence` and `confirmed: false` for anything you inferred rather than read). Then ask the returned `next_question`, one per turn, and record each reply. See [adaptive-interview.md](adaptive-interview.md).

## 5. Visual decisions

When `next_question.visual` is true, or the user must judge a look, follow [visual-options.md](visual-options.md): `generate_options` `plan`, render four labelled images, `generate_options` `register`, then show A, B, C, and W together. Record the user's choice with `record_answer` as words a factory can read (for example `field: base_color`, `value: "jet black"`, `evidence: "base_color-r01-A"`). A bare concept id is rejected as a value.

## 6. Approval

Only the user can approve. Ask whether they approve, wait for the reply, and when they clearly approve a concept or a combination, run `approve_design` with `concept_ids` and their words as `statement`. A hand-off such as "continue" or "use your recommendation" is refused as a statement; ask again plainly. This creates an immutable `designs/approved/vNNN/`. A later change is a new version.

## 7. Production masters

Build masters from client artwork, licensed type, or vector construction; see [production-pack.md](production-pack.md). Register each with `register_file` (`origin: production_master`, `construction`, `approved_version`, placement and dimensions).

## 8. Validate and export

Run `validate` with `"for_export": true`, resolve every blocker with the user, then run `export_production_pack`. Share the pack path, the production spec, and the checklist's open items.

## Status at any time

`status` returns the phase, answered fields, unconfirmed assumptions, approved versions, `next_question`, and current `blockers` from validation.
