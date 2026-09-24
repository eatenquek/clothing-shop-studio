# Visual options

## When a visual is required

Show pictures whenever the user must judge how something looks: silhouette and fit, proportion, colourway, graphic direction, typography, placement, scale, material appearance, decoration treatment, or presentation style. The interview marks these questions `"visual": true`. Never answer a visual question with a prose list of options.

Skip visuals only for facts that pictures cannot settle: quantity, size range, care, budget tier, deliverables, or an exact wording the user has already given.

## Four options: A, B, C, W

Every comparison has exactly four options:

- **A, B, C**: practical, market-credible directions that satisfy every constraint.
- **W**: a wildcard that breaks one stated convention (for example, type crossing the shoulder seam) while keeping every hard constraint and staying producible.

Give each option its own named axis, such as letter density, alignment, distress level, or scale. Four near-identical options are rejected. Hold everything else constant (garment, view, lighting, colour count) so only the named axis changes.

## Typical axes

Choose four axes that matter for the decision in hand. Typical choices:

### Colour

Body colour, ink or thread colour, contrast level, heather versus solid, garment-dyed versus piece-dyed. State the colour count; each extra spot colour usually adds a screen.

### Artwork

Motif, level of illustration versus type, composition, texture or distress treatment, degree of abstraction of a theme (for example a yokai drawn as a silhouette versus a symbol).

### Typography

Width (condensed or extended), weight, case, letter spacing, baseline behaviour, and how much irregularity the type carries. Typeset or vector lettering is needed later for the production master.

### Placement

Centre chest, left chest, full front, upper back, full back, back yoke, sleeve, hem. Show front or back view to match the placement.

### Scale

Artwork width relative to the garment, and how it behaves across the size range: one print size for all sizes or graded sizes.

## Workflow

1. **Plan.** Run `studio.py generate_options` with `"mode": "plan"`, a `decision_id` (for example `back_typography`), four `axes`, and the hard `constraints`. The response gives each slot's label, axis, and destination under `concepts/generated/<decision_id>/rNN/`.
2. **Render.** Create one image per slot with the available image tool and save it at its destination. Put the slot label visibly inside every image, or deliver a labelled contact sheet as well. Brand artwork and exact text must be composited from the user's files, never redrawn by an image model.
3. **Register.** Run `generate_options` with `"mode": "register"`, the `decision_id`, and four `results`. Each result has `label`, `axis`, relative `path`, `renderer`, and `prompt`; W also has `convention_broken`. Registration hashes each file and records it as a `generated_concept` with `production_eligible: false`.
4. **Show.** Present all four images together with their labels and one-line differences, then ask the user to choose, combine, revise, or regenerate.

## No image tool

When no raster image tool is available, run `scripts/render-options.py` with the planned `output_dir` and four briefs (`label`, `axis`, `title`, `brief`, `garment`, `placement`, `colors` as `#RRGGBB`). It writes `option-A.svg` through `option-W.svg` and `contact-sheet.svg`. Register the four option files with `"renderer": "svg-fallback"` and show the contact sheet.

## Combining and revising

When the user combines elements, for example "A's palette with C's placement", render the combined preview into `concepts/generated/<decision_id>/` and run `generate_options` with `"mode": "merge"`, the `path`, `renderer`, a short `description`, and `parents` naming the source concept ids. Revising or regenerating creates a new round (`r02`, `r03`, …); earlier rounds stay on record.

A generated preview is never approval and never production artwork. Approval happens only through `approve_design`, and production masters come from user-supplied, typeset, or vector artwork.
