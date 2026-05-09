from __future__ import annotations

import re
import shutil
from pathlib import Path


PACKAGED_CORE_SOURCE_NAMES = frozenset(
    {
        "agi-env",
        "agi-node",
        "agi-core",
        "agi-cluster",
        "agilab",
    }
)

_SECTION_RE = re.compile(r"^\s*\[[^\]]+\]\s*(?:#.*)?$")
_UV_SOURCES_RE = re.compile(r"^\s*\[tool\.uv\.sources\]\s*(?:#.*)?$")
_SOURCE_ENTRY_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*=.*$")


def _has_toml_entries(lines: list[str]) -> bool:
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return True
    return False


def strip_packaged_core_uv_sources(text: str) -> str:
    """Remove source-checkout AGILAB uv sources from packaged app manifests."""

    lines = text.splitlines(keepends=True)
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not _UV_SOURCES_RE.match(line):
            output.append(line)
            index += 1
            continue

        header = line
        index += 1
        block: list[str] = []
        while index < len(lines) and not _SECTION_RE.match(lines[index]):
            block.append(lines[index])
            index += 1

        kept_block: list[str] = []
        for block_line in block:
            match = _SOURCE_ENTRY_RE.match(block_line)
            if match and match.group(1) in PACKAGED_CORE_SOURCE_NAMES:
                continue
            kept_block.append(block_line)

        if _has_toml_entries(kept_block):
            output.append(header)
            output.extend(kept_block)
        elif output and output[-1].strip() and index < len(lines) and lines[index].strip():
            output.append("\n")

    return "".join(output)


def sanitize_packaged_builtin_app_pyprojects(build_lib: str | Path) -> list[Path]:
    """Sanitize built-in app manifests inside setuptools' build/lib tree."""

    builtin_root = Path(build_lib) / "agilab" / "apps" / "builtin"
    if not builtin_root.exists():
        return []

    changed: list[Path] = []
    for pyproject_path in sorted(builtin_root.glob("*_project/pyproject.toml")):
        original = pyproject_path.read_text(encoding="utf-8")
        sanitized = strip_packaged_core_uv_sources(original)
        if sanitized == original:
            continue
        pyproject_path.write_text(sanitized, encoding="utf-8")
        changed.append(pyproject_path)
    return changed


def purge_packaged_builtin_app_artifacts(build_lib: str | Path) -> list[Path]:
    """Remove local build/test artifacts from packaged built-in apps."""

    builtin_root = Path(build_lib) / "agilab" / "apps" / "builtin"
    if not builtin_root.exists():
        return []

    removed: list[Path] = []
    for pycache_dir in sorted(builtin_root.rglob("__pycache__")):
        shutil.rmtree(pycache_dir)
        removed.append(pycache_dir)
    for artifact in sorted(builtin_root.rglob("*")):
        if artifact.is_dir():
            if artifact.name.endswith(".egg-info"):
                shutil.rmtree(artifact)
                removed.append(artifact)
            continue
        if artifact.suffix in {".pyc", ".pyo", ".c"}:
            artifact.unlink()
            removed.append(artifact)
    return removed
