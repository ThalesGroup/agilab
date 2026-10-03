"""Replace explicit UI imports without reformatting application source files."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import re


def migrated_source(source: str) -> tuple[str, int, list[str]]:
    tree = ast.parse(source)
    lines = source.encode().splitlines(keepends=True)
    starts = [0]
    for line in lines: starts.append(starts[-1] + len(line))
    changes, unknown = [], []
    for node in ast.walk(tree):
        replacement = None
        if isinstance(node, ast.Import) and any(name.name == "streamlit" for name in node.names):
            if len(node.names) != 1:
                unknown.append(ast.get_source_segment(source, node)); continue
            replacement = "from agi_web import python_ui as " + (node.names[0].asname or "streamlit")
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("streamlit"):
            if node.module == "streamlit.errors" and all(name.name == "StreamlitAPIException" for name in node.names):
                replacement = "from agi_web.python_view_session import " + ", ".join("UIError" + (" as " + name.asname if name.asname else "") for name in node.names)
            elif node.module == "streamlit.runtime.scriptrunner" and all(name.name in {"get_script_run_ctx", "RerunException"} for name in node.names):
                replacement = "from agi_web.python_ui import " + ", ".join(name.name + (" as " + name.asname if name.asname else "") for name in node.names)
            elif node.module == "streamlit.testing.v1" and all(name.name == "AppTest" for name in node.names):
                replacement = "from agi_web.testing import " + ", ".join(name.name + (" as " + name.asname if name.asname else "") for name in node.names)
            elif node.module == "streamlit" and all(name.name == "config" for name in node.names):
                replacement = "from agi_web.python_ui import " + ", ".join(name.name + (" as " + name.asname if name.asname else "") for name in node.names)
            else:
                unknown.append(ast.get_source_segment(source, node)); continue
        elif isinstance(node, ast.Import) and any(name.name.startswith("streamlit.") for name in node.names):
            unknown.append(ast.get_source_segment(source, node)); continue
        if replacement:
            changes.append((starts[node.lineno - 1] + node.col_offset, starts[node.end_lineno - 1] + node.end_col_offset, replacement.encode()))
    data = source.encode()
    for start, end, replacement in sorted(changes, reverse=True): data = data[:start] + replacement + data[end:]
    result = data.decode()
    result = re.sub(r"\bStreamlitAPIException\b", "UIError", result)
    result = re.sub(r"\brequire_streamlit\b", "require_python_ui", result)
    ast.parse(result)
    return result, len(changes), unknown


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    count, files, remaining = 0, [], []
    for root in args.paths:
        for path in sorted(root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            try: result, changed, unknown = migrated_source(source)
            except SyntaxError: continue
            remaining.extend(f"{path}: {item}" for item in unknown)
            if result != source:
                files.append(str(path)); count += changed
                if args.apply: path.write_text(result, encoding="utf-8")
    print(f"{'Migrated' if args.apply else 'Proposed'} {count} imports in {len(files)} files.")
    for item in remaining: print("Manual migration: " + item)


if __name__ == "__main__": main()
