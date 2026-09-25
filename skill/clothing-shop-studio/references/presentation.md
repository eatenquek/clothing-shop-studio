# Presentation: catalogue cut-outs, AI-model try-ons, listing concepts

These commands turn the user's own garment designs into selling visuals. They never produce prices, sizes, fabric claims, stock, orders, or storefront work, and none of their images can become a production master.

Every command takes one JSON object on stdin with `project_dir` and `mode`, for example (all outputs land in the `asset_folders` returned by `resume_project`, never inside `projects/<slug>/`):

```bash
echo '{"project_dir": "/path/to/project", "mode": "install_defaults"}' | python3 scripts/studio.py create_models
```

## Rules for every generated visual

- After each newly generated cut-out grid, model contact sheet, try-on, or listing concept, add the full Singapore seller generation notice from `references/safety-scope.md` word for word, after the visual and before the single closing question.
- Ask one question per reply. Record the user's exact words as `user_quote`.
- A keep, a confirmation, or consent needs an unqualified yes. A reply with a question, condition, hedge, or change request is refused with `decision_not_affirmative` or the command's own code. Make the change, show it again, and ask again.

## When to use

After a design is approved, or when the user gives a reference image they want turned into catalogue cut-outs. Decline shopper try-on of other brands' products and general photo editing in one line, then offer the next in-scope step.

## Consent

Before `extract` mode `plan` on a user reference, ask once: "May I send this photo to the image tool to extract the garment?" Record the reply with `extract` mode `consent` (`file_id`, `user_quote`). Without it, `plan` refuses with `transmission_consent_missing`.

## Extract

1. `inventory`: `source_id` (a registered user reference or approved design) and `items`, one per visible garment, each with `slug`, `name`, `category` (tops, jackets, bottoms, accessories, shoes), `details`, `observed`, `bbox` (fractions `[left, top, right, bottom]`), `graphic_policy` (`exact`, `mark-only`, `omit`), and `unknowns`.
2. Show the list and ask one question: is this list right?
3. `confirm`: `inventory_id`, `user_quote`. For corrections, record a new inventory and ask again.
4. `plan`: returns one job per garment with the prompt, source crop, destination, `#FFFFFF` background, and a square minimum size of 1200 px.
5. Render each job with the host image tool at its destination, then `register`: `inventory_id`, `round`, and `results` with `slug`, `path`, `renderer`, `prompt`, and `estimated_colours` (`{"primary": "#RRGGBB"}`) for JPEG files.

Then open `exports/<slug>/catalogues/catalogue.html` under `studio_root`, show the grid, add the seller notice, and ask one question. Record the answer with `decide` (`ids`, `decision`: keep, regenerate, or drop, `user_quote`).

Cut-outs from a third-party or unconfirmed reference are inspiration only. They never reach try-on or a listing.

## AI models

- On first use, run `install_defaults`. It installs four fictional models into the shared model library, `generated/_models/` in the studio root.
- For a default with a missing image, run `plan_reference` (`model_id`), render the job, then `register` with `kind: reference`.
- Custom candidates: `plan` with `range` (`gender_presentation`, `age_range`, `build`, `skin_tone`, `hair`), render the four A/B/C/W jobs, then `register` (`kind: candidates`, `round`, `identities` exactly as planned, `results`). Show the contact sheet, then `keep` (`ids`, `user_quote`).
- Never describe or use a real person, celebrity, influencer, or a lookalike, and never use a photo of a real person as a model.

## Try-on

`plan` with `design_id` or `garment_ids`, `model_id`, `poses` (`front`, `three_quarter`, `back`), and optionally `reference_images_supported` (true or false, default true).

- When the host image tool accepts reference images, send every `inputs` image to it together with the job's prompt. The plan reports `identity_lock: reference_image`.
- When it cannot, pass `reference_images_supported: false`. The plan reports `identity_lock: description_only`, each job's `inputs` is empty, and the prompt carries the written identity anchors instead. Tell the user identity is held by description only and may drift between shots.
- `register` (`round`, `model_id`, the same garment ids, `results` with `pose` and `path`). Show each try-on beside its garment and name any visible mismatch. Add the seller notice, ask one question, then `decide`.

## Listing concept

`build` with `version` (an approved version such as `v001`). Omit `design_name`: the listing always shows the project's recorded name, and any other name is refused.

- Show `listing-concept.svg`. The HTML is for the browser.
- The white-background slot takes only a kept cut-out whose lineage descends from that approved version's design. A cut-out from the user's photo of a physical sample needs explicit lineage to that design before it can fill the slot; until then, the slot stays empty.
- Try-on slots take only kept try-ons of that approved design.
- For each missing slot, offer the command that fills it.
- The concept has no prices, sizes, fabric, or other claims: only the design name, grey placeholder bars, and the tag "Concept — not a live listing". Add the seller notice, ask one question, then `decide`.

## Error codes

These codes appear in `error.details[].code`.

| Code | Meaning | Recovery |
|---|---|---|
| `inventory_unconfirmed` | The user has not confirmed the garment list, or the reply was not an unqualified yes. | Show the list, apply corrections as a new inventory, and ask again. |
| `transmission_consent_missing` | No recorded consent to send this photo to the image tool. | Ask once and record the reply with `extract` mode `consent`. |
| `garment_not_listing_eligible` | The garment traces to a third-party, online, or unconfirmed source. | Use an approved design or a cut-out from an image the user owns. |
| `model_not_kept` | The model is not in the library or has no reference image yet. | Run `install_defaults`, `plan_reference`, or keep a candidate first. |
| `real_person_model_refused` | The model description names or resembles a real person. | Describe the model by build, age range, skin tone, and hair only. |
| `decision_not_affirmative` | A keep reply was hedged, conditional, a question, or asked for changes. | Resolve the request, show the result again, and ask for a clear yes. |
