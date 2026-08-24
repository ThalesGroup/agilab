from __future__ import annotations

import ast
from pathlib import Path


def _call_name(call: ast.Call) -> str:
    target = call.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return ""


def test_project_editor_checks_archive_quota_before_extraction() -> None:
    source_path = (
        Path(__file__).resolve().parents[1] / "src/agilab/pages/PROJECT_EDITOR.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]

    quota_lines = [
        node.lineno
        for node in calls
        if _call_name(node) == "validate_archive_extraction_quota"
    ]
    extraction_lines = [node.lineno for node in calls if _call_name(node) == "extractall"]

    assert quota_lines
    assert extraction_lines
    assert min(quota_lines) < min(extraction_lines)
