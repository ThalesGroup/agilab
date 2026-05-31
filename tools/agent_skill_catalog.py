#!/usr/bin/env python3
"""Generate AGILAB's public agent-skill catalog and LLM index files."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SKILLS_ROOT = REPO_ROOT / ".claude" / "skills"
DEFAULT_MARKDOWN_OUT = REPO_ROOT / "AGENT_SKILLS.md"
DEFAULT_LLMS_OUT = REPO_ROOT / "llms.txt"
DEFAULT_LLMS_FULL_OUT = REPO_ROOT / "llms-full.txt"
WORKS_WITH = ("Codex", "Claude Code", "Aider", "OpenCode")
CATALOG_COMPATIBLE = ("Continue",)


def _codex_skills_module():
    module_path = REPO_ROOT / "tools" / "codex_skills.py"
    spec = importlib.util.spec_from_file_location("agilab_catalog_codex_skills", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def collect_skills(skills_root: Path):
    module = _codex_skills_module()
    skills, issues = module.collect_skills(skills_root)
    if issues:
        joined = "\n".join(f"- {issue}" for issue in issues)
        raise RuntimeError(f"skill catalog generation blocked by validation issues:\n{joined}")
    return sorted(skills, key=lambda skill: skill.name.lower())


def _skill_lines(skills: Iterable[object], *, full: bool) -> list[str]:
    lines: list[str] = []
    for skill in skills:
        path = _rel(skill.path)
        lines.append(f"- {skill.name}: {skill.description} ({path})")
        if full:
            lines.append(f"  license: {skill.license}")
            if skill.updated:
                lines.append(f"  updated: {skill.updated}")
            if skill.body_preview:
                preview = " ".join(line.strip() for line in skill.body_preview.splitlines() if line.strip())
                lines.append(f"  preview: {preview}")
    return lines


def _skill_count_label(count: int) -> str:
    suffix = "skill" if count == 1 else "skills"
    return f"{count} {suffix}"


def render_markdown(skills: list[object]) -> str:
    lines = [
        "# AGILAB Agent Skills",
        "",
        "AGILAB keeps repo-managed skills as reviewed workflow assets, not as a bulk third-party skill dump.",
        "The canonical shared source is `.claude/skills/`; `.codex/skills/` is the generated Codex mirror.",
        "",
        "## Badges",
        "",
        "- Skills: " + _skill_count_label(len(skills)),
        "- Standard: Agent Skills style `SKILL.md` runbooks with front matter and self-contained references",
        "- Works with: " + ", ".join(WORKS_WITH),
        "- Catalog-compatible: " + ", ".join(CATALOG_COMPATIBLE),
        "",
        "## Security And Maintenance Contract",
        "",
        "- New or changed skills are scanned with `tools/skill_security_scan.py`.",
        "- Skill structure, local links, support-file reachability, and activation size are checked with `tools/agent_skill_quality_guard.py`.",
        "- Skill indexes are regenerated with `tools/codex_skills.py --root .codex/skills generate`.",
        "- Public catalog files are regenerated with `tools/agent_skill_catalog.py --apply`.",
        "- The public capability manifest is regenerated with `tools/agilab_capabilities_manifest.py --apply`.",
        "- Skills that require network access, shell execution, or local services must say so explicitly.",
        "",
        "## Catalog",
        "",
    ]
    lines.extend(_skill_lines(skills, full=False))
    return "\n".join(lines) + "\n"


def render_llms(skills: list[object]) -> str:
    lines = [
        "# AGILAB",
        "",
        "> Reproducible AI/ML workbench for turning notebooks, scripts, and agent runs into executable apps and evidence.",
        "",
        "## Agent Skills",
        "",
        "AGILAB exposes repo-managed Agent Skills compatible with Codex and Claude Code.",
        "Continue can consume this generated catalog, but AGILAB does not ship a Continue wrapper.",
        "Use `.claude/skills/` as the canonical skill source and `.codex/skills/` as the Codex mirror.",
        "Use `agilab-capabilities.json` for the machine-readable inventory of shipped CLI, page, app, package, schema, and catalog surfaces.",
        "",
    ]
    lines.extend(_skill_lines(skills, full=False))
    return "\n".join(lines) + "\n"


def render_llms_full(skills: list[object]) -> str:
    lines = [
        "# AGILAB Agent Skills Full Index",
        "",
        "This file is generated from `.claude/skills/*/SKILL.md` for LLM and scraper discovery.",
        "",
        "## Compatibility",
        "",
        "- Standard: Agent Skills style `SKILL.md` folders",
        "- Works with: " + ", ".join(WORKS_WITH),
        "- Catalog-compatible: " + ", ".join(CATALOG_COMPATIBLE),
        "- Capability manifest: `agilab-capabilities.json` generated by `tools/agilab_capabilities_manifest.py --apply`",
        "- Maintenance: `tools/agent_skill_quality_guard.py`, `tools/skill_security_scan.py`, `tools/codex_skills.py`, `tools/agent_skill_catalog.py`, and `tools/agilab_capabilities_manifest.py`",
        "",
        "## Skills",
        "",
    ]
    lines.extend(_skill_lines(skills, full=True))
    return "\n".join(lines) + "\n"


def generate_outputs(skills_root: Path) -> dict[Path, str]:
    skills = collect_skills(skills_root)
    return {
        DEFAULT_MARKDOWN_OUT: render_markdown(skills),
        DEFAULT_LLMS_OUT: render_llms(skills),
        DEFAULT_LLMS_FULL_OUT: render_llms_full(skills),
    }


def write_outputs(outputs: dict[Path, str]) -> list[Path]:
    changed: list[Path] = []
    for path, content in outputs.items():
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        if existing != content:
            path.write_text(content, encoding="utf-8")
            changed.append(path)
    return changed


def check_outputs(outputs: dict[Path, str]) -> list[Path]:
    stale: list[Path] = []
    for path, content in outputs.items():
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            stale.append(path)
    return stale


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-root", type=Path, default=DEFAULT_SKILLS_ROOT)
    parser.add_argument("--apply", action="store_true", help="Write generated catalog files.")
    parser.add_argument("--check", action="store_true", help="Fail if generated catalog files are stale.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    outputs = generate_outputs(args.skills_root)
    if args.apply:
        changed = write_outputs(outputs)
        if changed:
            print("Generated:")
            for path in changed:
                print(f" - {_rel(path)}")
        else:
            print("No changes in generated catalog outputs")
    if args.check:
        stale = check_outputs(outputs)
        if stale:
            print("ERROR: generated agent-skill catalog files are stale:", file=sys.stderr)
            for path in stale:
                print(f" - {_rel(path)}", file=sys.stderr)
            return 2
        print("OK: agent-skill catalog files are current")
    if not args.apply and not args.check:
        print(render_llms(collect_skills(args.skills_root)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
