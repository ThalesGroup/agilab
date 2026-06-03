from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import html
import json
from pathlib import Path
from typing import Any, Sequence
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


DEFAULT_OUTPUT_DIR = Path.home() / "log" / "execute" / "excel_workbook_proof"
SCHEMA = "agilab.example.excel_workbook_proof.evidence.v1"
CREATED_AT = "2026-01-01T00:00:00Z"
ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)
SAMPLE_ROWS: tuple[dict[str, Any], ...] = (
    {"region": "North", "segment": "Enterprise", "month": "2026-01", "units": 18, "revenue": 12600.0},
    {"region": "North", "segment": "SMB", "month": "2026-01", "units": 27, "revenue": 9450.0},
    {"region": "South", "segment": "Enterprise", "month": "2026-01", "units": 14, "revenue": 10500.0},
    {"region": "South", "segment": "SMB", "month": "2026-01", "units": 33, "revenue": 11220.0},
    {"region": "North", "segment": "Enterprise", "month": "2026-02", "units": 21, "revenue": 15120.0},
    {"region": "North", "segment": "SMB", "month": "2026-02", "units": 31, "revenue": 11160.0},
    {"region": "South", "segment": "Enterprise", "month": "2026-02", "units": 17, "revenue": 12750.0},
    {"region": "South", "segment": "SMB", "month": "2026-02", "units": 29, "revenue": 10150.0},
)


def _csv_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _write_csv(path: Path, rows: Sequence[dict[str, Any]], headers: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(headers))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key, "")) for key in headers})


def build_summary_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    totals: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row["region"]), str(row["segment"]))
        item = totals.setdefault(
            key,
            {"region": key[0], "segment": key[1], "units": 0, "revenue": 0.0},
        )
        item["units"] += int(row["units"])
        item["revenue"] += float(row["revenue"])

    summary = []
    for item in sorted(totals.values(), key=lambda value: (value["region"], value["segment"])):
        units = int(item["units"])
        revenue = float(item["revenue"])
        summary.append(
            {
                "region": item["region"],
                "segment": item["segment"],
                "units": units,
                "revenue": revenue,
                "revenue_per_unit": revenue / units if units else 0.0,
            }
        )
    return summary


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _column_name(index: int) -> str:
    chars = []
    while index:
        index, remainder = divmod(index - 1, 26)
        chars.append(chr(65 + remainder))
    return "".join(reversed(chars))


def _cell_xml(value: Any, *, coordinate: str) -> str:
    if isinstance(value, bool):
        return f'<c r="{coordinate}" t="b"><v>{1 if value else 0}</v></c>'
    if isinstance(value, int | float):
        return f'<c r="{coordinate}"><v>{value}</v></c>'
    escaped = html.escape(str(value), quote=True)
    return f'<c r="{coordinate}" t="inlineStr"><is><t>{escaped}</t></is></c>'


def _sheet_xml(rows: Sequence[Sequence[Any]]) -> str:
    xml_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = [
            _cell_xml(value, coordinate=f"{_column_name(column_index)}{row_index}")
            for column_index, value in enumerate(row, start=1)
        ]
        xml_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(xml_rows)}</sheetData>"
        "</worksheet>"
    )


def _rows_from_dicts(rows: Sequence[dict[str, Any]], headers: Sequence[str]) -> list[list[Any]]:
    return [list(headers), *[[row.get(header, "") for header in headers] for row in rows]]


def _write_xlsx(path: Path, sheets: Sequence[tuple[str, Sequence[Sequence[Any]]]]) -> None:
    if not sheets:
        raise ValueError("At least one worksheet is required")

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook_sheets = []
    workbook_rels = []
    content_types = [
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
        '<Override PartName="/docProps/core.xml" '
        'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
        '<Override PartName="/docProps/app.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>',
    ]
    worksheet_parts = {}
    for sheet_id, (name, rows) in enumerate(sheets, start=1):
        safe_name = html.escape(name[:31], quote=True)
        workbook_sheets.append(
            f'<sheet name="{safe_name}" sheetId="{sheet_id}" r:id="rId{sheet_id}"/>'
        )
        workbook_rels.append(
            f'<Relationship Id="rId{sheet_id}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{sheet_id}.xml"/>'
        )
        content_types.append(
            f'<Override PartName="/xl/worksheets/sheet{sheet_id}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
        worksheet_parts[f"xl/worksheets/sheet{sheet_id}.xml"] = _sheet_xml(rows)

    workbook_rels.append(
        f'<Relationship Id="rId{len(sheets) + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
    )

    def writestr(archive: ZipFile, name: str, data: str) -> None:
        info = ZipInfo(name, date_time=ZIP_TIMESTAMP)
        info.compress_type = ZIP_DEFLATED
        archive.writestr(info, data)

    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        writestr(
            archive,
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f"{''.join(content_types)}"
            "</Types>",
        )
        writestr(
            archive,
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/>'
            '<Relationship Id="rId2" '
            'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
            'Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" '
            'Target="docProps/app.xml"/>'
            "</Relationships>",
        )
        writestr(
            archive,
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{''.join(workbook_sheets)}</sheets>"
            "</workbook>",
        )
        writestr(
            archive,
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{''.join(workbook_rels)}"
            "</Relationships>",
        )
        writestr(
            archive,
            "xl/styles.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<fonts count=\"1\"><font><sz val=\"11\"/><name val=\"Calibri\"/></font></fonts>"
            "<fills count=\"1\"><fill><patternFill patternType=\"none\"/></fill></fills>"
            "<borders count=\"1\"><border/></borders>"
            "<cellStyleXfs count=\"1\"><xf/></cellStyleXfs><cellXfs count=\"1\"><xf/></cellXfs>"
            "</styleSheet>",
        )
        writestr(
            archive,
            "docProps/core.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            "<dc:creator>AGILAB</dc:creator>"
            "<dc:title>AGILAB Excel workbook proof preview</dc:title>"
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{CREATED_AT}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{CREATED_AT}</dcterms:modified>'
            "</cp:coreProperties>",
        )
        writestr(
            archive,
            "docProps/app.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
            'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
            "<Application>AGILAB</Application>"
            "</Properties>",
        )
        for name, data in worksheet_parts.items():
            writestr(archive, name, data)


def _artifact(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": _hash_file(path)}


def build_preview(*, output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    output_dir = output_dir.expanduser()
    refresh_dir = output_dir / "power_query_refresh"
    input_headers = ("region", "segment", "month", "units", "revenue")
    summary_headers = ("region", "segment", "units", "revenue", "revenue_per_unit")
    rows = [dict(row) for row in SAMPLE_ROWS]
    summary_rows = build_summary_rows(rows)

    input_csv = refresh_dir / "sales_input.csv"
    summary_csv = refresh_dir / "sales_summary.csv"
    _write_csv(input_csv, rows, input_headers)
    _write_csv(summary_csv, summary_rows, summary_headers)

    input_workbook = output_dir / "input_sales_workbook.xlsx"
    _write_xlsx(input_workbook, [("Sales Input", _rows_from_dicts(rows, input_headers))])

    evidence_rows = [
        ["field", "value"],
        ["schema", SCHEMA],
        ["run_kind", "local spreadsheet proof preview"],
        ["input_workbook", input_workbook.name],
        ["input_workbook_sha256", _hash_file(input_workbook)],
        ["power_query_folder", refresh_dir.name],
        ["sales_input_csv_sha256", _hash_file(input_csv)],
        ["sales_summary_csv_sha256", _hash_file(summary_csv)],
        ["note", "The proof workbook hash is stored in agilab_evidence.json after workbook creation."],
    ]
    proof_workbook = output_dir / "sales_proof_workbook.xlsx"
    _write_xlsx(
        proof_workbook,
        [
            ("Input Data", _rows_from_dicts(rows, input_headers)),
            ("Summary", _rows_from_dicts(summary_rows, summary_headers)),
            ("AGILAB Evidence", evidence_rows),
        ],
    )

    evidence_path = output_dir / "agilab_evidence.json"
    evidence = {
        "schema": SCHEMA,
        "created_at": CREATED_AT,
        "goal": "Show an Excel-shaped AGILAB adoption bridge without requiring an Office add-in.",
        "excel_user_story": (
            "Keep Excel as the familiar workbook interface while AGILAB records "
            "refresh-friendly outputs and reproducibility evidence."
        ),
        "artifacts": {
            "input_workbook": _artifact(input_workbook),
            "proof_workbook": _artifact(proof_workbook),
            "power_query_sales_input": _artifact(input_csv),
            "power_query_sales_summary": _artifact(summary_csv),
        },
        "power_query_hint": "Use Excel Data > Get Data > From File > From Folder on the power_query_refresh directory.",
        "office_add_in_required": False,
        "arbitrary_workbook_import_ui": "roadmap",
    }
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    return {"evidence": _artifact(evidence_path), **evidence}


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create an Excel-shaped AGILAB proof preview with workbook, CSV refresh files, and JSON evidence."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where preview workbook, CSV refresh files, and evidence JSON are written.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> dict[str, Any]:
    args = _parse_args(argv)
    preview = build_preview(output_dir=args.output_dir)
    print(json.dumps(preview, indent=2, sort_keys=True))
    return preview


if __name__ == "__main__":
    main()
