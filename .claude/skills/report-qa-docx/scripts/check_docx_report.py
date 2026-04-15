#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET


W_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
REL_NS = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}


def read_xml_from_docx(docx_path: Path, member: str) -> ET.Element | None:
    with zipfile.ZipFile(docx_path) as archive:
        try:
            data = archive.read(member)
        except KeyError:
            return None
    return ET.fromstring(data)


def extract_paragraphs(docx_path: Path) -> list[str]:
    root = read_xml_from_docx(docx_path, "word/document.xml")
    if root is None:
        return []
    paragraphs: list[str] = []
    for para in root.findall(".//w:p", W_NS):
        texts = [node.text or "" for node in para.findall(".//w:t", W_NS)]
        text = "".join(texts).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def list_media(docx_path: Path) -> list[str]:
    with zipfile.ZipFile(docx_path) as archive:
        return sorted(
            name for name in archive.namelist() if name.startswith("word/media/") and not name.endswith("/")
        )


def referenced_media(docx_path: Path) -> list[str]:
    refs: set[str] = set()
    with zipfile.ZipFile(docx_path) as archive:
        for name in archive.namelist():
            if not name.startswith("word/") or not name.endswith(".rels"):
                continue
            if "/_rels/" not in name and name != "word/_rels/document.xml.rels":
                continue
            try:
                root = ET.fromstring(archive.read(name))
            except Exception:
                continue
            base = Path(name).parent.parent
            for rel in root.findall(".//r:Relationship", REL_NS):
                target = rel.get("Target", "")
                if "media/" not in target:
                    continue
                resolved = str((base / target).as_posix()).replace("word/../", "word/")
                refs.add(resolved)
    return sorted(refs)


def figure_captions(paragraphs: list[str]) -> list[str]:
    pattern = re.compile(r"^Figure\b", re.IGNORECASE)
    return [text for text in paragraphs if pattern.match(text)]


def repeated_long_paragraphs(paragraphs: list[str], *, min_length: int = 40) -> dict[str, int]:
    counts = Counter(text for text in paragraphs if len(text) >= min_length)
    return {text: count for text, count in counts.items() if count > 1}


def build_report(docx_path: Path, terms: list[str]) -> dict:
    paragraphs = extract_paragraphs(docx_path)
    captions = figure_captions(paragraphs)
    media = list_media(docx_path)
    refs = referenced_media(docx_path)
    repeated = repeated_long_paragraphs(paragraphs)
    term_hits = {
        term: sum(text.count(term) for text in paragraphs)
        for term in terms
    }
    return {
        "docx": str(docx_path),
        "paragraph_count": len(paragraphs),
        "figure_caption_count": len(captions),
        "figure_captions": captions,
        "media_count": len(media),
        "media_files": media,
        "referenced_media_count": len(refs),
        "referenced_media": refs,
        "unreferenced_media": [item for item in media if item not in refs],
        "duplicate_captions": {text: count for text, count in Counter(captions).items() if count > 1},
        "repeated_long_paragraphs": repeated,
        "term_hits": term_hits,
    }


def render_text(report: dict) -> str:
    lines = [
        f"DOCX: {report['docx']}",
        f"Paragraphs: {report['paragraph_count']}",
        f"Figure captions: {report['figure_caption_count']}",
        f"Media files: {report['media_count']}",
        f"Referenced media: {report['referenced_media_count']}",
    ]
    if report["duplicate_captions"]:
        lines.append("Duplicate figure captions:")
        for text, count in report["duplicate_captions"].items():
            lines.append(f"  - {count}x {text}")
    if report["unreferenced_media"]:
        lines.append("Unreferenced media:")
        for item in report["unreferenced_media"]:
            lines.append(f"  - {item}")
    if report["repeated_long_paragraphs"]:
        lines.append("Repeated long paragraphs:")
        for text, count in list(report["repeated_long_paragraphs"].items())[:10]:
            lines.append(f"  - {count}x {text}")
    if any(report["term_hits"].values()):
        lines.append("Requested term hits:")
        for term, count in report["term_hits"].items():
            lines.append(f"  - {term}: {count}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a deterministic QA scan on a DOCX report.")
    parser.add_argument("docx", type=Path, help="Input DOCX path")
    parser.add_argument("--term", action="append", default=[], help="Extra term to count in paragraph text")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    args = parser.parse_args()

    report = build_report(args.docx, args.term)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(report))


if __name__ == "__main__":
    main()
