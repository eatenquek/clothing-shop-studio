# Production pack

A production pack is what a factory or print shop works from. It must be accurate enough to produce without guessing, and honest about what still needs the producer's confirmation. It never contains a price or a promise that a supplier will accept it.

## Masters

A production master is the artwork that gets printed or stitched. It must be one of:

- `user_supplied`: the client's own brand artwork, used exactly as supplied (the only case where a raster master is allowed);
- `typeset`: text set in a licensed font, ideally converted to outlines;
- `vector_construction`: vector artwork built for production, including deterministic distress, halftone, or texture.

A generated preview, an AI raster, or a mockup can never be a master, even if it is renamed or traced. Build the master from the approved direction; do not derive it from the preview's pixels. Name files with the `MASTER` token and keep presentation images labelled `MOCKUP`.

Save masters in `production/masters/` and register each one:

```json
{"project_dir": "...", "origin": "production_master", "path": "production/masters/back-typography_MASTER.svg",
 "construction": "typeset", "approved_version": "v001", "placement": "upper_back",
 "reference_point": "centre back, below the back neck seam", "offset_mm": 80,
 "print_width_mm": 300, "print_height_mm": 120,
 "colours": ["Off-white plastisol, match to approved strike-off"], "decoration_method": "plastisol screen print"}
```

Registration refuses masters whose lineage includes a generated concept, mockups, and raster masters that are not the client's own artwork.

## Sizing

Record the size range and whether garment measurements come from the producer's graded chart or a measured spec. Unisex ranges often need a wider graded run than a single-gender block.

## Artwork scaling

A large print that suits a medium can swamp a small and look lost on an XXL. Ask whether one print size fits the whole range or whether to grade it, for example two sizes: S–M at 280 mm and L–XXL at 320 mm wide. Record the answer as `grading_strategy`; the export lists it under Sizing.

## Decoration

The export checks every master's decoration method against the fabric using `data/compatibility-rules.json`. An incompatible combination blocks export and lists alternatives; a conditional or unrecognised one appears as an open note for the producer. State the colour count: limited spot colours suit screen printing, each colour needs its own screen, and light inks on dark garments need an underbase. Embroidery needs text about 5 mm tall or larger.

## Quantity

Quantity guides which methods are sensible. It is not a basis for quoting. As a rough guide, screen printing and embroidery make sense from small batches upward because setup is shared across units; DTG and transfers suit very small runs and detailed colour. Always confirm the producer's minimums.

## Budget

A budget tier (for example lean, average, premium) steers choices such as fabric weight, colour count, and finishing. Never convert it into prices or estimates; pricing is out of scope.

## Producer constraints

Record known constraints: available blank garments, press colour limits, maximum print area, embroidery hoop sizes, lead times the user mentions, and required file formats. Treat each as a requirement to confirm, not a guarantee.

## Packaging

Record labelling, care-label content, folding, bagging, and hang-tag needs if the user has them. Packaging design and retail presentation beyond the garment are out of scope unless the user asks for artwork.

## Deliverables

Ask which outputs the user needs: concept visuals, approved artwork, a production pack, or a factory handoff. Record `deliverables: production_pack` when physical production is intended; that makes the critical fields mandatory before export.

## Exporting

Run `studio.py validate` with `"for_export": true` to see blockers early, then `studio.py export_production_pack`. Export refuses to run while any blocker remains, and returns each one in `error.details` with a stable `code`:

| Code | Fix |
|---|---|
| `missing_critical_answer` | Ask the missing question. |
| `unconfirmed_critical_assumption` | Confirm or correct the inferred value with the user. |
| `no_approved_design` | Get an explicit approval through `approve_design`. |
| `no_production_master`, `master_missing_dimensions`, `master_not_linked_to_approval` | Register a complete master for the approved version. |
| `master_generated_raster`, `master_generated_concept`, `mockup_as_master` | Rebuild the master from typeset, vector, or client artwork. |
| `incompatible_production_method` | Choose one of the listed alternatives with the user. |
| `*_hash_mismatch`, `state_tampered`, `event_chain_broken`, `generated_view_tampered` | Stop. A file changed outside the tools; restore it from backup. |

Each export creates a new read-only `production/pack-vNNN/` containing `masters/` (versioned copies), `production-spec.md`, `handoff-checklist.md`, and `manifest.json` with every file's SHA-256. Earlier packs are never changed. Show the user the spec and checklist, point out every open item, and tell them which details still need the producer's confirmation.
