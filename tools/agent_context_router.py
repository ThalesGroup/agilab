#!/usr/bin/env python3
"""Recommend AGILAB agent runbooks and skills from files or a prompt.

This is a small AGILAB-native adaptation of the "baseline + detected packs"
pattern used by public AGENTS.md skill libraries. It does not execute agent
tools; it emits a deterministic context recommendation that another operator or
agent can inspect before work starts.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULES = REPO_ROOT / "agent-context-rules.json"
DEFAULT_CAPABILITIES = REPO_ROOT / "agilab-capabilities.json"
RULES_SCHEMA = "agilab.agent_context_rules.v1"
RECOMMENDATION_SCHEMA = "agilab.agent_context_recommendation.v1"
VALIDATION_SCHEMA = "agilab.agent_context_rules_validation.v1"


def _rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing JSON file: {_rel(path)}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {_rel(path)}: {exc}") from exc


def _expect_mapping(value: Any, *, path: str, issues: list[dict[str, str]]) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    issues.append({"severity": "error", "path": path, "message": "expected an object"})
    return {}


def _expect_list(value: Any, *, path: str, issues: list[dict[str, str]]) -> list[Any]:
    if isinstance(value, list):
        return value
    issues.append({"severity": "error", "path": path, "message": "expected a list"})
    return []


def _string_list(value: Any, *, path: str, issues: list[dict[str, str]]) -> list[str]:
    values = _expect_list(value, path=path, issues=issues)
    result: list[str] = []
    for index, item in enumerate(values):
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
        else:
            issues.append(
                {
                    "severity": "error",
                    "path": f"{path}[{index}]",
                    "message": "expected a non-empty string",
                }
            )
    return result


def normalize_file(path: str | Path) -> str:
    raw = str(path).strip()
    if not raw:
        return ""
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            return candidate.as_posix()
    return Path(raw).as_posix()


def _matches_any(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _git_changed_files(*, staged: bool, changed: bool) -> list[str]:
    if not staged and not changed:
        return []
    args = ["git", "diff", "--name-only"]
    if staged:
        args.append("--cached")
    elif changed:
        args.append("HEAD")
    args.append("--")
    completed = subprocess.run(
        args,
        cwd=REPO_ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git diff failed")
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def load_skill_index(capabilities_path: Path = DEFAULT_CAPABILITIES) -> dict[str, dict[str, str]]:
    payload = _load_json(capabilities_path)
    if not isinstance(payload, Mapping):
        return {}
    skills: dict[str, dict[str, str]] = {}
    for item in payload.get("agent_skills", []):
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue
        skills[name] = {
            "name": name,
            "path": str(item.get("path") or ""),
            "description": str(item.get("description") or ""),
            "updated": str(item.get("updated") or ""),
        }
    return skills


def validate_rules(
    rules_payload: Mapping[str, Any],
    *,
    skills: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    schema = rules_payload.get("schema")
    if schema != RULES_SCHEMA:
        issues.append(
            {
                "severity": "error",
                "path": "schema",
                "message": f"expected {RULES_SCHEMA!r}, got {schema!r}",
            }
        )
    baseline = _expect_mapping(rules_payload.get("baseline"), path="baseline", issues=issues)
    runbooks = _expect_list(baseline.get("runbooks"), path="baseline.runbooks", issues=issues)
    for index, raw in enumerate(runbooks):
        runbook = _expect_mapping(raw, path=f"baseline.runbooks[{index}]", issues=issues)
        path = runbook.get("path")
        if not isinstance(path, str) or not path.strip():
            issues.append(
                {
                    "severity": "error",
                    "path": f"baseline.runbooks[{index}].path",
                    "message": "expected a non-empty path",
                }
            )
        elif not (REPO_ROOT / path).exists():
            issues.append(
                {
                    "severity": "error",
                    "path": f"baseline.runbooks[{index}].path",
                    "message": f"runbook path does not exist: {path}",
                }
            )
    known_skills = skills or load_skill_index()
    baseline_skills = _string_list(baseline.get("skills"), path="baseline.skills", issues=issues)
    for name in baseline_skills:
        if name not in known_skills:
            issues.append(
                {
                    "severity": "error",
                    "path": "baseline.skills",
                    "message": f"unknown skill: {name}",
                }
            )
    rules = _expect_list(rules_payload.get("rules"), path="rules", issues=issues)
    seen_ids: set[str] = set()
    for index, raw in enumerate(rules):
        rule = _expect_mapping(raw, path=f"rules[{index}]", issues=issues)
        rule_id = rule.get("id")
        if not isinstance(rule_id, str) or not rule_id.strip():
            issues.append(
                {
                    "severity": "error",
                    "path": f"rules[{index}].id",
                    "message": "expected a non-empty rule id",
                }
            )
        elif rule_id in seen_ids:
            issues.append(
                {
                    "severity": "error",
                    "path": f"rules[{index}].id",
                    "message": f"duplicate rule id: {rule_id}",
                }
            )
        else:
            seen_ids.add(rule_id)
        paths = _string_list(rule.get("paths"), path=f"rules[{index}].paths", issues=issues)
        terms = _string_list(rule.get("terms"), path=f"rules[{index}].terms", issues=issues)
        if not paths and not terms:
            issues.append(
                {
                    "severity": "error",
                    "path": f"rules[{index}]",
                    "message": "expected at least one path pattern or prompt term",
                }
            )
        for field in ("label", "reason"):
            value = rule.get(field)
            if not isinstance(value, str) or not value.strip():
                issues.append(
                    {
                        "severity": "error",
                        "path": f"rules[{index}].{field}",
                        "message": "expected a non-empty string",
                    }
                )
        for name in _string_list(rule.get("skills"), path=f"rules[{index}].skills", issues=issues):
            if name not in known_skills:
                issues.append(
                    {
                        "severity": "error",
                        "path": f"rules[{index}].skills",
                        "message": f"unknown skill: {name}",
                    }
                )
    errors = sum(1 for issue in issues if issue["severity"] == "error")
    return {
        "schema": VALIDATION_SCHEMA,
        "status": "fail" if errors else "pass",
        "summary": {"errors": errors, "issues": len(issues), "rules": len(rules)},
        "issues": issues,
    }


def _skill_payload(
    name: str,
    *,
    skills: Mapping[str, Mapping[str, str]],
    sources: Sequence[str],
) -> dict[str, Any]:
    metadata = skills.get(name, {})
    payload: dict[str, Any] = {
        "name": name,
        "path": metadata.get("path", ""),
        "description": metadata.get("description", ""),
        "sources": list(sources),
    }
    updated = metadata.get("updated")
    if updated:
        payload["updated"] = updated
    if not metadata:
        payload["missing_metadata"] = True
    return payload


def recommend_context(
    *,
    files: Sequence[str] = (),
    prompt: str = "",
    rules_path: Path = DEFAULT_RULES,
    skills: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    rules_payload = _load_json(rules_path)
    if not isinstance(rules_payload, Mapping):
        raise ValueError(f"rules root must be a JSON object: {_rel(rules_path)}")
    skill_index = dict(skills or load_skill_index())
    validation = validate_rules(rules_payload, skills=skill_index)
    normalized_files = [item for item in (normalize_file(path) for path in files) if item]
    prompt_text = prompt.strip()
    prompt_lower = prompt_text.lower()
    baseline = _expect_mapping(rules_payload.get("baseline"), path="baseline", issues=[])
    baseline_skills = [item for item in baseline.get("skills", []) if isinstance(item, str)]
    skill_sources: "OrderedDict[str, list[str]]" = OrderedDict((name, ["baseline"]) for name in baseline_skills)
    matched_rules: list[dict[str, Any]] = []
    for raw_rule in rules_payload.get("rules", []):
        if not isinstance(raw_rule, Mapping):
            continue
        paths = [item for item in raw_rule.get("paths", []) if isinstance(item, str)]
        terms = [item for item in raw_rule.get("terms", []) if isinstance(item, str)]
        matched_paths = [path for path in normalized_files if _matches_any(path, paths)]
        matched_terms = [term for term in terms if term.lower() in prompt_lower]
        if not matched_paths and not matched_terms:
            continue
        rule_id = str(raw_rule.get("id") or "")
        rule_skills = [item for item in raw_rule.get("skills", []) if isinstance(item, str)]
        for name in rule_skills:
            source = f"rule:{rule_id}"
            sources = skill_sources.setdefault(name, [])
            if source not in sources:
                sources.append(source)
        matched_rules.append(
            {
                "id": rule_id,
                "label": str(raw_rule.get("label") or ""),
                "reason": str(raw_rule.get("reason") or ""),
                "skills": rule_skills,
                "matched_paths": matched_paths,
                "matched_terms": matched_terms,
            }
        )
    return {
        "schema": RECOMMENDATION_SCHEMA,
        "schema_version": 1,
        "status": "pass" if validation["status"] == "pass" else "rules-invalid",
        "rules_file": _rel(rules_path),
        "rules_schema": rules_payload.get("schema", ""),
        "inputs": {
            "files": normalized_files,
            "prompt": prompt_text,
        },
        "baseline": baseline,
        "matched_rules": matched_rules,
        "recommended_skills": [
            _skill_payload(name, skills=skill_index, sources=sources)
            for name, sources in skill_sources.items()
        ],
        "validation": validation,
    }


def render_text(payload: Mapping[str, Any]) -> str:
    lines = ["AGILAB agent context recommendation"]
    baseline = payload.get("baseline", {})
    if isinstance(baseline, Mapping):
        runbooks = baseline.get("runbooks", [])
        if isinstance(runbooks, list):
            paths = [
                item.get("path")
                for item in runbooks
                if isinstance(item, Mapping) and isinstance(item.get("path"), str)
            ]
            if paths:
                lines.append("Runbooks: " + ", ".join(paths))
    skills = payload.get("recommended_skills", [])
    if isinstance(skills, list):
        names = [item.get("name") for item in skills if isinstance(item, Mapping)]
        if names:
            lines.append("Skills: " + ", ".join(str(name) for name in names))
    matched = payload.get("matched_rules", [])
    if isinstance(matched, list) and matched:
        lines.append("Matched rules:")
        for item in matched:
            if not isinstance(item, Mapping):
                continue
            lines.append(f"- {item.get('id')}: {item.get('label')}")
    else:
        lines.append("Matched rules: none; use the baseline runbooks and skills.")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES, help="Context routing rules JSON.")
    parser.add_argument("--files", nargs="*", default=(), help="Changed or target files to classify.")
    parser.add_argument("--prompt", default="", help="Natural-language task text to classify.")
    parser.add_argument("--staged", action="store_true", help="Include staged git paths.")
    parser.add_argument("--changed", action="store_true", help="Include paths changed against HEAD.")
    parser.add_argument("--check", action="store_true", help="Validate the routing rules and exit.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rules_path = args.rules.expanduser()
    rules_payload = _load_json(rules_path)
    if not isinstance(rules_payload, Mapping):
        raise SystemExit(f"ERROR: rules root must be a JSON object: {_rel(rules_path)}")
    if args.check:
        report = validate_rules(rules_payload)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        elif report["status"] == "pass":
            print(f"OK: {report['summary']['rules']} agent context rule(s) are valid")
        else:
            print("ERROR: agent context rules are invalid", file=sys.stderr)
            for issue in report["issues"]:
                print(f" - {issue['path']}: {issue['message']}", file=sys.stderr)
        return 0 if report["status"] == "pass" else 2
    files = list(args.files)
    files.extend(_git_changed_files(staged=args.staged, changed=args.changed))
    payload = recommend_context(files=files, prompt=args.prompt, rules_path=rules_path)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_text(payload), end="")
    return 0 if payload["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
