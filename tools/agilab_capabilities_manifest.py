#!/usr/bin/env python3
"""Generate AGILAB's public machine-readable capability manifest."""

from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on older local python3 launchers.
    tomllib = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "agilab-capabilities.json"
SCHEMA = "agilab.capabilities.v1"
SCHEMA_VERSION = 1

SCHEMA_SCAN_ROOTS = (
    REPO_ROOT / "src" / "agilab",
    REPO_ROOT / "tools",
    REPO_ROOT / "docs" / "source",
)
SCHEMA_SCAN_FILES = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "README.pypi.md",
    REPO_ROOT / "AGENT_SKILLS.md",
    REPO_ROOT / "agent-context-rules.json",
    REPO_ROOT / "agenticweb.md",
    REPO_ROOT / "llms.txt",
    REPO_ROOT / "llms-full.txt",
)
SCHEMA_SCAN_SUFFIXES = (
    ".py",
    ".rst",
    ".md",
    ".toml",
    ".json",
    ".txt",
)
SCHEMA_SCAN_SKIP_DIRS = (
    ".eggs",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
)
SCHEMA_PATTERN = re.compile(r"\bagilab[._-][A-Za-z0-9_.-]+\.v1\b")

CLI_COMMANDS: tuple[dict[str, Any], ...] = (
    {
        "id": "ui",
        "command": "agilab",
        "kind": "streamlit-ui",
        "maturity": "live-product-path",
        "description": "Launch the local Streamlit workbench.",
        "docs": ["docs/source/quick-start.rst", "docs/source/agilab-help.rst"],
        "evidence_outputs": [],
    },
    {
        "id": "first-proof",
        "command": "agilab first-proof --json",
        "aliases": ["agilab dry-run"],
        "kind": "proof",
        "maturity": "local-proof",
        "description": "Run the packaged first proof and emit install/run evidence.",
        "docs": ["docs/source/quick-start.rst", "docs/source/release-proof.rst"],
        "evidence_outputs": ["run_manifest.json"],
    },
    {
        "id": "workflow-validate",
        "command": "agilab workflow validate <lab_stages.toml> --dry-run --json",
        "kind": "workflow-contract",
        "maturity": "contract-proof",
        "description": "Validate stage, dependency, role, artifact-flow, and app-reference contracts without executing user code.",
        "docs": ["docs/source/capability-map.rst", "docs/source/features.rst"],
        "evidence_outputs": ["agilab.workflow_dry_run_report.v1"],
    },
    {
        "id": "agent-run",
        "command": "agilab agent-run ...",
        "kind": "agent-evidence",
        "maturity": "live-product-path",
        "description": "Wrap coding-agent actions with redacted manifests, traces, and local artifact pointers.",
        "docs": ["docs/source/agent-workflows.rst"],
        "evidence_outputs": [
            "agilab.agent_run.v1",
            "agilab.agent_trace.v1",
        ],
    },
    {
        "id": "agent-context-router",
        "command": "python3 tools/agent_context_router.py --files <paths> --prompt <task> --json",
        "kind": "agent-context",
        "maturity": "contract-proof",
        "description": "Recommend AGILAB runbooks and repo-managed skills from changed files or task text without executing agent tools.",
        "docs": ["docs/source/agent-workflows.rst"],
        "evidence_outputs": ["agilab.agent_context_recommendation.v1"],
    },
    {
        "id": "agenticweb-manifest",
        "command": "python3 tools/agenticweb_manifest.py --check",
        "kind": "agent-discovery",
        "maturity": "contract-proof",
        "description": "Validate the generated root agenticweb.md discovery file against the AGILAB capability manifest.",
        "docs": ["docs/source/agent-workflows.rst", "docs/source/capability-map.rst"],
        "evidence_outputs": ["agilab.agenticweb_discovery.v1"],
    },
    {
        "id": "agent-instruction-contract",
        "command": "python3 tools/agent_instruction_contract.py --check",
        "kind": "agent-runbook-contract",
        "maturity": "contract-proof",
        "description": "Validate that root agent runbooks, public agent docs, and discovery manifests describe the same executable contract.",
        "docs": ["docs/source/agent-workflows.rst"],
        "evidence_outputs": ["agilab.agent_instruction_contract.v1"],
    },
    {
        "id": "security-check",
        "command": "agilab security-check --json --strict",
        "kind": "security-posture",
        "maturity": "contract-proof",
        "description": "Inspect local AGILAB safety posture and fail on strict adoption blockers.",
        "docs": ["docs/source/security-adoption.rst"],
        "evidence_outputs": ["security check JSON report"],
    },
    {
        "id": "proof-capsule",
        "command": "agilab prove|verify|sign|replay|export-lineage|policy-check|cards|metadata-store ...",
        "kind": "evidence-core",
        "maturity": "live-product-path",
        "description": "Create, inspect, replay, and package run evidence and proof capsules.",
        "docs": ["docs/source/proof-capsule.rst", "docs/source/advanced-proof-pack.rst"],
        "evidence_outputs": [
            "agilab.proof_capsule.v1",
            ".agipack",
            "lineage export",
            "policy report",
        ],
    },
    {
        "id": "app-surface",
        "command": "agilab app surface <project> --ui <backend>",
        "kind": "app-ui-surface",
        "maturity": "live-product-path",
        "description": "Launch an app-declared UI surface through the generic app surface route.",
        "docs": ["docs/source/public-app-catalog.rst", "docs/source/pytorch-playground.rst"],
        "evidence_outputs": ["app surface metadata"],
    },
)

STREAMLIT_PAGES: tuple[dict[str, Any], ...] = (
    {
        "title": "ABOUT",
        "url_path": "",
        "source": "src/agilab/main_page.py",
        "visible_in_nav": False,
        "purpose": "product overview, first-proof wizard, and entry routing",
    },
    {
        "title": "SETTINGS",
        "url_path": "SETTINGS",
        "source": "src/agilab/pages/0_SETTINGS.py",
        "visible_in_nav": False,
        "purpose": "runtime diagnostics and local environment settings",
    },
    {
        "title": "PROJECT",
        "url_path": "PROJECT",
        "source": "src/agilab/pages/1_PROJECT.py",
        "visible_in_nav": False,
        "purpose": "project selection, creation, import, export, and package updates",
    },
    {
        "title": "ORCHESTRATE",
        "url_path": "ORCHESTRATE",
        "source": "src/agilab/pages/2_ORCHESTRATE.py",
        "visible_in_nav": True,
        "purpose": "install, execute, cluster/service controls, and run evidence",
    },
    {
        "title": "WORKFLOW",
        "url_path": "WORKFLOW",
        "source": "src/agilab/pages/3_WORKFLOW.py",
        "visible_in_nav": True,
        "purpose": "stage contract, pipeline view, notebook import/export, and dry-run evidence",
    },
    {
        "title": "ANALYSIS",
        "url_path": "ANALYSIS",
        "source": "src/agilab/pages/4_ANALYSIS.py",
        "visible_in_nav": True,
        "purpose": "analysis views, artifacts, evidence graphs, and app surfaces",
    },
)

CATALOG_FILES: tuple[dict[str, str], ...] = (
    {
        "path": "AGENTS.md",
        "kind": "agent-runbook",
        "description": "full AGILAB operator runbook for coding agents and maintainers",
    },
    {
        "path": "AGENT_CONVENTIONS.md",
        "kind": "agent-runbook",
        "description": "short local-agent contract for tools with smaller context windows",
    },
    {
        "path": "tools/agent_workflows.md",
        "kind": "agent-workflow-runbook",
        "description": "developer workflow reference for repo-supported coding agents",
    },
    {
        "path": "AGENT_SKILLS.md",
        "kind": "agent-skill-catalog",
        "description": "human-readable repo-managed agent skills catalog",
    },
    {
        "path": "llms.txt",
        "kind": "agent-docs-index",
        "description": "compact LLM/scraper entry-point index",
    },
    {
        "path": "llms-full.txt",
        "kind": "agent-docs-index",
        "description": "expanded LLM/scraper skill index",
    },
    {
        "path": "agilab-capabilities.json",
        "kind": "capability-manifest",
        "description": "machine-readable inventory of shipped public AGILAB surfaces",
    },
    {
        "path": "agilab-capabilities.schema.json",
        "kind": "capability-schema",
        "description": "JSON Schema contract for the public AGILAB capability manifest",
    },
    {
        "path": "agilab-capability-rules.yml",
        "kind": "capability-rules",
        "description": "declarative semantic rule metadata for the public AGILAB capability manifest linter",
    },
    {
        "path": "agent-context-rules.json",
        "kind": "agent-context-rules",
        "description": "declarative file and prompt rules for AGILAB agent runbook and skill routing",
    },
    {
        "path": "agenticweb.md",
        "kind": "agenticweb-discovery",
        "description": "generated agenticweb.md discovery file for AI-agent capability discovery",
    },
)

KEY_DOCS: tuple[dict[str, str], ...] = (
    {
        "path": "docs/source/capability-map.rst",
        "title": "Capability map",
        "description": "job-to-route map with evidence and maturity boundaries",
    },
    {
        "path": "docs/source/features.rst",
        "title": "Features",
        "description": "inventory of shipped capability families",
    },
    {
        "path": "docs/source/public-app-catalog.rst",
        "title": "Public app catalog",
        "description": "public app project/package/status mapping",
    },
    {
        "path": "docs/source/release-proof.rst",
        "title": "Release proof",
        "description": "current release evidence contract",
    },
    {
        "path": "docs/source/proof-capsule.rst",
        "title": "Proof capsule",
        "description": "proof, replay, lineage, policy, and capsule commands",
    },
    {
        "path": "docs/source/agent-workflows.rst",
        "title": "Agent workflows",
        "description": "coding-agent run evidence and repo workflow guidance",
    },
)


def _rel(path: Path, *, root: Path = REPO_ROOT) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _read_pyproject(path: Path) -> dict[str, Any]:
    if tomllib is not None:
        with path.open("rb") as handle:
            payload = tomllib.load(handle)
        return payload if isinstance(payload, dict) else {}
    return {"project": _read_project_table_fallback(path)}


def _read_project_table_fallback(path: Path) -> dict[str, str]:
    metadata: dict[str, str] = {}
    in_project = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line == "[project]":
            in_project = True
            continue
        if in_project and line.startswith("[") and line.endswith("]"):
            break
        if not in_project or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if key not in {"name", "version", "description"}:
            continue
        value = raw_value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            metadata[key] = value[1:-1]
    return metadata


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _package_split_contract():
    return _load_module(
        "agilab_capability_package_split_contract",
        REPO_ROOT / "tools" / "package_split_contract.py",
    )


def _codex_skills_module():
    return _load_module(
        "agilab_capability_codex_skills",
        REPO_ROOT / "tools" / "codex_skills.py",
    )


def _resolve_project_name(package_path: Path) -> str | None:
    project_paths = sorted(package_path.glob("src/*/project/*_project/pyproject.toml"))
    if project_paths:
        return project_paths[0].parent.name

    provider_inits = sorted(package_path.glob("src/*/__init__.py"))
    for provider_init in provider_inits:
        for line in provider_init.read_text(encoding="utf-8").splitlines():
            if line.startswith("PROJECT_NAME"):
                return line.split("=", 1)[1].strip().strip("'\"")
    return None


def collect_packages() -> list[dict[str, Any]]:
    contract = _package_split_contract()
    promoted_apps = set(contract.PROMOTED_APP_PROJECT_PACKAGE_NAMES)
    packages: list[dict[str, Any]] = []
    for package in contract.PACKAGE_CONTRACTS:
        pyproject_path = REPO_ROOT / package.pyproject
        metadata = _read_pyproject(pyproject_path).get("project", {}) if pyproject_path.exists() else {}
        status = "PyPI package"
        if package.role == "app-project":
            status = "PyPI app package" if package.name in promoted_apps else "Release artifact"
        packages.append(
            {
                "name": package.name,
                "role": package.role,
                "status": status,
                "version": metadata.get("version"),
                "description": metadata.get("description"),
                "project": package.project,
                "pyproject": package.pyproject,
                "pypi_environment": package.pypi_environment,
                "artifact_policy": package.artifact_policy,
            }
        )
    return packages


def collect_public_apps() -> list[dict[str, Any]]:
    contract = _package_split_contract()
    promoted_apps = set(contract.PROMOTED_APP_PROJECT_PACKAGE_NAMES)
    apps: dict[str, dict[str, Any]] = {}

    for package_name, package_project in contract.APP_PROJECT_PACKAGE_SPECS:
        package_path = REPO_ROOT / package_project
        project_name = _resolve_project_name(package_path)
        if not project_name:
            continue
        metadata = _read_pyproject(package_path / "pyproject.toml").get("project", {})
        apps[project_name] = {
            "project": project_name,
            "package": package_name,
            "status": "PyPI app package" if package_name in promoted_apps else "Release artifact",
            "source": package_project,
            "version": metadata.get("version"),
            "description": metadata.get("description"),
        }

    builtin_root = REPO_ROOT / "src" / "agilab" / "apps" / "builtin"
    for project_path in sorted(builtin_root.glob("*_project")):
        if not project_path.is_dir():
            continue
        metadata = _read_pyproject(project_path / "pyproject.toml").get("project", {})
        apps.setdefault(
            project_path.name,
            {
                "project": project_path.name,
                "package": None,
                "status": "Source built-in",
                "source": _rel(project_path),
                "version": metadata.get("version"),
                "description": metadata.get("description"),
            },
        )

    return [apps[name] for name in sorted(apps)]


def collect_streamlit_pages() -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for page in STREAMLIT_PAGES:
        source = REPO_ROOT / str(page["source"])
        row = dict(page)
        row["exists"] = source.exists()
        pages.append(row)
    return pages


def collect_agent_skills() -> list[dict[str, Any]]:
    module = _codex_skills_module()
    skills, issues = module.collect_skills(REPO_ROOT / ".claude" / "skills")
    if issues:
        joined = "\n".join(f"- {issue}" for issue in issues)
        raise RuntimeError(f"cannot collect agent skills:\n{joined}")
    rows: list[dict[str, Any]] = []
    for skill in sorted(skills, key=lambda item: item.name.lower()):
        rows.append(
            {
                "name": skill.name,
                "description": skill.description,
                "path": _rel(skill.path),
                "updated": skill.updated,
            }
        )
    return rows


def _iter_schema_sources() -> Iterable[Path]:
    seen: set[Path] = set()
    for root in SCHEMA_SCAN_ROOTS:
        for path in _walk_source_files(root):
            if path in seen:
                continue
            seen.add(path)
            yield path
    for path in SCHEMA_SCAN_FILES:
        if path.exists() and path.is_file() and path not in seen:
            seen.add(path)
            yield path


def _walk_source_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            dirname for dirname in dirnames if dirname not in SCHEMA_SCAN_SKIP_DIRS
        )
        current_dir = Path(dirpath)
        for filename in sorted(filenames):
            path = current_dir / filename
            if path.suffix in SCHEMA_SCAN_SUFFIXES:
                yield path


def collect_evidence_schemas() -> list[dict[str, Any]]:
    by_schema: dict[str, set[str]] = {}
    for path in _iter_schema_sources():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in SCHEMA_PATTERN.findall(text):
            by_schema.setdefault(match, set()).add(_rel(path))
    return [
        {"schema": schema, "sources": sorted(sources)}
        for schema, sources in sorted(by_schema.items())
    ]


def _existing_catalog_files() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in CATALOG_FILES:
        path = REPO_ROOT / item["path"]
        row: dict[str, Any] = dict(item)
        row["exists"] = path.exists() or path == DEFAULT_OUTPUT
        rows.append(row)
    return rows


def _existing_docs() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in KEY_DOCS:
        path = REPO_ROOT / item["path"]
        row: dict[str, Any] = dict(item)
        row["exists"] = path.exists()
        rows.append(row)
    return rows


def _base_manifest() -> dict[str, Any]:
    packages = collect_packages()
    apps = collect_public_apps()
    pages = collect_streamlit_pages()
    skills = collect_agent_skills()
    schemas = collect_evidence_schemas()
    cli_commands = [dict(command) for command in CLI_COMMANDS]
    project_metadata = _read_pyproject(REPO_ROOT / "pyproject.toml").get("project", {})

    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "generated_by": {
            "tool": "tools/agilab_capabilities_manifest.py",
            "command": "python3 tools/agilab_capabilities_manifest.py --apply",
        },
        "source": {
            "repository": "https://github.com/ThalesGroup/agilab",
            "documentation": "https://thalesgroup.github.io/agilab/",
            "project": project_metadata.get("name"),
            "version": project_metadata.get("version"),
        },
        "boundary": {
            "proves": "This manifest proves that public AGILAB surfaces are discoverable from checked-in contracts.",
            "does_not_prove": "It does not prove runtime success, external service reachability, security certification, or production readiness.",
        },
        "summary": {
            "cli_command_count": len(cli_commands),
            "streamlit_page_count": len(pages),
            "package_count": len(packages),
            "public_app_count": len(apps),
            "agent_skill_count": len(skills),
            "evidence_schema_count": len(schemas),
            "catalog_file_count": len(CATALOG_FILES),
        },
        "cli_commands": cli_commands,
        "streamlit_pages": pages,
        "packages": packages,
        "public_apps": apps,
        "agent_skills": skills,
        "evidence_schemas": schemas,
        "catalog_files": _existing_catalog_files(),
        "docs": _existing_docs(),
    }


def build_manifest(output_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    base_payload = _base_manifest()
    return {
        "generated_at_utc": _resolve_generated_at(base_payload=base_payload, output_path=output_path),
        **base_payload,
    }


def render_manifest(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, indent=2) + "\n"


def write_manifest(output_path: Path = DEFAULT_OUTPUT) -> bool:
    payload = build_manifest(output_path=output_path)
    text = render_manifest(payload)
    existing = output_path.read_text(encoding="utf-8") if output_path.exists() else None
    if existing == text:
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    return True


def check_manifest(output_path: Path = DEFAULT_OUTPUT) -> bool:
    if not output_path.exists():
        return False
    expected = render_manifest(build_manifest(output_path=output_path))
    return output_path.read_text(encoding="utf-8") == expected


def _resolve_generated_at(base_payload: Mapping[str, Any], output_path: Path) -> str:
    existing_payload = _read_existing_payload(output_path)
    if existing_payload is not None:
        comparable = dict(existing_payload)
        comparable.pop("generated_at_utc", None)
        if comparable == base_payload:
            existing_generated_at = existing_payload.get("generated_at_utc")
            if isinstance(existing_generated_at, str) and existing_generated_at:
                return existing_generated_at
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_existing_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--apply", action="store_true", help="Write the generated manifest.")
    parser.add_argument("--check", action="store_true", help="Fail if the manifest is stale.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_path = args.output
    if not output_path.is_absolute():
        output_path = REPO_ROOT / output_path

    if args.apply:
        changed = write_manifest(output_path=output_path)
        print(f"Generated {_rel(output_path)}" if changed else "No changes in capability manifest")
    if args.check:
        if not check_manifest(output_path=output_path):
            print(f"ERROR: capability manifest is stale: {_rel(output_path)}", file=sys.stderr)
            return 2
        print(f"OK: capability manifest is current: {_rel(output_path)}")
    if not args.apply and not args.check:
        print(render_manifest(build_manifest(output_path=output_path)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
