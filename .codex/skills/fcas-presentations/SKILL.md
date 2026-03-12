---
name: fcas-presentations
description: Workflow for FCAS PPTX/DOCX/PDF deliverables, figure assets, and Confluence-safe exports in the sibling thales_agilab repo.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-03-12
---

# FCAS presentations and chapter deliverables

Use this skill when working on the FCAS materials in the sibling repo
`../thales_agilab`, especially:

- `FCAS/Routing-Algo.pptx`
- `FCAS/7_Decision-Engine (FCAS-R-2420051).docx`
- `FCAS/7_Decision-Engine_export.docx`
- `FCAS/*.dot`, `FCAS/*.svg`, `FCAS/*.png`
- `FCAS/tools/generate_routing_algo_slides.py`
- `FCAS/tools/generate_routing_algo_slides_pptx.py`

## Working assumptions

- Treat `../thales_agilab/FCAS` as the source tree.
- Keep English as the default asset language. Preserve French alternates with `_fr`
  suffixes.
- Prefer updating figure source files (`.dot`, `.svg`) before replacing embedded
  PNG copies in Office documents.
- If a deck is generator-driven, update the generators as well as the current
  `.pptx`; do not leave regenerated output out of sync with the source script.

## Figure conventions

- Use the same notation family across MILP and RL figures:
  - `G_t`, `D_t`, `s_d`, `t_d`, `b_d`, `L_d`, `p_d`, `c_e`, `ell_e`,
    `a_d`, `y_{d,e}`, `x_{d,e}`, `f_d`
- Use consistent color semantics when possible:
  - `orange` for runtime inference / decision path
  - `purple` for offline training-only blocks
  - `green` for environment / system context
- Avoid subtitles or meta-reading prompts inside figures unless explicitly asked.
- Prefer captions below figures in DOCX chapters.
- When a keyword line is part of the chapter style, keep `10` keywords when
  possible.

## PPTX workflow

1. Check whether the slide is generated from:
   - `FCAS/tools/generate_routing_algo_slides.py`
   - `FCAS/tools/generate_routing_algo_slides_pptx.py`
2. If yes, patch the generators first, then regenerate a temporary output and
   compare before touching the hand-edited deck.
3. If the user wants the live deck updated immediately, patch the current
   `FCAS/Routing-Algo.pptx` too.
4. Keep speaker notes and slide-local inserted figures aligned with the current
   deck version.

## DOCX workflow

- `.docx` files are OOXML zip bundles. For figure swaps, replace the embedded
  `word/media/image*.png` asset that matches the target figure.
- For text and ordering edits, use `python-docx` or direct OOXML manipulation only
  if paragraph order and styles stay intact.
- After edits, always validate with:
  - `python-docx` open test
  - `zipfile.ZipFile(...).testzip()`
- If visual fidelity matters, export to PDF and inspect the affected pages.

## Source and export chapters

- Keep the source chapter and export chapter aligned in:
  - figure order
  - notation
  - caption wording
  - figure/title placement rules
- The export may contain the whole report; do not infer chapter mismatch from raw
  image counts alone. Compare the active `Decision-Engine` section.

## Confluence-safe outputs

- Prefer PNG for embedded figures and wide diagrams.
- Avoid very wide single-row figures in DOCX when a top-bottom layout is more
  readable.
- Remove decorative text that turns into clutter after Confluence import or PDF
  downscaling.

## Useful commands

- Find FCAS assets:
  - `rg --files ../thales_agilab/FCAS`
- Render Graphviz assets:
  - `dot -Tpng input.dot -o output.png`
  - `dot -Tsvg input.dot -o output.svg`
- Validate a DOCX quickly:
  - `uv run python - <<'PY'`
  - `from docx import Document; import zipfile; p='...'; Document(p); print(zipfile.ZipFile(p).testzip())`
  - `PY`
- Export a DOCX or PPTX to PDF for preview:
  - `soffice --headless --convert-to pdf --outdir <dir> <file>`

## Final checks

- Figures render without text overlap.
- Training-only blocks and inference blocks are visibly separated.
- MILP and RL notation match.
- Slide and chapter wording reflect the latest approved terminology.
- Generator sources, live deliverables, and exported previews are not contradicting
  each other.
