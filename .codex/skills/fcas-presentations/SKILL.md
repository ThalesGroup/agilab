---
name: fcas-presentations
description: Workflow for FCAS PPTX/DOCX/PDF deliverables, figure assets, and Confluence-safe exports in the sibling thales_agilab repo.
license: BSD-3-Clause (see repo LICENSE)
metadata:
  updated: 2026-03-16
---

# FCAS presentations and chapter deliverables

Use this skill when working on the FCAS materials in the sibling repo
`../thales_agilab`, especially:

- `FCAS/Routing-Algo.pptx`
- `FCAS/7_Decision-Engine (FCAS-R-2420051).docx`
- `FCAS/7_Decision-Engine_export.docx`
- `FCAS/FCAS-R-XXXXXXX_Final report for PCM Decision-Engine.docx`
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
  - `G_t`, `D_t`, `src_d`, `dst_d`, `b_d`, `b_d^{min}`, `L_d`, `p_d`,
    `c_e`, `ell_e`, `q_g`, `q_g^{max}`, `a_d`, `y_{d,e}`, `x_{d,e}`, `f_d`
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
- When the user says the final report is the only target, do not assume the source
  chapter or export chapter should be kept in sync in the same pass.
- When editing the final report, keep the visible front matter aligned with the
  current content:
  - `Table of Contents`
  - `Table of Figures`
  - visible `Number of pages` row
- When a figure caption has been fixed but the user still sees stale wording, check
  the embedded image bytes in `word/media/*`, not only the paragraph text. Word may
  display a stale embedded bitmap even when the caption is already correct.
- For inherited PCM report content, watch explicitly for stale leftovers such as:
  - `chapter 7` / `chapter-7`
  - old `see page ...` pointers
  - old `.doc` titles for earlier deliveries
  - glossary or definitions rows that still use superseded notation
- In the final report, prefer document-traceability prose over bibliography rows for
  previous internal deliverables when they are mentioned only once.
- For abbreviations used only once, prefer expanding them in place and removing them
  from the abbreviations table.
- For the content tables in the final report (`Applicable Documents`, `Referenced
  Documents`, `Abbreviations`, `Definitions`), a safe normalization is:
  - top cell alignment
  - left paragraph alignment
  - zero before/after spacing in body rows
- Do not apply that normalization blindly to the cover, signature, or identification
  form tables; those often mix alignments intentionally.
- Small manual font overrides in Annex D subheads can be intentional layout aids.
  Check the rendered PDF before normalizing them away.
- After edits, always validate with:
  - `python-docx` open test
  - `zipfile.ZipFile(...).testzip()`
- If visual fidelity matters, export to PDF and inspect the affected pages.

## Final report annex pattern

- The current FCAS final report uses annexes as a traceability extension of the
  main narrative, not as a repository dump.
- Keep the annex roles distinct:
  - `Annex A`: implementation traceability matrix
  - `Annex B`: variable-name traceability matrix
  - `Annex C`: app input/output traceability matrix
  - `Annex D`: project implementation metrics
- When adding or extending annexes:
  - add one short bridge sentence in the body so the reader is told why the
    annex matters
  - keep matrix tables compact and page-readable
  - prefer one annex per traceability question rather than one oversized table
- For annex tables:
  - use repeated header rows
  - use explicit column widths
  - top-align cells
  - break long code-path cells across lines for PDF readability

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

## Chat transcript PDF exports

- When the user asks for a chat export, store the export inside
  `../thales_agilab/FCAS/chat_exports/`, not only in `~/Downloads`.
- Keep a repo-local generator script next to the PDF, for example
  `FCAS/chat_exports/export_<slug>_chat_pdf.py`, so the same transcript can be
  rebuilt later.
- Preserve role coloring with a chat-style layout instead of a plain text dump.
- If the user gives a start message, export only from that point onward.
- Prefer a Unicode-capable font such as `Arial Unicode` when available so
  arrows, bullets, and path-like text survive in the PDF.
- After generation, verify:
  - the PDF exists in the repo
  - the file type is `PDF document`
  - the reported page count is plausible for the selected range

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
- Visible TOC / annex pages / page-count fields match the exported PDF.
- Generator sources, live deliverables, and exported previews are not contradicting
  each other.
