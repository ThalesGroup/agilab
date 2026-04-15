#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape


def _text_run(text: str, *, bold: bool = False, size_half_points: int | None = None) -> str:
    properties = []
    if bold:
        properties.append("<w:b/>")
    if size_half_points is not None:
        properties.append(f'<w:sz w:val="{size_half_points}"/>')
    props_xml = f"<w:rPr>{''.join(properties)}</w:rPr>" if properties else ""
    safe = escape(text or "")
    return f"<w:r>{props_xml}<w:t xml:space=\"preserve\">{safe}</w:t></w:r>"


def _paragraph(text: str, *, bold: bool = False, size_half_points: int | None = None) -> str:
    return f"<w:p>{_text_run(text, bold=bold, size_half_points=size_half_points)}</w:p>"


def build_docx(messages: list[dict[str, str]], *, title: str | None = None) -> bytes:
    body_parts: list[str] = []
    if title:
        body_parts.append(_paragraph(title, bold=True, size_half_points=32))
        body_parts.append(_paragraph(""))

    for message in messages:
        role = str(message.get("role", "unknown")).capitalize()
        content = str(message.get("content", "") or "")
        body_parts.append(_paragraph(role, bold=True, size_half_points=24))
        for line in content.splitlines() or [""]:
            body_parts.append(_paragraph(line))
        body_parts.append(_paragraph(""))

    body_xml = "".join(body_parts) + "<w:sectPr/>"
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document
  xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas"
  xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
  xmlns:o="urn:schemas-microsoft-com:office:office"
  xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
  xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"
  xmlns:v="urn:schemas-microsoft-com:vml"
  xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing"
  xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
  xmlns:w10="urn:schemas-microsoft-com:office:word"
  xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
  xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"
  xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"
  xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk"
  xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml"
  xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
  mc:Ignorable="w14 wp14">
  <w:body>{body_xml}</w:body>
</w:document>
"""

    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""

    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def write_docx(output_path: Path, messages: list[dict[str, str]], *, title: str | None = None) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(build_docx(messages, title=title))


if __name__ == "__main__":
    sample_messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi"},
    ]
    target = Path("chat-export-sample.docx")
    write_docx(target, sample_messages, title="Sample")
    print(json.dumps({"written": str(target)}, indent=2))
