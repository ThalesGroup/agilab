# DOCX Figure Sync Workflow

## Preferred order

1. Find the editable source figure if it exists.
2. Update the source figure.
3. Render or export the final image if needed.
4. Replace the embedded DOCX media.
5. Verify the DOCX package still opens.
6. Regenerate PDF only when explicitly needed.

## Checks

- figure still appears near the intended caption
- no missing image placeholder
- no broken DOCX archive entries
- no accidental page-count drift unless expected
