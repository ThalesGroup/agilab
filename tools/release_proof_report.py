#!/usr/bin/env python3
"""Render and validate the AGILAB release proof documentation page."""

from __future__ import annotations

import argparse
import copy
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from string import Formatter
import subprocess
import textwrap
from typing import Any, Mapping, Sequence
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOCS_SOURCE = REPO_ROOT / "docs" / "source"
MANIFEST_RELATIVE_PATH = Path("data/release_proof.toml")
OUTPUT_RELATIVE_PATH = Path("release-proof.rst")
SCHEMA = "agilab.release_proof.v1"
GITHUB_RUN_FIELDS = (
    "databaseId",
    "workflowName",
    "headSha",
    "status",
    "conclusion",
    "url",
    "createdAt",
    "event",
)
DEFAULT_GITHUB_BRANCH = "main"
DEFAULT_GITHUB_RUN_LIMIT = 50
DEFAULT_GITHUB_MAX_AGE_DAYS = 45
DEFAULT_GITHUB_WORKFLOWS = (
    "repo-guardrails",
    "docs-source-guard",
    "docs-publish",
    "coverage",
)
GITHUB_WORKFLOW_SUMMARIES = {
    "repo-guardrails": "passed repository guardrails and clean package first-proof jobs",
    "docs-source-guard": "passed docs mirror and release-proof consistency checks",
    "docs-publish": "built the public documentation from the managed docs mirror",
    "coverage": "passed component coverage and badge freshness checks",
}
GITHUB_WORKFLOW_IDS = {
    "repo-guardrails": "release-guardrails",
    "docs-source-guard": "docs-source-guard",
    "docs-publish": "docs-publish",
    "coverage": "coverage",
}


class _SafeFormatDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        raise KeyError(f"unknown release proof template key: {key}")


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = _load_toml(path)
    if manifest.get("schema") != SCHEMA:
        raise ValueError(f"{path} must declare schema = {SCHEMA!r}")
    return manifest


def _format_toml_scalar(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    raise TypeError(f"unsupported TOML scalar: {type(value).__name__}")


def _format_toml_list_item(value: Any) -> str:
    if isinstance(value, Mapping):
        raise TypeError("mapping values must be written as TOML tables")
    return _format_toml_scalar(value)


def _dump_toml_key_value(lines: list[str], key: str, value: Any) -> None:
    if isinstance(value, list):
        if all(not isinstance(item, Mapping) for item in value):
            if not value:
                lines.append(f"{key} = []")
                return
            lines.append(f"{key} = [")
            for item in value:
                lines.append(f"  {_format_toml_list_item(item)},")
            lines.append("]")
            return
        raise TypeError(f"{key} must be emitted as an array table")
    if isinstance(value, Mapping):
        raise TypeError(f"{key} must be emitted as a table")
    lines.append(f"{key} = {_format_toml_scalar(value)}")


def dump_manifest(manifest: Mapping[str, Any]) -> str:
    lines: list[str] = []
    first_block = True
    for key, value in manifest.items():
        if isinstance(value, Mapping):
            if not first_block:
                lines.append("")
            lines.append(f"[{key}]")
            for child_key, child_value in value.items():
                _dump_toml_key_value(lines, str(child_key), child_value)
            first_block = False
            continue
        if isinstance(value, list) and any(isinstance(item, Mapping) for item in value):
            for item in value:
                if not isinstance(item, Mapping):
                    raise TypeError(f"{key} mixes table and scalar values")
                if not first_block:
                    lines.append("")
                lines.append(f"[[{key}]]")
                for child_key, child_value in item.items():
                    _dump_toml_key_value(lines, str(child_key), child_value)
                first_block = False
            continue
        _dump_toml_key_value(lines, str(key), value)
        first_block = False
    lines.append("")
    return "\n".join(lines)


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_manifest(manifest), encoding="utf-8")


def _template_context(manifest: Mapping[str, Any]) -> dict[str, Any]:
    release = manifest.get("release", {})
    if not isinstance(release, Mapping):
        raise TypeError("[release] must be a table")
    package_name = str(release.get("package_name", ""))
    package_version = str(release.get("package_version", ""))
    return {
        **{str(key): value for key, value in release.items()},
        "package_spec": f"{package_name}=={package_version}",
    }


def _format_template(text: str, context: Mapping[str, Any]) -> str:
    # Validate field names explicitly so a release manifest typo fails clearly.
    for _, field_name, _, _ in Formatter().parse(text):
        if field_name and field_name not in context:
            raise KeyError(f"unknown release proof template key: {field_name}")
    return text.format_map(_SafeFormatDict(context))


def _format_templates(values: Sequence[Any], context: Mapping[str, Any]) -> list[str]:
    return [_format_template(str(value), context) for value in values]


def _append_wrapped(
    lines: list[str],
    text: str,
    *,
    initial_indent: str = "",
    subsequent_indent: str | None = None,
) -> None:
    subsequent = initial_indent if subsequent_indent is None else subsequent_indent
    wrapped = textwrap.wrap(
        text,
        width=79,
        initial_indent=initial_indent,
        subsequent_indent=subsequent,
        break_long_words=False,
        break_on_hyphens=False,
    )
    if wrapped:
        lines.extend(wrapped)
    else:
        lines.append(initial_indent.rstrip())


def _append_paragraphs(lines: list[str], paragraphs: Sequence[Any], context: Mapping[str, Any]) -> None:
    for index, paragraph in enumerate(_format_templates(paragraphs, context)):
        if index:
            lines.append("")
        _append_wrapped(lines, paragraph)


def _append_code_block(
    lines: list[str],
    commands: Sequence[Any],
    context: Mapping[str, Any],
    *,
    indent: str = "",
) -> None:
    lines.append("")
    lines.append(f"{indent}.. code-block:: bash")
    lines.append("")
    for command in _format_templates(commands, context):
        lines.append(f"{indent}   {command}")


def _required_table(name: str, manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    value = manifest.get(name)
    if not isinstance(value, Mapping):
        raise TypeError(f"[{name}] must be a table")
    return value


def _required_list(name: str, manifest: Mapping[str, Any]) -> list[Any]:
    value = manifest.get(name, [])
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list")
    return value


def render_release_proof(manifest: Mapping[str, Any]) -> str:
    context = _template_context(manifest)
    release = _required_table("release", manifest)
    proof_command = _required_table("proof_command", manifest)
    verification = _required_table("verification", manifest)
    scope = _required_table("scope", manifest)
    maintenance = manifest.get("maintenance", {})
    ci_runs = _required_list("ci_runs", manifest)
    proof_bullets = _required_list("proof_bullets", manifest)
    related_pages = _required_list("related_pages", manifest)

    title = str(manifest.get("title", "Release Proof"))
    lines: list[str] = [title, "=" * len(title), ""]
    lines.extend(
        [
            ".. This page is generated from docs/source/data/release_proof.toml by",
            "   tools/release_proof_report.py. Edit the TOML and rerender.",
            "",
        ]
    )
    _append_paragraphs(lines, _required_list("intro", manifest), context)

    lines.extend(
        [
            "",
            "Current public release",
            "----------------------",
            "",
            ".. list-table::",
            "   :header-rows: 1",
            "   :widths: 24 76",
            "",
            "   * - Item",
            "     - Public evidence",
            "   * - Package version",
            (
                f"     - ``{context['package_spec']}`` on "
                f"`PyPI <{release['pypi_url']}>`__"
            ),
            "   * - GitHub release",
            (
                f"     - `{release['github_release_tag']} "
                f"<{release['github_release_url']}>`__"
            ),
            "   * - Hosted demo",
            (
                f"     - `{release['hf_space_label']} <{release['hf_space_url']}>`__ "
                f"at Space commit ``{release['hf_space_commit']}``"
            ),
        ]
    )
    for run in ci_runs:
        if not isinstance(run, Mapping):
            raise TypeError("each [[ci_runs]] entry must be a table")
        label = str(run["label"])
        workflow = str(run["workflow"])
        run_id = str(run["run_id"])
        url = str(run["url"])
        summary = _format_template(str(run["summary"]), context)
        lines.extend(
            [
                f"   * - {label}",
                f"     - `{workflow} run {run_id} <{url}>`__ {summary}",
            ]
        )

    lines.extend(["", "What was proved", "---------------", ""])
    _append_wrapped(lines, _format_template(str(proof_command["summary"]), context), initial_indent="- ")
    _append_code_block(lines, proof_command.get("commands", []), context, indent="  ")
    lines.append("")
    for bullet in _format_templates(proof_bullets, context):
        _append_wrapped(lines, bullet, initial_indent="- ", subsequent_indent="  ")

    lines.extend(["", "How to verify it again", "----------------------", ""])
    _append_paragraphs(lines, [verification["intro"]], context)
    _append_code_block(lines, verification.get("commands", []), context)
    lines.append("")
    _append_paragraphs(lines, [verification["follow_up"]], context)

    if maintenance:
        if not isinstance(maintenance, Mapping):
            raise TypeError("[maintenance] must be a table")
        lines.extend(["", "Maintainer refresh", "------------------", ""])
        _append_paragraphs(lines, [maintenance["intro"]], context)
        _append_code_block(lines, maintenance.get("commands", []), context)
        follow_up = maintenance.get("follow_up")
        if follow_up:
            lines.append("")
            _append_paragraphs(lines, [follow_up], context)

    lines.extend(["", "Scope and limits", "----------------", ""])
    _append_paragraphs(lines, [scope["paragraph"]], context)

    lines.extend(["", "Related pages", "-------------", ""])
    for page in related_pages:
        lines.append(f"- :doc:`{page}`")
    lines.append("")
    return "\n".join(lines)


def _check_result(
    check_id: str,
    passed: bool,
    summary: str,
    *,
    evidence: Sequence[str] = (),
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "pass" if passed else "fail",
        "summary": summary,
        "evidence": list(evidence),
        "details": dict(details or {}),
    }


def _load_project_version(repo_root: Path) -> str | None:
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.exists():
        return None
    payload = _load_toml(pyproject)
    project = payload.get("project", {})
    if not isinstance(project, Mapping):
        return None
    version = project.get("version")
    return str(version) if version is not None else None


def _run_git(repo_root: Path, args: Sequence[str]) -> str | None:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _release_tag_prefix(package_version: str) -> str | None:
    match = re.match(r"^(\d{4}\.\d{2}\.\d{2})", package_version)
    return match.group(1) if match else None


def _latest_local_release_tag(repo_root: Path, package_version: str) -> str | None:
    prefix = _release_tag_prefix(package_version)
    if not prefix:
        return None
    output = _run_git(repo_root, ["tag", "--list", f"v{prefix}*", "--sort=-v:refname"])
    if not output:
        return None
    return output.splitlines()[0].strip() or None


def _github_repo_base_url(repo_root: Path) -> str | None:
    remote = _run_git(repo_root, ["remote", "get-url", "origin"])
    if not remote:
        return None
    remote = remote.strip()
    if remote.startswith("https://github.com/"):
        return remote.removesuffix(".git")
    ssh_match = re.match(r"git@github\.com:(?P<repo>[^/]+/[^/]+?)(?:\.git)?$", remote)
    if ssh_match:
        return f"https://github.com/{ssh_match.group('repo')}"
    return None


def _github_repo_name(repo_root: Path) -> str | None:
    base_url = _github_repo_base_url(repo_root)
    if not base_url:
        return None
    prefix = "https://github.com/"
    if not base_url.startswith(prefix):
        return None
    return base_url.removeprefix(prefix)


def _run_gh_json(args: Sequence[str]) -> Any:
    completed = subprocess.run(
        ["gh", *args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"gh {' '.join(args)} failed: {detail}")
    try:
        return json.loads(completed.stdout or "null")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gh {' '.join(args)} returned invalid JSON: {exc}") from exc


def _github_json_fields() -> str:
    return ",".join(GITHUB_RUN_FIELDS)


def _normalize_github_run(row: Mapping[str, Any]) -> dict[str, str]:
    return {field: str(row.get(field, "") or "") for field in GITHUB_RUN_FIELDS}


def _github_run_id(row: Mapping[str, Any]) -> str:
    value = row.get("databaseId", "")
    return str(value or "")


def _github_run_is_success(row: Mapping[str, Any]) -> bool:
    return (
        str(row.get("status", "")) == "completed"
        and str(row.get("conclusion", "")) == "success"
        and bool(_github_run_id(row))
        and bool(row.get("url"))
    )


def _github_created_at(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        return None


def _resolve_github_repo(repo_root: Path, explicit_repo: str | None) -> str:
    repo = explicit_repo or _github_repo_name(repo_root)
    if not repo:
        raise RuntimeError("unable to infer GitHub repository from origin; pass --github-repo OWNER/REPO")
    return repo


def _latest_successful_github_runs(
    *,
    repo: str,
    workflows: Sequence[str],
    branch: str | None,
    head_sha: str | None,
    limit: int,
) -> dict[str, dict[str, str]]:
    args = [
        "run",
        "list",
        "--repo",
        repo,
        "--limit",
        str(limit),
        "--json",
        _github_json_fields(),
    ]
    if branch:
        args.extend(["--branch", branch])
    rows = _run_gh_json(args)
    if not isinstance(rows, list):
        raise RuntimeError("gh run list did not return a JSON list")

    wanted = set(workflows)
    found: dict[str, dict[str, str]] = {}
    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            continue
        workflow = str(raw_row.get("workflowName", "") or "")
        if workflow not in wanted or workflow in found:
            continue
        if head_sha and str(raw_row.get("headSha", "") or "") != head_sha:
            continue
        if not _github_run_is_success(raw_row):
            continue
        found[workflow] = _normalize_github_run(raw_row)

    missing = [workflow for workflow in workflows if workflow not in found]
    if missing:
        qualifier = f" for head {head_sha}" if head_sha else ""
        raise RuntimeError(
            "missing successful GitHub workflow runs"
            f"{qualifier}: {', '.join(missing)}"
        )
    return found


def refresh_manifest_from_github(
    manifest: Mapping[str, Any],
    *,
    repo_root: Path = REPO_ROOT,
    github_repo: str | None = None,
    github_branch: str | None = DEFAULT_GITHUB_BRANCH,
    github_head_sha: str | None = None,
    workflows: Sequence[str] = DEFAULT_GITHUB_WORKFLOWS,
    run_limit: int = DEFAULT_GITHUB_RUN_LIMIT,
) -> dict[str, Any]:
    repo = _resolve_github_repo(repo_root, github_repo)
    runs = _latest_successful_github_runs(
        repo=repo,
        workflows=workflows,
        branch=github_branch,
        head_sha=github_head_sha,
        limit=run_limit,
    )

    refreshed = copy.deepcopy(dict(manifest))
    ci_runs = refreshed.get("ci_runs", [])
    if not isinstance(ci_runs, list):
        raise TypeError("ci_runs must be a list")

    managed_workflows = set(workflows)
    by_workflow: dict[str, dict[str, Any]] = {}
    normalized_runs: list[dict[str, Any]] = []
    for entry in ci_runs:
        if not isinstance(entry, Mapping):
            raise TypeError("each [[ci_runs]] entry must be a table")
        copied = dict(entry)
        workflow = str(copied.get("workflow", "") or "")
        if workflow in managed_workflows and workflow in by_workflow:
            continue
        normalized_runs.append(copied)
        if workflow and workflow not in by_workflow:
            by_workflow[workflow] = copied

    for workflow in workflows:
        run = runs[workflow]
        entry = by_workflow.get(workflow)
        if entry is None:
            entry = {
                "id": GITHUB_WORKFLOW_IDS.get(workflow, workflow),
                "label": workflow,
                "workflow": workflow,
            }
            normalized_runs.append(entry)
            by_workflow[workflow] = entry
        entry["run_id"] = _github_run_id(run)
        entry["url"] = str(run["url"])
        entry["summary"] = GITHUB_WORKFLOW_SUMMARIES.get(
            workflow,
            "passed the public release proof workflow gate",
        )

    refreshed["ci_runs"] = normalized_runs
    return refreshed


def refresh_manifest_from_local(
    manifest: Mapping[str, Any],
    *,
    repo_root: Path = REPO_ROOT,
    github_release_tag: str | None = None,
    github_release_url: str | None = None,
    hf_space_commit: str | None = None,
) -> dict[str, Any]:
    refreshed = copy.deepcopy(dict(manifest))
    release = refreshed.get("release")
    if not isinstance(release, dict):
        raise TypeError("[release] must be a table")

    package_version = _load_project_version(repo_root) or str(release.get("package_version", ""))
    if package_version:
        release["package_version"] = package_version

    tag = github_release_tag or _latest_local_release_tag(repo_root, package_version)
    if tag:
        release["github_release_tag"] = tag
        base_url = _github_repo_base_url(repo_root)
        release["github_release_url"] = github_release_url or (
            f"{base_url}/releases/tag/{tag}" if base_url else str(release.get("github_release_url", ""))
        )
    elif github_release_url:
        release["github_release_url"] = github_release_url

    if hf_space_commit:
        release["hf_space_commit"] = hf_space_commit

    return refreshed


def _text_contains(path: Path, expected: str) -> bool | None:
    if not path.exists():
        return None
    return expected in path.read_text(encoding="utf-8")


def _ci_run_urls_are_consistent(ci_runs: Sequence[Any]) -> bool:
    for run in ci_runs:
        if not isinstance(run, Mapping):
            return False
        run_id = str(run.get("run_id", ""))
        url = str(run.get("url", ""))
        if not run_id or not url.endswith(f"/actions/runs/{run_id}"):
            return False
    return True


def _github_ci_runs_check(
    ci_runs: Sequence[Any],
    *,
    repo_root: Path,
    github_repo: str | None,
    max_age_days: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    checked_at = now or datetime.now(UTC)
    try:
        repo = _resolve_github_repo(repo_root, github_repo)
    except RuntimeError as exc:
        return _check_result(
            "github_ci_runs",
            False,
            "manifest CI runs could not be checked against GitHub",
            evidence=[],
            details={"error": str(exc)},
        )

    details: list[dict[str, Any]] = []
    failures: list[str] = []
    for run in ci_runs:
        if not isinstance(run, Mapping):
            failures.append("malformed ci_runs entry")
            continue
        run_id = str(run.get("run_id", "") or "")
        workflow = str(run.get("workflow", "") or "")
        if not run_id:
            failures.append(f"{workflow or '<unknown>'}: missing run_id")
            continue
        try:
            raw = _run_gh_json(
                [
                    "run",
                    "view",
                    run_id,
                    "--repo",
                    repo,
                    "--json",
                    _github_json_fields(),
                ]
            )
        except RuntimeError as exc:
            failures.append(f"{workflow or run_id}: {exc}")
            continue
        if not isinstance(raw, Mapping):
            failures.append(f"{workflow or run_id}: gh run view did not return an object")
            continue

        github_run = _normalize_github_run(raw)
        github_workflow = github_run["workflowName"]
        created_at = _github_created_at(github_run["createdAt"])
        age_days = None
        if created_at is not None:
            age_days = max((checked_at - created_at).total_seconds() / 86400, 0.0)
        run_failures: list[str] = []
        if github_workflow != workflow:
            run_failures.append(f"workflow mismatch: expected {workflow}, got {github_workflow}")
        if not _github_run_is_success(raw):
            run_failures.append(
                "run is not successful: "
                f"status={github_run['status']} conclusion={github_run['conclusion']}"
            )
        expected_url = str(run.get("url", "") or "")
        if expected_url and github_run["url"] and expected_url != github_run["url"]:
            run_failures.append("manifest URL differs from GitHub run URL")
        if age_days is None:
            run_failures.append("run createdAt timestamp is missing or invalid")
        elif age_days > max_age_days:
            run_failures.append(f"run is stale: {age_days:.1f} days old > {max_age_days}")

        details.append(
            {
                "workflow": workflow,
                "run_id": run_id,
                "github_workflow": github_workflow,
                "status": github_run["status"],
                "conclusion": github_run["conclusion"],
                "head_sha": github_run["headSha"],
                "created_at": github_run["createdAt"],
                "age_days": age_days,
                "url": github_run["url"],
                "failures": run_failures,
            }
        )
        failures.extend(f"{workflow or run_id}: {failure}" for failure in run_failures)

    return _check_result(
        "github_ci_runs",
        not failures,
        (
            "manifest CI runs exist on GitHub, succeeded, and are fresh"
            if not failures
            else "manifest CI runs are missing, failed, or stale on GitHub"
        ),
        evidence=[str(MANIFEST_RELATIVE_PATH)],
        details={
            "repo": repo,
            "max_age_days": max_age_days,
            "checked_at": checked_at.isoformat(),
            "runs": details,
            "failures": failures,
        },
    )


def build_report(
    *,
    manifest_path: Path,
    output_path: Path,
    repo_root: Path = REPO_ROOT,
    check_github_runs: bool = False,
    github_repo: str | None = None,
    github_max_age_days: int = DEFAULT_GITHUB_MAX_AGE_DAYS,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    rendered = render_release_proof(manifest)
    release = _required_table("release", manifest)
    ci_runs = _required_list("ci_runs", manifest)
    package_version = str(release["package_version"])
    github_release_url = str(release["github_release_url"])
    github_release_tag = str(release["github_release_tag"])
    checks: list[dict[str, Any]] = []

    project_version = _load_project_version(repo_root)
    checks.append(
        _check_result(
            "pyproject_version",
            project_version in (None, package_version),
            (
                "manifest package version matches pyproject.toml"
                if project_version is not None
                else "pyproject.toml not present; skipped package version cross-check"
            ),
            evidence=["pyproject.toml", str(manifest_path)],
            details={"pyproject_version": project_version, "manifest_version": package_version},
        )
    )
    checks.append(
        _check_result(
            "github_release_url",
            github_release_tag in github_release_url,
            "manifest GitHub release URL contains the release tag",
            evidence=[str(manifest_path)],
            details={"tag": github_release_tag, "url": github_release_url},
        )
    )
    badge_path = repo_root / "badges" / "pypi-version-agilab.svg"
    badge_contains = _text_contains(badge_path, f"v{package_version}")
    checks.append(
        _check_result(
            "pypi_badge_version",
            badge_contains is not False,
            (
                "PyPI badge contains manifest package version"
                if badge_contains is not None
                else "PyPI badge not present; skipped badge cross-check"
            ),
            evidence=[str(badge_path.relative_to(repo_root)) if badge_path.exists() else str(badge_path)],
        )
    )
    changelog = repo_root / "CHANGELOG.md"
    changelog_text = changelog.read_text(encoding="utf-8") if changelog.exists() else ""
    checks.append(
        _check_result(
            "changelog_release",
            not changelog.exists()
            or (f"## [{package_version}]" in changelog_text and github_release_url in changelog_text),
            "CHANGELOG current release entry matches the manifest",
            evidence=["CHANGELOG.md", str(manifest_path)],
        )
    )
    readme = repo_root / "README.md"
    readme_contains = _text_contains(readme, "https://thalesgroup.github.io/agilab/release-proof.html")
    checks.append(
        _check_result(
            "readme_release_proof_link",
            readme_contains is not False,
            (
                "README links to the public release proof page"
                if readme_contains is not None
                else "README not present; skipped README link cross-check"
            ),
            evidence=["README.md"],
        )
    )
    checks.append(
        _check_result(
            "ci_run_urls",
            _ci_run_urls_are_consistent(ci_runs),
            "CI run URLs match their run IDs",
            evidence=[str(manifest_path)],
        )
    )
    if check_github_runs:
        checks.append(
            _github_ci_runs_check(
                ci_runs,
                repo_root=repo_root,
                github_repo=github_repo,
                max_age_days=github_max_age_days,
            )
        )
    output_matches = output_path.exists() and output_path.read_text(encoding="utf-8") == rendered
    checks.append(
        _check_result(
            "rendered_page",
            output_matches,
            "release-proof.rst matches the rendered manifest output",
            evidence=[str(manifest_path), str(output_path)],
        )
    )

    failed = [check for check in checks if check["status"] != "pass"]
    return {
        "report": "AGILAB release proof report",
        "schema": SCHEMA,
        "status": "pass" if not failed else "fail",
        "manifest": str(manifest_path),
        "output": str(output_path),
        "release": {
            "package_name": str(release["package_name"]),
            "package_version": package_version,
            "github_release_tag": github_release_tag,
            "github_release_url": github_release_url,
            "hf_space_url": str(release["hf_space_url"]),
            "hf_space_commit": str(release["hf_space_commit"]),
        },
        "summary": {
            "check_count": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--docs-source",
        type=Path,
        default=DEFAULT_DOCS_SOURCE,
        help="Docs source root containing data/release_proof.toml.",
    )
    parser.add_argument("--data", type=Path, default=None, help="Override manifest path.")
    parser.add_argument("--output", type=Path, default=None, help="Override RST output path.")
    parser.add_argument(
        "--refresh-from-local",
        action="store_true",
        help=(
            "Update the manifest from local release evidence: pyproject.toml, the matching "
            "local git release tag, and the GitHub origin URL."
        ),
    )
    parser.add_argument(
        "--refresh-from-github",
        action="store_true",
        help=(
            "Update [[ci_runs]] from the latest successful GitHub Actions runs for the "
            "selected workflows."
        ),
    )
    parser.add_argument("--github-release-tag", default=None, help="Override refreshed GitHub release tag.")
    parser.add_argument("--github-release-url", default=None, help="Override refreshed GitHub release URL.")
    parser.add_argument("--hf-space-commit", default=None, help="Override refreshed Hugging Face Space commit.")
    parser.add_argument(
        "--github-repo",
        default=None,
        help="GitHub repository for run evidence as OWNER/REPO. Defaults to origin.",
    )
    parser.add_argument(
        "--github-branch",
        default=DEFAULT_GITHUB_BRANCH,
        help="Branch used when refreshing GitHub run evidence. Use an empty value to disable branch filtering.",
    )
    parser.add_argument(
        "--github-head-sha",
        default=None,
        help="Optional commit SHA that refreshed GitHub run evidence must match.",
    )
    parser.add_argument(
        "--github-workflow",
        action="append",
        dest="github_workflows",
        default=None,
        help=(
            "Workflow display name to refresh from GitHub. May be repeated. "
            "Defaults to repo-guardrails, docs-source-guard, docs-publish, and coverage."
        ),
    )
    parser.add_argument(
        "--github-run-limit",
        type=int,
        default=DEFAULT_GITHUB_RUN_LIMIT,
        help="Maximum GitHub Actions runs to inspect when refreshing run evidence.",
    )
    parser.add_argument(
        "--github-max-age-days",
        type=int,
        default=DEFAULT_GITHUB_MAX_AGE_DAYS,
        help="Maximum allowed age for CI runs when --check-github-runs is used.",
    )
    parser.add_argument(
        "--check-github-runs",
        action="store_true",
        help="Fail if manifest CI run IDs are missing, failed, mismatched, or stale on GitHub.",
    )
    parser.add_argument("--render", action="store_true", help="Write the rendered RST page.")
    parser.add_argument("--check", action="store_true", help="Fail if manifest checks or rendered page drift.")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON.")
    parser.add_argument("--quiet", action="store_true", help="Suppress JSON output.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    docs_source = args.docs_source
    manifest_path = args.data or docs_source / MANIFEST_RELATIVE_PATH
    output_path = args.output or docs_source / OUTPUT_RELATIVE_PATH

    manifest = load_manifest(manifest_path)
    if args.refresh_from_local:
        manifest = refresh_manifest_from_local(
            manifest,
            repo_root=REPO_ROOT,
            github_release_tag=args.github_release_tag,
            github_release_url=args.github_release_url,
            hf_space_commit=args.hf_space_commit,
        )
        write_manifest(manifest_path, manifest)
    if args.refresh_from_github:
        manifest = refresh_manifest_from_github(
            manifest,
            repo_root=REPO_ROOT,
            github_repo=args.github_repo,
            github_branch=args.github_branch or None,
            github_head_sha=args.github_head_sha,
            workflows=tuple(args.github_workflows or DEFAULT_GITHUB_WORKFLOWS),
            run_limit=args.github_run_limit,
        )
        write_manifest(manifest_path, manifest)

    rendered = render_release_proof(manifest)
    if args.render:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")

    report = build_report(
        manifest_path=manifest_path,
        output_path=output_path,
        repo_root=REPO_ROOT,
        check_github_runs=args.check_github_runs,
        github_repo=args.github_repo,
        github_max_age_days=args.github_max_age_days,
    )
    if not args.quiet:
        if args.compact:
            print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        else:
            print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if (not args.check or report["status"] == "pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
