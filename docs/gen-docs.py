#!/usr/bin/env python3
"""Generate documentation artefacts (stubs + HTML) for AGILab."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str], message: str) -> None:
    print(message)
    subprocess.run(cmd, check=True)


def _build_sphinx(source_dir: Path, html_dir: Path) -> None:
    try:
        from sphinx.cmd.build import main as sphinx_build
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise SystemExit(
            "sphinx is not installed. Run `uv pip install sphinx` (and required extensions)"
        ) from exc

    cmd = ["-b", "html", str(source_dir), str(html_dir)]
    print(f"[gen-docs] Building documentation via Sphinx ({source_dir}) …")
    status = sphinx_build(cmd)
    if status != 0:
        raise SystemExit(status)


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    docs_root = repo_root / "docs"
    stub_script = docs_root / "gen_stubs.py"
    output_dir = docs_root / "stubs"
    html_dir = docs_root / "html"
    source_root = docs_root / "source"
    static_root = source_root / "_static"

    if not stub_script.exists():
        print(f"[gen-docs] Missing stub generator at {stub_script}", file=sys.stderr)
        return 1

    static_root.mkdir(parents=True, exist_ok=True)

    _run(
        [
            sys.executable,
            str(stub_script),
            "--clean",
            "--output",
            str(output_dir),
        ],
        "[gen-docs] Generating API stubs …",
    )

    if (docs_root / "conf.py").exists():
        source_dir = docs_root
    elif (source_root / "conf.py").exists():
        source_dir = source_root
    else:
        print(
            "[gen-docs] No Sphinx configuration found (docs/conf.py or docs/source/conf.py). "
            "Skipping HTML build.",
            file=sys.stderr,
        )
        return 0

    _build_sphinx(source_dir, html_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

