#!/usr/bin/env python3
"""Lint AGILAB's generated public capability manifest."""

from __future__ import annotations

import argparse
import copy
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "agilab-capabilities.json"
DEFAULT_SCHEMA = REPO_ROOT / "agilab-capabilities.schema.json"
REPORT_SCHEMA = "agilab.capabilities_lint.v1"
MANIFEST_SCHEMA = "agilab.capabilities.v1"
MANIFEST_SCHEMA_VERSION = 1
MATURITY_VALUES = {
    "live-product-path",
    "local-proof",
    "contract-proof",
    "operator-triggered-live-check",
    "roadmap-boundary",
}
APP_STATUSES = {"PyPI app package", "Release artifact", "Source built-in"}


@dataclass(frozen=True)
class LintIssue:
    severity: str
    rule: str
    path: str
    message: str


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


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _add_issue(
    issues: list[LintIssue],
    *,
    severity: str,
    rule: str,
    path: str,
    message: str,
) -> None:
    issues.append(LintIssue(severity=severity, rule=rule, path=path, message=message))


def _require_keys(
    obj: Mapping[str, Any],
    required: Iterable[str],
    path: str,
    issues: list[LintIssue],
) -> None:
    for key in required:
        if key not in obj:
            _add_issue(
                issues,
                severity="error",
                rule="required-key",
                path=f"{path}.{key}",
                message=f"missing required key {key!r}",
            )


def _expect_non_empty_string(
    value: Any,
    *,
    path: str,
    rule: str,
    issues: list[LintIssue],
) -> None:
    if not _is_non_empty_string(value):
        _add_issue(
            issues,
            severity="error",
            rule=rule,
            path=path,
            message="expected a non-empty string",
        )


def _expect_list(value: Any, *, path: str, issues: list[LintIssue]) -> list[Any]:
    if isinstance(value, list):
        return value
    _add_issue(
        issues,
        severity="error",
        rule="expected-list",
        path=path,
        message="expected a list",
    )
    return []


def _expect_mapping(value: Any, *, path: str, issues: list[LintIssue]) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    _add_issue(
        issues,
        severity="error",
        rule="expected-object",
        path=path,
        message="expected an object",
    )
    return {}


def _repo_path_exists(relative_path: Any) -> bool:
    return _is_non_empty_string(relative_path) and (REPO_ROOT / str(relative_path)).exists()


def _check_unique(
    rows: list[Any],
    *,
    key: str,
    path: str,
    issues: list[LintIssue],
) -> None:
    seen: dict[Any, int] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        value = row.get(key)
        if value in seen:
            _add_issue(
                issues,
                severity="error",
                rule="unique-key",
                path=f"{path}[{index}].{key}",
                message=f"duplicate {key!r} value {value!r}; first seen at {path}[{seen[value]}]",
            )
        else:
            seen[value] = index


def lint_manifest(
    manifest: Mapping[str, Any],
    schema_contract: Mapping[str, Any],
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    schema_path: Path = DEFAULT_SCHEMA,
) -> dict[str, Any]:
    issues: list[LintIssue] = []
    _lint_schema_contract(schema_contract, schema_path=schema_path, issues=issues)
    _lint_manifest_contract(manifest, manifest_path=manifest_path, schema_path=schema_path, issues=issues)
    errors = sum(1 for issue in issues if issue.severity == "error")
    warnings = sum(1 for issue in issues if issue.severity == "warning")
    return {
        "schema": REPORT_SCHEMA,
        "status": "fail" if errors else "pass",
        "manifest": _rel(manifest_path),
        "schema_file": _rel(schema_path),
        "summary": {
            "issue_count": len(issues),
            "error_count": errors,
            "warning_count": warnings,
        },
        "issues": [asdict(issue) for issue in issues],
    }


def lint_files(
    manifest_path: Path = DEFAULT_MANIFEST,
    schema_path: Path = DEFAULT_SCHEMA,
) -> dict[str, Any]:
    manifest = _expect_root_mapping(_load_json(manifest_path), manifest_path)
    schema_contract = _expect_root_mapping(_load_json(schema_path), schema_path)
    return lint_manifest(
        manifest,
        schema_contract,
        manifest_path=manifest_path,
        schema_path=schema_path,
    )


def _expect_root_mapping(payload: Any, path: Path) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{_rel(path)} must contain a JSON object")
    return payload


def _lint_schema_contract(
    schema_contract: Mapping[str, Any],
    *,
    schema_path: Path,
    issues: list[LintIssue],
) -> None:
    required = schema_contract.get("required")
    properties = schema_contract.get("properties")
    defs = schema_contract.get("$defs")

    if schema_contract.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        _add_issue(
            issues,
            severity="error",
            rule="schema-draft",
            path="$schema",
            message="capability schema must use JSON Schema draft 2020-12",
        )
    if schema_contract.get("properties", {}).get("schema", {}).get("const") != MANIFEST_SCHEMA:
        _add_issue(
            issues,
            severity="error",
            rule="schema-const",
            path="properties.schema.const",
            message=f"schema file must constrain manifest schema to {MANIFEST_SCHEMA!r}",
        )
    if schema_contract.get("properties", {}).get("schema_version", {}).get("const") != MANIFEST_SCHEMA_VERSION:
        _add_issue(
            issues,
            severity="error",
            rule="schema-version-const",
            path="properties.schema_version.const",
            message=f"schema file must constrain schema_version to {MANIFEST_SCHEMA_VERSION}",
        )
    if not isinstance(required, list) or not {"cli_commands", "packages", "public_apps"}.issubset(required):
        _add_issue(
            issues,
            severity="error",
            rule="schema-required-surface",
            path="required",
            message="schema must require the main public surface collections",
        )
    if not isinstance(properties, Mapping):
        _add_issue(
            issues,
            severity="error",
            rule="schema-properties",
            path="properties",
            message="schema must declare top-level properties",
        )
    if not isinstance(defs, Mapping) or not {"CliCommand", "EvidenceSchema", "PublicApp"}.issubset(defs):
        _add_issue(
            issues,
            severity="error",
            rule="schema-definitions",
            path="$defs",
            message="schema must define CLI, evidence schema, and public app entry contracts",
        )
    if not schema_path.exists():
        _add_issue(
            issues,
            severity="error",
            rule="schema-file-exists",
            path=_rel(schema_path),
            message="schema file is missing",
        )


def _lint_manifest_contract(
    manifest: Mapping[str, Any],
    *,
    manifest_path: Path,
    schema_path: Path,
    issues: list[LintIssue],
) -> None:
    _require_keys(
        manifest,
        (
            "schema",
            "schema_version",
            "generated_by",
            "source",
            "boundary",
            "summary",
            "cli_commands",
            "streamlit_pages",
            "packages",
            "public_apps",
            "agent_skills",
            "evidence_schemas",
            "catalog_files",
            "docs",
        ),
        "$",
        issues,
    )
    if manifest.get("schema") != MANIFEST_SCHEMA:
        _add_issue(
            issues,
            severity="error",
            rule="manifest-schema",
            path="schema",
            message=f"expected {MANIFEST_SCHEMA!r}",
        )
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        _add_issue(
            issues,
            severity="error",
            rule="manifest-schema-version",
            path="schema_version",
            message=f"expected {MANIFEST_SCHEMA_VERSION}",
        )

    _lint_generated_by(_expect_mapping(manifest.get("generated_by"), path="generated_by", issues=issues), issues)
    _lint_source(_expect_mapping(manifest.get("source"), path="source", issues=issues), issues)
    _lint_boundary(_expect_mapping(manifest.get("boundary"), path="boundary", issues=issues), issues)

    cli_commands = _expect_list(manifest.get("cli_commands"), path="cli_commands", issues=issues)
    streamlit_pages = _expect_list(manifest.get("streamlit_pages"), path="streamlit_pages", issues=issues)
    packages = _expect_list(manifest.get("packages"), path="packages", issues=issues)
    public_apps = _expect_list(manifest.get("public_apps"), path="public_apps", issues=issues)
    agent_skills = _expect_list(manifest.get("agent_skills"), path="agent_skills", issues=issues)
    evidence_schemas = _expect_list(manifest.get("evidence_schemas"), path="evidence_schemas", issues=issues)
    catalog_files = _expect_list(manifest.get("catalog_files"), path="catalog_files", issues=issues)
    docs = _expect_list(manifest.get("docs"), path="docs", issues=issues)

    _lint_summary(
        _expect_mapping(manifest.get("summary"), path="summary", issues=issues),
        {
            "cli_command_count": len(cli_commands),
            "streamlit_page_count": len(streamlit_pages),
            "package_count": len(packages),
            "public_app_count": len(public_apps),
            "agent_skill_count": len(agent_skills),
            "evidence_schema_count": len(evidence_schemas),
            "catalog_file_count": len(catalog_files),
        },
        issues,
    )

    schema_names = {
        row.get("schema")
        for row in evidence_schemas
        if isinstance(row, Mapping) and _is_non_empty_string(row.get("schema"))
    }
    package_names = {
        row.get("name")
        for row in packages
        if isinstance(row, Mapping) and _is_non_empty_string(row.get("name"))
    }

    _lint_cli_commands(cli_commands, schema_names=schema_names, issues=issues)
    _lint_streamlit_pages(streamlit_pages, issues)
    _lint_packages(packages, issues)
    _lint_public_apps(public_apps, package_names=package_names, issues=issues)
    _lint_agent_skills(agent_skills, issues)
    _lint_evidence_schemas(evidence_schemas, issues)
    _lint_catalog_files(catalog_files, manifest_path=manifest_path, schema_path=schema_path, issues=issues)
    _lint_docs(docs, issues)


def _lint_generated_by(row: Mapping[str, Any], issues: list[LintIssue]) -> None:
    _expect_non_empty_string(row.get("tool"), path="generated_by.tool", rule="generated-tool", issues=issues)
    _expect_non_empty_string(row.get("command"), path="generated_by.command", rule="generated-command", issues=issues)
    tool = row.get("tool")
    command = row.get("command")
    if _is_non_empty_string(tool) and not _repo_path_exists(tool):
        _add_issue(
            issues,
            severity="error",
            rule="generated-tool-exists",
            path="generated_by.tool",
            message=f"generator tool does not exist: {tool}",
        )
    if _is_non_empty_string(tool) and _is_non_empty_string(command) and str(tool) not in str(command):
        _add_issue(
            issues,
            severity="warning",
            rule="generated-command-references-tool",
            path="generated_by.command",
            message="generator command should reference the generator tool path",
        )


def _lint_source(row: Mapping[str, Any], issues: list[LintIssue]) -> None:
    for key in ("repository", "documentation", "project", "version"):
        _expect_non_empty_string(row.get(key), path=f"source.{key}", rule="source-field", issues=issues)
    for key in ("repository", "documentation"):
        value = row.get(key)
        if _is_non_empty_string(value) and not str(value).startswith("https://"):
            _add_issue(
                issues,
                severity="error",
                rule="source-https",
                path=f"source.{key}",
                message="public source URL must use https",
            )


def _lint_boundary(row: Mapping[str, Any], issues: list[LintIssue]) -> None:
    for key in ("proves", "does_not_prove"):
        _expect_non_empty_string(row.get(key), path=f"boundary.{key}", rule="boundary-field", issues=issues)
    does_not_prove = str(row.get("does_not_prove", "")).lower()
    for phrase in ("runtime success", "production readiness", "security certification"):
        if phrase not in does_not_prove:
            _add_issue(
                issues,
                severity="error",
                rule="boundary-limit",
                path="boundary.does_not_prove",
                message=f"boundary must explicitly exclude {phrase}",
            )


def _lint_summary(
    summary: Mapping[str, Any],
    expected_counts: Mapping[str, int],
    issues: list[LintIssue],
) -> None:
    for key, expected in expected_counts.items():
        actual = summary.get(key)
        if actual != expected:
            _add_issue(
                issues,
                severity="error",
                rule="summary-count",
                path=f"summary.{key}",
                message=f"expected {expected}, found {actual!r}",
            )


def _lint_cli_commands(
    rows: list[Any],
    *,
    schema_names: set[Any],
    issues: list[LintIssue],
) -> None:
    _check_unique(rows, key="id", path="cli_commands", issues=issues)
    for index, raw_row in enumerate(rows):
        row = _expect_mapping(raw_row, path=f"cli_commands[{index}]", issues=issues)
        path = f"cli_commands[{index}]"
        for key in ("id", "command", "kind", "maturity", "description"):
            _expect_non_empty_string(row.get(key), path=f"{path}.{key}", rule="cli-command-field", issues=issues)
        if row.get("maturity") not in MATURITY_VALUES:
            _add_issue(
                issues,
                severity="error",
                rule="cli-maturity",
                path=f"{path}.maturity",
                message=f"unknown maturity value {row.get('maturity')!r}",
            )
        _lint_doc_paths(_expect_list(row.get("docs"), path=f"{path}.docs", issues=issues), path=f"{path}.docs", issues=issues)
        outputs = _expect_list(row.get("evidence_outputs"), path=f"{path}.evidence_outputs", issues=issues)
        for output_index, output in enumerate(outputs):
            if not _is_non_empty_string(output):
                _add_issue(
                    issues,
                    severity="error",
                    rule="cli-evidence-output",
                    path=f"{path}.evidence_outputs[{output_index}]",
                    message="evidence output must be a non-empty string",
                )
                continue
            if str(output).startswith("agilab.") and output not in schema_names:
                _add_issue(
                    issues,
                    severity="error",
                    rule="cli-evidence-schema-source",
                    path=f"{path}.evidence_outputs[{output_index}]",
                    message=f"evidence schema {output!r} is not listed in evidence_schemas",
                )


def _lint_streamlit_pages(rows: list[Any], issues: list[LintIssue]) -> None:
    _check_unique(rows, key="title", path="streamlit_pages", issues=issues)
    _check_unique(rows, key="url_path", path="streamlit_pages", issues=issues)
    for index, raw_row in enumerate(rows):
        row = _expect_mapping(raw_row, path=f"streamlit_pages[{index}]", issues=issues)
        path = f"streamlit_pages[{index}]"
        for key in ("title", "source", "purpose"):
            _expect_non_empty_string(row.get(key), path=f"{path}.{key}", rule="streamlit-page-field", issues=issues)
        if not isinstance(row.get("visible_in_nav"), bool):
            _add_issue(
                issues,
                severity="error",
                rule="streamlit-visible-bool",
                path=f"{path}.visible_in_nav",
                message="visible_in_nav must be a boolean",
            )
        _lint_existing_path(row, path=path, path_key="source", issues=issues)
        if row.get("exists") is not True:
            _add_issue(
                issues,
                severity="error",
                rule="streamlit-source-exists-flag",
                path=f"{path}.exists",
                message="streamlit page source must be marked as existing",
            )


def _lint_packages(rows: list[Any], issues: list[LintIssue]) -> None:
    _check_unique(rows, key="name", path="packages", issues=issues)
    for index, raw_row in enumerate(rows):
        row = _expect_mapping(raw_row, path=f"packages[{index}]", issues=issues)
        path = f"packages[{index}]"
        for key in ("name", "role", "status", "version", "description", "pyproject"):
            _expect_non_empty_string(row.get(key), path=f"{path}.{key}", rule="package-field", issues=issues)
        _lint_existing_path(row, path=path, path_key="pyproject", issues=issues)
        project = row.get("project")
        if _is_non_empty_string(project) and project != "." and not _repo_path_exists(project):
            _add_issue(
                issues,
                severity="error",
                rule="package-project-exists",
                path=f"{path}.project",
                message=f"package project path does not exist: {project}",
            )


def _lint_public_apps(
    rows: list[Any],
    *,
    package_names: set[Any],
    issues: list[LintIssue],
) -> None:
    _check_unique(rows, key="project", path="public_apps", issues=issues)
    for index, raw_row in enumerate(rows):
        row = _expect_mapping(raw_row, path=f"public_apps[{index}]", issues=issues)
        path = f"public_apps[{index}]"
        for key in ("project", "status", "source", "version", "description"):
            _expect_non_empty_string(row.get(key), path=f"{path}.{key}", rule="public-app-field", issues=issues)
        status = row.get("status")
        package = row.get("package")
        if status not in APP_STATUSES:
            _add_issue(
                issues,
                severity="error",
                rule="public-app-status",
                path=f"{path}.status",
                message=f"unknown public app status {status!r}",
            )
        if status in {"PyPI app package", "Release artifact"}:
            if not _is_non_empty_string(package):
                _add_issue(
                    issues,
                    severity="error",
                    rule="public-app-package-required",
                    path=f"{path}.package",
                    message=f"{status} apps must declare a package",
                )
            elif package not in package_names:
                _add_issue(
                    issues,
                    severity="error",
                    rule="public-app-package-known",
                    path=f"{path}.package",
                    message=f"package {package!r} is not listed in packages",
                )
        if status == "Source built-in" and package is not None:
            _add_issue(
                issues,
                severity="error",
                rule="source-built-in-package-none",
                path=f"{path}.package",
                message="source built-in apps must not declare a package",
            )
        _lint_existing_path(row, path=path, path_key="source", issues=issues)


def _lint_agent_skills(rows: list[Any], issues: list[LintIssue]) -> None:
    _check_unique(rows, key="name", path="agent_skills", issues=issues)
    for index, raw_row in enumerate(rows):
        row = _expect_mapping(raw_row, path=f"agent_skills[{index}]", issues=issues)
        path = f"agent_skills[{index}]"
        for key in ("name", "description", "path"):
            _expect_non_empty_string(row.get(key), path=f"{path}.{key}", rule="agent-skill-field", issues=issues)
        _lint_existing_path(row, path=path, path_key="path", issues=issues)


def _lint_evidence_schemas(rows: list[Any], issues: list[LintIssue]) -> None:
    _check_unique(rows, key="schema", path="evidence_schemas", issues=issues)
    for index, raw_row in enumerate(rows):
        row = _expect_mapping(raw_row, path=f"evidence_schemas[{index}]", issues=issues)
        path = f"evidence_schemas[{index}]"
        schema = row.get("schema")
        _expect_non_empty_string(schema, path=f"{path}.schema", rule="evidence-schema-field", issues=issues)
        if _is_non_empty_string(schema) and not str(schema).startswith("agilab."):
            _add_issue(
                issues,
                severity="error",
                rule="evidence-schema-prefix",
                path=f"{path}.schema",
                message="evidence schema must use the agilab.* namespace",
            )
        for source_index, source in enumerate(_expect_list(row.get("sources"), path=f"{path}.sources", issues=issues)):
            if not _repo_path_exists(source):
                _add_issue(
                    issues,
                    severity="error",
                    rule="evidence-schema-source-exists",
                    path=f"{path}.sources[{source_index}]",
                    message=f"evidence schema source does not exist: {source!r}",
                )


def _lint_catalog_files(
    rows: list[Any],
    *,
    manifest_path: Path,
    schema_path: Path,
    issues: list[LintIssue],
) -> None:
    _check_unique(rows, key="path", path="catalog_files", issues=issues)
    catalog_paths: set[Any] = set()
    for index, raw_row in enumerate(rows):
        row = _expect_mapping(raw_row, path=f"catalog_files[{index}]", issues=issues)
        path = f"catalog_files[{index}]"
        catalog_paths.add(row.get("path"))
        for key in ("path", "kind", "description"):
            _expect_non_empty_string(row.get(key), path=f"{path}.{key}", rule="catalog-file-field", issues=issues)
        _lint_existing_path(row, path=path, path_key="path", issues=issues)
        if row.get("exists") is not True:
            _add_issue(
                issues,
                severity="error",
                rule="catalog-file-exists-flag",
                path=f"{path}.exists",
                message="catalog file must be marked as existing",
            )
    for required_path, label in (
        (_rel(manifest_path), "manifest"),
        (_rel(schema_path), "schema"),
    ):
        if required_path not in catalog_paths:
            _add_issue(
                issues,
                severity="error",
                rule="catalog-required-file",
                path="catalog_files",
                message=f"catalog files must list the capability {label}: {required_path}",
            )


def _lint_docs(rows: list[Any], issues: list[LintIssue]) -> None:
    _check_unique(rows, key="path", path="docs", issues=issues)
    for index, raw_row in enumerate(rows):
        row = _expect_mapping(raw_row, path=f"docs[{index}]", issues=issues)
        path = f"docs[{index}]"
        for key in ("path", "title", "description"):
            _expect_non_empty_string(row.get(key), path=f"{path}.{key}", rule="doc-field", issues=issues)
        _lint_existing_path(row, path=path, path_key="path", issues=issues)
        if row.get("exists") is not True:
            _add_issue(
                issues,
                severity="error",
                rule="doc-exists-flag",
                path=f"{path}.exists",
                message="documentation entry must be marked as existing",
            )


def _lint_doc_paths(paths: list[Any], *, path: str, issues: list[LintIssue]) -> None:
    for index, doc_path in enumerate(paths):
        if not _repo_path_exists(doc_path):
            _add_issue(
                issues,
                severity="error",
                rule="doc-path-exists",
                path=f"{path}[{index}]",
                message=f"documentation path does not exist: {doc_path!r}",
            )


def _lint_existing_path(
    row: Mapping[str, Any],
    *,
    path: str,
    path_key: str,
    issues: list[LintIssue],
) -> None:
    value = row.get(path_key)
    if not _repo_path_exists(value):
        _add_issue(
            issues,
            severity="error",
            rule="repo-path-exists",
            path=f"{path}.{path_key}",
            message=f"path does not exist in repository: {value!r}",
        )


def mutated_manifest(payload: Mapping[str, Any], *path: str, value: Any) -> dict[str, Any]:
    """Return a deep-copied manifest with one nested field replaced for tests."""
    clone = copy.deepcopy(dict(payload))
    cursor: Any = clone
    for key in path[:-1]:
        cursor = cursor[int(key)] if isinstance(cursor, list) else cursor[key]
    final_key = path[-1]
    if isinstance(cursor, list):
        cursor[int(final_key)] = value
    else:
        cursor[final_key] = value
    return clone


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--check", action="store_true", help="Fail when lint issues are found.")
    parser.add_argument("--json", action="store_true", help="Print the full JSON lint report.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest_path = args.manifest if args.manifest.is_absolute() else REPO_ROOT / args.manifest
    schema_path = args.schema if args.schema.is_absolute() else REPO_ROOT / args.schema
    try:
        report = lint_files(manifest_path=manifest_path, schema_path=schema_path)
    except ValueError as exc:
        report = {
            "schema": REPORT_SCHEMA,
            "status": "fail",
            "manifest": _rel(manifest_path),
            "schema_file": _rel(schema_path),
            "summary": {"issue_count": 1, "error_count": 1, "warning_count": 0},
            "issues": [
                {
                    "severity": "error",
                    "rule": "load-json",
                    "path": _rel(manifest_path),
                    "message": str(exc),
                }
            ],
        }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        status = report["status"]
        summary = report["summary"]
        print(
            f"{status}: {summary['error_count']} error(s), "
            f"{summary['warning_count']} warning(s) in {report['manifest']}"
        )
        for issue in report["issues"]:
            print(f"- {issue['severity']} {issue['rule']} {issue['path']}: {issue['message']}")
    if args.check and report["status"] != "pass":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
