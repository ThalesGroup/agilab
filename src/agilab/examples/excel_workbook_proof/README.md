# Excel Workbook Proof Example

## Example Class

**Read-only preview.** The preview writes deterministic local workbook, CSV, and evidence artifacts. It does not install or run an AGILAB app project.


## Purpose

Shows the smallest Excel-shaped AGILAB adoption bridge:

```text
Excel workbook -> AGILAB preview -> result workbook + refresh CSVs + evidence JSON
```

The example is intentionally local and dependency-free. It writes a small
`.xlsx` input workbook, a `.xlsx` proof workbook, Power Query-friendly CSV files,
and hash evidence without requiring an Office add-in or Excel automation.

## What You Learn

- Excel can remain the familiar user interface while AGILAB owns the reproducible
  run evidence.
- Power Query-friendly CSV folders are a lower-friction bridge than a full Office
  add-in for the first adoption step.
- The proof workbook can carry an `AGILAB Evidence` sheet while a JSON evidence
  file records stable artifact hashes.
- Native arbitrary workbook import and a command such as `agilab excel-proof`
  remain product roadmap work, not shipped UI claims.

## Install

There is no separate project install for this preview. Install AGILAB first. The
script uses only the Python standard library and writes local files.

## Run

From a source checkout:

```bash
uv --preview-features extra-build-dependencies run python src/agilab/examples/excel_workbook_proof/preview_excel_workbook_proof.py
```

From an installed AGILAB package, locate the packaged script:

```bash
python -c "from pathlib import Path; import agilab; print(Path(agilab.__file__).with_name('examples') / 'excel_workbook_proof' / 'preview_excel_workbook_proof.py')"
```

Then run it:

```bash
python preview_excel_workbook_proof.py
```

## Expected Input

The script creates a deterministic sample sales workbook with these fields:

- `region`
- `segment`
- `month`
- `units`
- `revenue`

It does not read a private workbook and does not send data to a cloud service.

## Expected Output

The script writes:

```text
~/log/execute/excel_workbook_proof/input_sales_workbook.xlsx
~/log/execute/excel_workbook_proof/sales_proof_workbook.xlsx
~/log/execute/excel_workbook_proof/agilab_evidence.json
~/log/execute/excel_workbook_proof/power_query_refresh/sales_input.csv
~/log/execute/excel_workbook_proof/power_query_refresh/sales_summary.csv
```

Open `sales_proof_workbook.xlsx` in Excel and inspect the `AGILAB Evidence`
sheet. Use Excel `Data > Get Data > From File > From Folder` on the
`power_query_refresh` directory when you want a refresh-friendly handoff.

## Expected Preview

Read the output as a workbook proof contract:

| Artifact | Purpose |
|---|---|
| `input_sales_workbook.xlsx` | Example workbook an analyst would recognize. |
| `sales_proof_workbook.xlsx` | Workbook with input, summary, and evidence sheets. |
| `power_query_refresh/*.csv` | Stable folder-based outputs that Excel can refresh. |
| `agilab_evidence.json` | Machine-readable hashes and adoption-boundary notes. |

## Read The Script

Open `preview_excel_workbook_proof.py` and look for these functions first:

- `build_summary_rows()` aggregates the workbook-shaped input data.
- `_write_xlsx()` writes a minimal workbook with the Python standard library.
- `build_preview()` creates the workbook, refresh CSVs, and evidence JSON.

## Change One Thing

Run the preview with a custom output directory:

```bash
uv --preview-features extra-build-dependencies run python src/agilab/examples/excel_workbook_proof/preview_excel_workbook_proof.py --output-dir /tmp/agilab-excel-proof
```

Then edit one value in `SAMPLE_ROWS`, rerun, and compare the hashes in
`agilab_evidence.json`.

## Troubleshooting

- If Excel opens the workbook in protected view, save a local copy before
  editing; the preview writes normal local `.xlsx` files.
- If Power Query cannot find the folder, copy the absolute
  `power_query_refresh` path printed in `agilab_evidence.json`.
- If you need to import arbitrary customer workbooks, treat that as the next
  product step. This preview deliberately proves the bridge shape first.
