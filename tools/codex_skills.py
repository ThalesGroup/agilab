#!/usr/bin/env python3
"""Codex skills helper.

Utility to validate `.codex/skills/*/SKILL.md` files, generate deterministic skill
indexes, and create new skills from the standard template.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


DOCS_ROOT_DEFAULT = Path(".codex/skills")
JSON_DEFAULT = DOCS_ROOT_DEFAULT / ".generated" / "skills_index.json"
MD_DEFAULT = DOCS_ROOT_DEFAULT / ".generated" / "skills_index.md"


@dataclass
class SkillData:
    name: str
    description: str
    license: str
    path: Path
    body_preview: str
    updated: str | None


def parse_front_matter(md_text: str, path: Path) -> tuple[Dict[str, Any], str, list[str]]:
    """Parse SKILL.md front-matter.

    Supports the simplified YAML currently used in this repository, including one
    level of nested `metadata` map.
    """

    lines = md_text.splitlines()
    issues: list[str] = []

    if not lines or lines[0].strip() != "---":
        issues.append(f"{path}: missing front-matter opening '---'")
        return {}, "\n".join(lines), issues

    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        issues.append(f"{path}: missing front-matter closing '---'")
        return {}, "\n".join(lines), issues

    fm_lines = lines[1:end]
    body = "\n".join(lines[end + 1 :]).lstrip("\n")

    data: Dict[str, Any] = {}
    i = 0
    while i < len(fm_lines):
        raw = fm_lines[i]
        i += 1
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue

        m = re.match(r"^(?P<indent>[ ]{0,4})(?P<key>[A-Za-z0-9_.-]+):(?P<rest>.*)$", raw)
        if not m:
            issues.append(f"{path}: cannot parse front-matter line: {raw!r}")
            continue

        key = m.group("key")
        rest = m.group("rest").strip()

        if rest:
            data[key] = _parse_scalar(rest)
            continue

        # Nested mapping block (one level expected)
        nested: Dict[str, Any] = {}
        while i < len(fm_lines):
            nested_line = fm_lines[i]
            nm = re.match(r"^(?P<indent>[ ]{2,})(?P<nkey>[A-Za-z0-9_.-]+):(?P<nrest>.*)$", nested_line)
            if not nm:
                break
            nk = nm.group("nkey")
            nrest = nm.group("nrest").strip()
            if not nrest:
                issues.append(
                    f"{path}: nested front-matter key '{nk}' has no value; unsupported deeper nesting"
                )
            else:
                nested[nk] = _parse_scalar(nrest)
            i += 1

        if nested:
            data[key] = nested
        else:
            issues.append(f"{path}: front-matter key '{key}' missing value")

    return data, body, issues


def _parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if value == "":
        return ""
    if (value.startswith("'") and value.endswith("'")) or (
        value.startswith('"') and value.endswith('"')
    ):
        return value[1:-1]
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    if value.lower() in ("null", "none"):
        return None
    if re.fullmatch(r"-?\d+(\.\d+)?", value):
        return float(value) if "." in value else int(value)
    return value


def _validate_skill_front_matter(
    name: str, fm: Dict[str, Any], path: Path
) -> list[str]:
    issues: list[str] = []
    required = ("name", "description", "license")
    for key in required:
        if key not in fm:
            issues.append(f"{path}: missing required front-matter key '{key}'")
        elif not isinstance(fm[key], str):
            issues.append(f"{path}: '{key}' must be a string")

    fm_name = fm.get("name")
    if isinstance(fm_name, str) and fm_name != name:
        issues.append(f"{path}: front-matter name '{fm_name}' does not match folder '{name}'")

    fm_desc = fm.get("description")
    if isinstance(fm_desc, str) and not fm_desc.strip():
        issues.append(f"{path}: description should not be empty")

    fm_license = fm.get("license")
    if isinstance(fm_license, str) and not fm_license.strip():
        issues.append(f"{path}: license should not be empty")

    metadata = fm.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        issues.append(f"{path}: metadata must be a mapping")

    updated = metadata.get("updated") if isinstance(metadata, dict) else None
    if updated is not None and not isinstance(updated, str):
        issues.append(f"{path}: metadata.updated should be a string if present")

    return issues


def collect_skills(skills_root: Path) -> tuple[list[SkillData], list[str]]:
    skills: list[SkillData] = []
    issues: list[str] = []

    for skill_dir in sorted(p for p in skills_root.iterdir() if p.is_dir()):
        if skill_dir.name.startswith("."):
            continue
        if skill_dir.name in {".generated"}:
            continue

        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            issues.append(f"{skill_dir}: missing SKILL.md")
            continue

        content = skill_file.read_text(encoding="utf-8")
        fm, body, fm_issues = parse_front_matter(content, skill_file)
        issues.extend(fm_issues)
        issues.extend(_validate_skill_front_matter(skill_dir.name, fm, skill_file))

        body_preview = "\n".join(
            [line for line in body.splitlines() if line.strip()][:4]
        ).strip()
        metadata = fm.get("metadata", {}) if isinstance(fm, dict) else {}
        updated = metadata.get("updated") if isinstance(metadata, dict) else None
        if not isinstance(updated, str):
            updated = None

        skills.append(
            SkillData(
                name=fm.get("name", skill_dir.name),
                description=fm.get("description", ""),
                license=fm.get("license", ""),
                path=skill_file,
                body_preview=body_preview,
                updated=updated,
            )
        )

    return skills, issues


def generate_outputs(skills: list[SkillData], json_out: Path, md_out: Path) -> list[Path]:
    generated_at = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sorted_skills = sorted(skills, key=lambda s: s.name.lower())
    payload = {
        "generated_at_utc": generated_at,
        "tool": "tools/codex_skills.py",
        "count": len(skills),
        "skills": [
            {
                "name": s.name,
                "description": s.description,
                "license": s.license,
                "updated": s.updated,
                "path": str(s.path.as_posix()),
                "body_preview": s.body_preview,
            }
            for s in sorted_skills
        ],
    }
    json_text = json.dumps(payload, indent=2) + "\n"

    lines = [
        "# Codex Skills Index",
        "",
        f"Generated: {generated_at}",
        "",
        "This file is auto-generated by `tools/codex_skills.py`.",
        "",
        "| Skill | Description | Updated | License | Source file |",
        "|---|---|---|---|---|",
    ]

    for skill in sorted_skills:
        updated = skill.updated or "-"
        lines.append(
            "| `{name}` | {description} | {updated} | {license} | `{path}` |".format(
                name=_md_escape_cell(skill.name),
                description=_md_escape_cell(skill.description),
                updated=_md_escape_cell(updated),
                license=_md_escape_cell(skill.license),
                path=skill.path.as_posix(),
            )
        )

    md_text = "\n".join(lines) + "\n"

    changed = []
    if _write_if_changed(json_out, json_text):
        changed.append(json_out)
    if _write_if_changed(md_out, md_text):
        changed.append(md_out)

    return changed


def _write_if_changed(path: Path, content: str) -> bool:
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    if existing == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _quote_yaml_scalar(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _md_escape_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def create_skill(
    skills_root: Path, name: str, description: str, license_text: str, force: bool
) -> Path:
    slug = _slugify(name)
    skill_dir = skills_root / slug
    if skill_dir.exists() and not force:
        raise RuntimeError(
            f"Skill directory already exists: {skill_dir}. Use --force to overwrite."
        )
    skill_dir.mkdir(parents=True, exist_ok=True)

    today = _dt.date.today().isoformat()
    content = f"""---
name: {slug}
description: {_quote_yaml_scalar(description)}
license: {_quote_yaml_scalar(license_text)}
metadata:
  updated: {today}
---

# {name} Skill

Add runbook notes and concrete commands in this section.
"""

    path = skill_dir / "SKILL.md"
    if path.exists() and not force:
        raise RuntimeError(f"SKILL.md already exists: {path}. Use --force to overwrite.")

    path.write_text(content, encoding="utf-8")
    return path


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        raise ValueError("Computed slug is empty; provide a meaningful skill name.")
    return slug


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage Codex skill definitions")
    parser.add_argument(
        "--root",
        default=str(DOCS_ROOT_DEFAULT),
        help="Path to skills root (default: .codex/skills)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    validate_cmd = sub.add_parser("validate", help="Validate SKILL.md front matter")
    validate_cmd.add_argument("--strict", action="store_true", help="Fail on warnings")

    generate_cmd = sub.add_parser("generate", help="Generate deterministic skill index")
    generate_cmd.add_argument(
        "--json-output",
        default=str(JSON_DEFAULT),
        help="Path to generated JSON index",
    )
    generate_cmd.add_argument(
        "--md-output",
        default=str(MD_DEFAULT),
        help="Path to generated Markdown index",
    )

    create_cmd = sub.add_parser("create", help="Create a new skill folder with SKILL.md")
    create_cmd.add_argument("name", help="Skill display name")
    create_cmd.add_argument(
        "--description", required=True, help="Skill short description"
    )
    create_cmd.add_argument(
        "--license",
        required=True,
        help="License text for the generated SKILL.md",
    )
    create_cmd.add_argument("--force", action="store_true", help="Overwrite existing files")

    args = parser.parse_args(argv)
    root = Path(args.root)
    if not root.exists():
        print(f"ERROR: skills root does not exist: {root}", file=sys.stderr)
        return 2

    skills, issues = collect_skills(root)

    if args.command == "validate":
        if args.strict:
            if issues:
                for issue in issues:
                    print(f"ERROR: {issue}", file=sys.stderr)
                return 2
            print(f"OK: validated {len(skills)} skills")
            return 0

        if issues:
            for issue in issues:
                print(f"WARN: {issue}", file=sys.stderr)
        print(f"OK: validated {len(skills)} skills with {len(issues)} warning(s)")
        return 1 if issues else 0

    if args.command == "generate":
        changed = generate_outputs(
            skills=skills,
            json_out=Path(args.json_output),
            md_out=Path(args.md_output),
        )
        if changed:
            print("Generated:")
            for path in changed:
                print(f" - {path}")
        else:
            print("No changes in generated outputs")
        return 2 if issues else 0

    if args.command == "create":
        try:
            created = create_skill(
                skills_root=root,
                name=args.name,
                description=args.description,
                license_text=args.license,
                force=args.force,
            )
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        print(f"Created {created}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
