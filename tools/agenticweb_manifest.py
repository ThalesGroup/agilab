#!/usr/bin/env python3
"""Generate AGILAB's agenticweb.md discovery file from capabilities.

The root ``agenticweb.md`` file is an external discovery index for agents.
AGILAB keeps ``agilab-capabilities.json`` as the richer source of truth and
generates this compact front door from it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CAPABILITIES = REPO_ROOT / "agilab-capabilities.json"
DEFAULT_OUTPUT = REPO_ROOT / "agenticweb.md"
PUBLIC_DOCS = "https://thalesgroup.github.io/agilab"
PUBLIC_REPO = "https://github.com/ThalesGroup/agilab"
PUBLIC_RAW = "https://raw.githubusercontent.com/ThalesGroup/agilab/main"
PYPI_URL = "https://pypi.org/project/agilab/"
HF_SPACE_URL = "https://huggingface.co/spaces/jpmorard/agilab"
AGENTICWEB_SCHEMA = "agilab.agenticweb_discovery.v1"


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


def _doc_url(path: str) -> str:
    if path.startswith("docs/source/") and path.endswith(".rst"):
        page = path.removeprefix("docs/source/").removesuffix(".rst")
        return f"{PUBLIC_DOCS}/{page}.html"
    return f"{PUBLIC_REPO}/blob/main/{path}"


def _raw_url(path: str) -> str:
    return f"{PUBLIC_RAW}/{path}"


def _permissions(*, executable: bool = False) -> dict[str, bool]:
    return {
        "read": True,
        "cite": True,
        "summarize": True,
        "train": False,
        "cache": True,
        "execute": executable,
    }


def _capability(
    *,
    kind: str,
    capability_id: str,
    description: str,
    url: str,
    status: str = "active",
    pricing_model: str = "free",
    auth_required: bool = False,
    permissions: Mapping[str, bool] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "kind": kind,
        "id": capability_id,
        "description": description,
        "url": url,
        "status": status,
        "pricing_model": pricing_model,
        "auth_required": auth_required,
    }
    if permissions is not None:
        row["permissions"] = dict(permissions)
    row.update({key: value for key, value in extra.items() if value not in (None, "", [], {})})
    return row


def _pick_cli(manifest: Mapping[str, Any], cli_id: str) -> Mapping[str, Any]:
    for row in manifest.get("cli_commands", []):
        if isinstance(row, Mapping) and row.get("id") == cli_id:
            return row
    return {}


def _validate_discovery(payload: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    if payload.get("agenticweb") != "1":
        issues.append("agenticweb must be '1'")
    description = payload.get("description")
    if not isinstance(description, str) or not description.strip():
        issues.append("description must be non-empty")
    elif len(description) > 400:
        issues.append("description must be at most 400 characters")
    organization = payload.get("organization")
    if not isinstance(organization, Mapping) or not organization.get("name"):
        issues.append("organization.name is required")
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        issues.append("capabilities must be a non-empty list")
    else:
        seen: set[str] = set()
        for index, raw in enumerate(capabilities):
            if not isinstance(raw, Mapping):
                issues.append(f"capabilities[{index}] must be an object")
                continue
            for key in ("kind", "id", "description", "url"):
                if not isinstance(raw.get(key), str) or not raw.get(key):
                    issues.append(f"capabilities[{index}].{key} must be a non-empty string")
            capability_id = raw.get("id")
            if isinstance(capability_id, str):
                if capability_id in seen:
                    issues.append(f"duplicate capability id: {capability_id}")
                seen.add(capability_id)
    return issues


def build_discovery(manifest_path: Path = DEFAULT_CAPABILITIES) -> dict[str, Any]:
    manifest = _load_json(manifest_path)
    if not isinstance(manifest, Mapping):
        raise ValueError(f"capability manifest must be a JSON object: {_rel(manifest_path)}")
    source = manifest.get("source", {})
    source_version = source.get("version") if isinstance(source, Mapping) else ""
    generated_at = str(manifest.get("generated_at_utc") or "")
    updated = generated_at[:10] if len(generated_at) >= 10 else ""
    agent_run = _pick_cli(manifest, "agent-run")
    first_proof = _pick_cli(manifest, "first-proof")
    workflow_validate = _pick_cli(manifest, "workflow-validate")
    description = (
        "AGILAB is an open-source AI/ML workbench for reproducible experiments, "
        "notebook-to-app workflows, run evidence, proof capsules, and local "
        "agent evidence review."
    )
    payload: dict[str, Any] = {
        "agenticweb": "1",
        "description": description,
        "updated": updated,
        "organization": {
            "name": "AGILAB",
            "website": PUBLIC_DOCS,
        },
        "contacts": {
            "support": f"{PUBLIC_REPO}/issues",
            "security": f"{PUBLIC_REPO}/security/policy",
        },
        "links": [
            {
                "name": "docs",
                "url": PUBLIC_DOCS,
                "description": "Public documentation.",
            },
            {
                "name": "github",
                "url": PUBLIC_REPO,
                "description": "Source repository and issue tracker.",
            },
            {
                "name": "pypi",
                "url": PYPI_URL,
                "description": "Installable Python package.",
            },
            {
                "name": "llms",
                "url": _raw_url("llms.txt"),
                "description": "Compact LLM/scraper discovery index.",
                "permissions": _permissions(),
            },
            {
                "name": "llms-full",
                "url": _raw_url("llms-full.txt"),
                "description": "Expanded LLM/scraper skill index.",
                "permissions": _permissions(),
            },
        ],
        "trust": {
            "allowed_origins": [
                PUBLIC_DOCS,
                PUBLIC_REPO,
                PUBLIC_RAW,
                "https://pypi.org",
                "https://huggingface.co",
            ],
            "marketplaces": [
                {
                    "platform": "github",
                    "url": PUBLIC_REPO,
                    "listing_type": "organization",
                },
                {
                    "platform": "pypi",
                    "url": PYPI_URL,
                    "listing_type": "api",
                },
                {
                    "platform": "huggingface",
                    "url": HF_SPACE_URL,
                    "listing_type": "agent",
                },
            ],
        },
        "capabilities": [
            _capability(
                kind="docs",
                capability_id="quick-start",
                description="Local install and first proof path for AGILAB.",
                url=f"{PUBLIC_DOCS}/quick-start.html",
                permissions=_permissions(),
            ),
            _capability(
                kind="docs",
                capability_id="capability-map",
                description="Job-to-route map with evidence and maturity boundaries.",
                url=f"{PUBLIC_DOCS}/capability-map.html",
                permissions=_permissions(),
            ),
            _capability(
                kind="docs",
                capability_id="release-proof",
                description="Public release evidence for package, docs, CI, coverage, and demo proof.",
                url=f"{PUBLIC_DOCS}/release-proof.html",
                permissions=_permissions(),
            ),
            _capability(
                kind="docs",
                capability_id="agent-skills",
                description="Repo-managed agent skills catalog and maintenance contract.",
                url=_raw_url("AGENT_SKILLS.md"),
                format="markdown",
                permissions=_permissions(),
            ),
            _capability(
                kind="data",
                capability_id="capability-manifest",
                description="Machine-readable inventory of shipped public AGILAB surfaces.",
                url=_raw_url("agilab-capabilities.json"),
                format="json",
                schema=_raw_url("agilab-capabilities.schema.json"),
                license="BSD-3-Clause",
                permissions=_permissions(),
            ),
            _capability(
                kind="data",
                capability_id="capability-rules",
                description="Declarative semantic lint-rule metadata for AGILAB capabilities.",
                url=_raw_url("agilab-capability-rules.yml"),
                format="yaml",
                license="BSD-3-Clause",
                permissions=_permissions(),
            ),
            _capability(
                kind="api",
                capability_id="first-proof-cli",
                description=str(first_proof.get("description") or "Run AGILAB first-proof evidence locally."),
                url=PYPI_URL,
                schema=_raw_url("agilab-capabilities.schema.json"),
                permissions=_permissions(executable=True),
            ),
            _capability(
                kind="api",
                capability_id="workflow-validate-cli",
                description=str(workflow_validate.get("description") or "Validate AGILAB workflow contracts."),
                url=_doc_url("docs/source/capability-map.rst"),
                permissions=_permissions(executable=False),
            ),
            _capability(
                kind="mcp",
                capability_id="read-only-evidence",
                description="Read-only MCP bridge for AGILAB run and agent-run evidence.",
                url="mcp://agilab/read-only-evidence",
                transport="stdio",
                auth_required=False,
                permissions=_permissions(executable=False),
            ),
            _capability(
                kind="api",
                capability_id="agent-run-evidence",
                description=str(agent_run.get("description") or "Wrap coding-agent actions with evidence."),
                url=f"{PUBLIC_DOCS}/agent-workflows.html",
                permissions=_permissions(executable=True),
            ),
            _capability(
                kind="ui",
                capability_id="streamlit-demo",
                description="Hosted AGILAB Streamlit demo for the public workbench path.",
                url=HF_SPACE_URL,
                status="beta",
                permissions=_permissions(executable=True),
            ),
        ],
        "x_generated_by": {
            "schema": AGENTICWEB_SCHEMA,
            "tool": "tools/agenticweb_manifest.py",
            "command": "python3 tools/agenticweb_manifest.py --apply",
            "source_manifest": _rel(manifest_path),
            "source_schema": str(manifest.get("schema") or ""),
            "source_version": str(source_version or ""),
            "boundary": (
                "Discovery only: this file does not prove runtime success, "
                "external service reachability, security certification, or production readiness."
            ),
        },
    }
    issues = _validate_discovery(payload)
    if issues:
        raise ValueError("invalid generated agenticweb payload:\n- " + "\n- ".join(issues))
    return payload


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _yaml_lines(value: Any, *, indent: int = 0) -> Iterable[str]:
    prefix = " " * indent
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(item, (Mapping, list)):
                yield f"{prefix}{key}:"
                yield from _yaml_lines(item, indent=indent + 2)
            elif isinstance(item, bool):
                yield f"{prefix}{key}: {'true' if item else 'false'}"
            elif item is None:
                yield f"{prefix}{key}: null"
            else:
                yield f"{prefix}{key}: {_quote(str(item))}"
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, Mapping):
                first = True
                for key, child in item.items():
                    marker = "-" if first else " "
                    if isinstance(child, (Mapping, list)):
                        yield f"{prefix}{marker} {key}:"
                        yield from _yaml_lines(child, indent=indent + 4)
                    elif isinstance(child, bool):
                        yield f"{prefix}{marker} {key}: {'true' if child else 'false'}"
                    else:
                        yield f"{prefix}{marker} {key}: {_quote(str(child))}"
                    first = False
            else:
                yield f"{prefix}- {_quote(str(item))}"
    else:
        yield f"{prefix}{_quote(str(value))}"


def render_agenticweb(payload: Mapping[str, Any]) -> str:
    body = [
        "# AGILAB agentic web discovery",
        "",
        "This file is generated from `agilab-capabilities.json`.",
        "Use the capability manifest for the complete machine-readable AGILAB surface.",
        "",
        "Validation:",
        "",
        "```bash",
        "python3 tools/agenticweb_manifest.py --check",
        "```",
    ]
    return "---\n" + "\n".join(_yaml_lines(payload)) + "\n---\n\n" + "\n".join(body) + "\n"


def generate_output(manifest_path: Path = DEFAULT_CAPABILITIES) -> str:
    return render_agenticweb(build_discovery(manifest_path))


def write_output(output_path: Path, content: str) -> bool:
    existing = output_path.read_text(encoding="utf-8") if output_path.exists() else None
    if existing == content:
        return False
    output_path.write_text(content, encoding="utf-8")
    return True


def check_output(output_path: Path = DEFAULT_OUTPUT, manifest_path: Path = DEFAULT_CAPABILITIES) -> bool:
    expected = generate_output(manifest_path)
    return output_path.exists() and output_path.read_text(encoding="utf-8") == expected


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capabilities", type=Path, default=DEFAULT_CAPABILITIES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--apply", action="store_true", help="Write agenticweb.md.")
    parser.add_argument("--check", action="store_true", help="Fail if agenticweb.md is stale.")
    parser.add_argument("--json", action="store_true", help="Print generated discovery JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    capabilities = args.capabilities.expanduser()
    output = args.output.expanduser()
    payload = build_discovery(capabilities)
    content = render_agenticweb(payload)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    if args.apply:
        changed = write_output(output, content)
        print(f"{'Generated' if changed else 'No changes in'} {_rel(output)}")
    if args.check:
        if not output.exists() or output.read_text(encoding="utf-8") != content:
            print(f"ERROR: {_rel(output)} is stale")
            return 2
        print(f"OK: {_rel(output)} is current")
    if not args.apply and not args.check and not args.json:
        print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
