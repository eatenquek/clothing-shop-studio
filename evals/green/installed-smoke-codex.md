# Installed-path smoke test (Codex)

- Installed bundle: `~/.codex/skills/clothing-shop-studio` (44 files, byte-identical to the tracked bundle at `d8db0809bd04a49158ffa68c7e1e89f87e9217fb`)
- Runtime: `codex exec` (codex-cli 0.154.0), fresh session, `workspace-write` sandbox, throwaway workspace; no `CLOTHING_SHOP_STUDIO_HOME` and no saved config.

| Turn | User | Assistant (final message, verbatim) | Result |
|---|---|---|---|
| 1 | Use $clothing-shop-studio. Help me design a garment. | Where would you like me to store your clothing design projects? | PASS: root asked once, alone |
| 2 | Store it in <workspace>/projects for this project only; do not remember the location. | Would you like to attach a reference image? If not, say no and we will continue. | PASS: reference asked first |
| 3 | No reference image, thanks. | What are we designing: tee, long-sleeve, polo, tank, performance top, sweatshirt, hoodie, jacket, bottoms, headwear, bag, or another garment? | PASS: one garment question |

- Project state: slug `garment-design`, phase `intake`, answers `reference_image: null`, `reference_status: none`.
- `~/.config/clothing-shop-studio` was not created; no files were added inside the installed skill.
