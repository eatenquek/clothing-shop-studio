# Presentation commands: extract, AI models, try-on, listing concept

Date: 2026-09-25
Status: draft for review
Skill: `skill/clothing-shop-studio`

## Goal

The skill currently goes from brief to approved design to factory pack. The seller also needs visuals for selling their own designs. This spec adds a presentation layer after approval:

1. `extract`: pull garments out of any reference image into clean catalogue cut-outs, in the style of the Sheesh wardrobe catalogue.
2. `create_models`: a library of AI-generated models (not real people), with four defaults shipped.
3. `try_on`: put an approved design or cut-out on a library model, from the front, at 3/4, or from the back.
4. `create_listing`: one Taobao-style listing concept page that shows how the product would look for sale.

Agreed with the user:

- The purpose is selling the user's own designs.
- Images come from the agent host's own image tool. There is no new API, GPU, or third-party Python package.
- No pricing and no size chart. The listing is a visual concept only and carries no unconfirmed facts.
- `extract` accepts any reference image.
- The user confirms the garment list before any extraction image is made.
- White backgrounds; transparent PNGs are not needed.
- Four default AI models. Poses are front, 3/4, and back.
- Everything lives in the existing skill (approach 1), with the trigger-description risk mitigated.

## Non-goals (v1)

- Pricing, cost, size charts, inventory, orders, and storefront or marketplace administration. These stay out of scope.
- Real-person models: stock photos, friends, or hired models. These can be added later with release records.
- Hosted APIs (fal.ai, Replicate), local GPU models, and background-removal libraries.
- Transparent PNG output, video, social or ad creatives, and multi-garment outfit styling.
- Copying or shipping the Sheesh screenshot. It is a layout reference only.

## References used

- **Extract Clothing skill** (tandpfun gist) and the `tandpfun/wardrobe` / `davidmarinangeli/wardrobe` projects (MIT). Their pipeline is to inventory garments, crop each with padding, write an evidence-based prompt ("Reconstruct ONLY the complete empty [item]…"), and QA each result against its source crop. They follow three rules:
  - Prefer omission over invention.
  - Text and logos follow one of three policies: exact, mark-only, or omit.
  - Unknown details go in the manifest, not the image.
- **`prithivMLmods/QIE-2511-Extract-Outfit`** (Apache 2.0). Its flat-mockup prompt shape informs ours. It also warns that a cropped input extracts only the visible region.
- **`motiful/product-shots`** (MIT). It locks identity anchors (face, hair, skin, build, lighting, camera) so a model stays the same person across angles. It also enforces main-image rules as prompt fields before rendering.
- **Taobao listing conventions.** A 1:1 main gallery at 800 px or larger (1200 recommended), at least one white-background image, and a mobile detail column about 750 px wide.
- **Rejected as engines:** OutfitAnyone (CC BY-NC 4.0) and CatVTON, IDM-VTON, and OOTDiffusion (non-commercial licences). They are workflow references only. Free stock people photos (Unsplash, Pexels) are also rejected because they carry no model releases.

## Architecture

The new commands use the existing `generate_options` three-step pattern:

1. **Plan.** The script validates the inputs and returns each image job: prompt, input images, destination path, and output requirements.
2. **Render.** The agent runs the host image tool and saves each file to its destination.
3. **Register.** The script hashes each file, records its origin and parents, and appends one event to `decisions.jsonl`.

New `studio.py` commands:

| Command | Modes |
|---|---|
| `extract` | `inventory`, `plan`, `register` |
| `create_models` | `install_defaults`, `plan`, `register`, `keep` |
| `try_on` | `plan`, `register`, `decide` |
| `create_listing` | `build`, `decide` |

New modules keep each unit small:

- `studio_core/presentation.py`: shared plan and register helpers, lineage and eligibility checks.
- `studio_core/extract.py`: inventory manifest, extraction jobs, catalogue page.
- `studio_core/models.py`: model identity cards, defaults, keep decisions.
- `studio_core/tryon.py`: try-on jobs and decisions.
- `studio_core/listing.py`: listing concept page and SVG preview.
- `studio_core/pngcolour.py`: stdlib-only PNG decoding and dominant-colour estimation.

Storage:

- Per project: `presentation/extracted/<source-id>/rNN/`, `presentation/tryon/rNN/`, and `presentation/listing/vNNN/`.
- Model library: `<projects root>/_models/<model-id>/`, holding `identity.json` and `front.png`, plus optional `three-quarter.png` and `back.png`. It is shared by all projects under the same root. Each project records the model id and hash it used, so a later library change cannot silently alter an old try-on.
- Shipped defaults: `assets/models/<id>/identity.json`, plus reference images when they exist. `install_defaults` copies them into the library once. The installed skill is never written to.

New file origins. All are `production_eligible: false` and are treated as generated content by the master-lineage checks:

- `extracted_garment`, parents `[source reference or approved design]`.
- `synthetic_model`, no parents, flagged `ai_generated_person: true`.
- `tryon_image`, parents `[garment or approved design, synthetic model]`.
- `listing_concept`, parents are every image placed in it.

`_generated_ancestors` and every rule that refuses generated artwork as a production master must treat these four origins exactly like `generated_concept`. The design-to-factory flow is otherwise unchanged: the interview, approvals, masters, and export.

## `extract`

1. **`inventory`**
   - Input: `project_dir`, `source_id` (a registered `user_reference` or approved-design file), and an optional `target` naming the garment the user wants.
   - The agent looks at the image and sends one manifest entry per visible garment:
     - `slug`, `name`, and `category` (tops, jackets, bottoms, accessories, or shoes);
     - `details` tags, for example `casual` or `retro`;
     - `observed` notes;
     - `bbox` as fractions of the image;
     - `graphic_policy` (`exact`, `mark-only`, or `omit`);
     - an `unknowns` list.
   - The script validates the manifest and returns it for the user to confirm.
2. **The user confirms the list.** The agent shows the list as one question. The reply is recorded as `user_quote` and must pass the whole-reply affirmative check. Corrections are applied to the manifest and the list is shown again.
3. **`plan`**
   - This mode requires a confirmed manifest, and requires `external_transmission_consent: true` on the source when the source is a user reference. That consent is asked once per reference and recorded with `register_file`.
   - Each garment gets one job:
     - a prompt in the gist style that reconstructs only that empty garment, excludes the wearer, body, underlayers, props, and scene, prefers omission over invention, and applies the recorded graphic policy;
     - `background: #FFFFFF`, square, at least 1200 px;
     - destination `presentation/extracted/<source-id>/rNN/<slug>.png`.
4. **`register`**
   - The script hashes each file and records it as `extracted_garment`.
   - For PNG files it computes `primary_colour` and an optional `secondary_colour` with `pngcolour.py`, ignoring near-white background pixels. A secondary colour is reported only when it covers at least 15% of the garment pixels and is visibly distinct from the primary.
   - For other formats the agent may send estimates, which are stored with `colour_source: estimated`.
   - It renders `presentation/extracted/catalogue.html`: a grid of every cut-out in the project with category tabs. Selecting one shows its name, category, colour swatches with hex, and detail tags. All text is HTML-escaped. The page is static, needs no network, and uses relative image paths.
5. **Eligibility.** A cut-out is `listing_eligible` only when every source in its lineage is an approved design or a `user_reference` with `rights: user-owned-or-licensed`. Cut-outs from third-party or unconfirmed images are inspiration only.

## `create_models` and the four defaults

- **Identity card fields:**
  - `id`, `display_name`, `gender_presentation`, `age_range`, `build`, `height_impression`;
  - `skin_tone`, `hair`, `face_description`, `neutral_outfit`;
  - `lighting`, `camera`, `background`;
  - `ai_generated_person: true`, `renderer`, `prompt`.
- **`plan`** takes the user's range (gender presentation, age range, build, skin tone, hair) and returns four A/B/C/W candidate jobs. Registered candidates are shown as a contact sheet.
- **`keep`** needs the user's affirmative quote. It copies kept candidates into `_models/` with their identity card.
- **Refusals:**
  - prompts or names that refer to a real person, celebrity, or influencer;
  - registering a photo of a real person as a model.
  The real-person check is a keyword backstop plus an explicit instruction; the rule in `SKILL.md` is the primary control.
- **Defaults:** four varied identity cards ship in `assets/models/`. Reference images ship only if they were generated at build time with a recorded renderer. Otherwise `install_defaults` installs the cards and marks the images as needed, and the first `try_on` plans their generation.

## `try_on`

- **`plan`**
  - Input: `garment_ids` (listing-eligible cut-outs) or an approved design id, plus `model_id` and `poses` (a subset of `front`, `three_quarter`, `back`).
  - The script refuses ineligible garments, and models that are not kept `synthetic_model` entries.
  - Each job sends the model's reference image and identity card together with the garment image. The prompt locks every identity anchor and requires the garment exactly as shown: colour, print, placement, and scale, with no invented logos, pockets, or trims.
- **`register`** records each file as a `tryon_image` with parents garment and model, `label: AI try-on`, and the pose.
- **`decide`** records keep, regenerate, or drop for each image, using the user's quote.
  - Keep requires an affirmative reply.
  - Regenerate plans a new round.
  - Before asking, the agent shows each try-on beside its cut-out and names any visible mismatch.
- If the host tool cannot take reference images, `plan` returns `identity_lock: description_only`, and the agent warns that the model may drift between shots.

## `create_listing`

- **`build`**
  - Input: an approved design version.
  - The script collects only kept, listing-eligible cut-outs and try-ons.
  - It writes `presentation/listing/vNNN/listing-concept.html` and `listing-concept.svg`. It generates no new images.
- **Main gallery:** five 1:1 slots:
  1. a hero on-model shot;
  2. the white-background cut-out;
  3. front try-on;
  4. 3/4 try-on;
  5. back try-on.
- **Detail column** (750 px): a full on-model shot, then close-ups of the cut-out made by SVG/CSS framing only, never by generating new pixels.
- **Text:** only the design name. Grey placeholder bars stand where the title, price, and specs would go. A small "Concept — not a live listing" tag sits on the mock, never on product images.
- **Missing images:** a missing slot shows an empty labelled frame. The response offers the command that fills it.
- **`decide`** records whether the user keeps the concept or asks for changes. A revision builds `vNNN+1`, and earlier versions stay.

## Trigger-description mitigation

- **Description.** One sentence rooted in the user's own garment designs:
  > Use when designing the user's own garments, apparel graphics, merch, production specs, or factory handoff files, or when turning those designs into catalogue cut-outs, AI-model try-ons, or listing-concept visuals; load it before asking any design-intake question.
- **Router.** `SKILL.md` gains one core rule and one "Read when needed" line pointing to a new `references/presentation.md`. It stays short.
- **Scope rule.** It still declines pricing, quotes, inventory, orders, storefront administration, shopper try-on of other brands' products, and general photo editing, each with a one-line redirect.
- **New evals** in `evals/scenarios/`, run with the existing `tools/run_eval.py`:
  - Positive: turn my approved tee into a listing concept; extract the jacket from my sample photo; put design v001 on a model.
  - Near-miss negatives that must not produce a design or presentation flow:
    - a shopper who wants to see a store's jacket on themselves;
    - removing the background from a mug photo;
    - writing a Shopee description with a price.
  - Both kinds must also follow the one-question and seller-notice ordering rules.

## Safety and rights

- **Seller notice.** It follows every newly generated cut-out, model candidate, try-on, and listing concept, and comes before the single closing question.
- **Consent.** Passing a user's image to the host image tool counts as external transmission. It needs recorded consent per reference, and the check is enforced in code.
- **People in source photos.** People may appear in `extract` source photos. The output must contain only the garment, and try-on uses only synthetic models.
- **Rights lineage.** Third-party or unconfirmed lineage blocks listing use. All presentation outputs are blocked as production masters.
- **Reference text.** Text inside images stays data. Inventory `observed` notes and names are stored as untrusted text and escaped in every page.
- **User decisions** (the inventory confirmation, model keep, try-on keep, and listing keep) use the existing whole-reply affirmative check.

## Error handling

- Every refusal is a structured `ValidationError` with `field` and `recovery`, as in the existing CLI.
- The new error codes are documented in `references/presentation.md`:
  - `inventory_unconfirmed`
  - `transmission_consent_missing`
  - `garment_not_listing_eligible`
  - `model_not_kept`
  - `real_person_model_refused`
  - `listing_slot_missing` (a warning)
- Register refuses files outside the planned destination, missing or empty files, invalid PNG or JPEG signatures, and byte-identical duplicates within one job set.

## Testing

- **Unit tests per module, test-first:**
  - manifest validation;
  - job planning;
  - eligibility and lineage;
  - consent enforcement;
  - identity-card validation;
  - real-person refusal backstop;
  - listing slot assembly;
  - HTML escaping of every user-supplied string;
  - PNG decoding (8-bit greyscale, RGB, RGBA, and palette, via stdlib-encoded fixtures);
  - dominant-colour results;
  - a rule that presentation origins are refused as production masters.
- **CLI tests** for each command and mode, including structured errors.
- **Legacy test:** a project from the previous release loads and gains the new commands without `state_tampered`.
- **Release checks:**
  - full suites on Python 3.14 and 3.9;
  - `quick_validate.py`;
  - `git diff --check`;
  - the public-path hygiene test;
  - one live headless check of the visual → notice → one-question ordering for `extract` and `create_listing`.
