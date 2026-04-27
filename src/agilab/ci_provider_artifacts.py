# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS
"""CI provider artifact indexing for external-machine AGILAB evidence."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
import re
import tempfile
from typing import Any
from urllib import parse
from urllib import request
from zipfile import ZipFile

from agilab.ci_artifact_harvest import (
    DEFAULT_RELEASE_ID,
    REQUIRED_ARTIFACT_KINDS,
    sample_ci_artifacts,
)


SCHEMA = "agilab.ci_provider_artifact_index.v1"
PROVIDER = "github_actions"
GENERIC_PROVIDER = "generic_download"
GITLAB_CI_PROVIDER = "gitlab_ci"
DEFAULT_SOURCE_MACHINE = "github-actions"
DEFAULT_USER_AGENT = "agilab-ci-provider-artifacts/1"
REQUIRED_PAYLOAD_PATHS = {
    "run_manifest": ("run_manifest.json",),
    "kpi_evidence_bundle": ("kpi_evidence_bundle.json",),
    "compatibility_report": ("compatibility_report.json",),
    "promotion_decision": ("promotion_decision.json",),
}
SAMPLE_ARCHIVE_MEMBERS = {
    "run_manifest": "ci/source-checkout-first-proof/run_manifest.json",
    "kpi_evidence_bundle": "ci/evidence/kpi_evidence_bundle.json",
    "compatibility_report": "ci/evidence/compatibility_report.json",
    "promotion_decision": "ci/release/promotion_decision.json",
}


UrlOpen = Callable[[request.Request], Any]


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_id(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return normalized or "artifact"


def _path_matches_kind(member: str, kind: str) -> bool:
    normalized = member.replace("\\", "/").lower()
    return any(
        normalized.endswith(candidate)
        for candidate in REQUIRED_PAYLOAD_PATHS.get(kind, ())
    )


def _json_payload_from_archive(archive: ZipFile, member: str) -> dict[str, Any]:
    payload = json.loads(archive.read(member).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"archive member is not a JSON object: {member}")
    return payload


def _payloads_from_archive(path: Path) -> dict[str, tuple[str, dict[str, Any]]]:
    payloads: dict[str, tuple[str, dict[str, Any]]] = {}
    with ZipFile(path) as archive:
        members = sorted(name for name in archive.namelist() if not name.endswith("/"))
        for kind in REQUIRED_ARTIFACT_KINDS:
            matches = [member for member in members if _path_matches_kind(member, kind)]
            if not matches:
                continue
            exact_matches = [
                member
                for member in matches
                if Path(member).name.lower()
                in {candidate.lower() for candidate in REQUIRED_PAYLOAD_PATHS[kind]}
            ]
            selected = sorted(exact_matches or matches)[0]
            payloads[kind] = (selected, _json_payload_from_archive(archive, selected))
    return payloads


def _provider_scheme(provider: str) -> str:
    if provider == PROVIDER:
        return "github-actions"
    if provider == GITLAB_CI_PROVIDER:
        return "gitlab-ci"
    return _safe_id(provider).replace("_", "-") or "ci-provider"


def _artifact_uri(
    *,
    provider: str,
    repository: str,
    run_id: str,
    archive_name: str,
    member: str,
) -> str:
    scheme = _provider_scheme(provider)
    if repository and run_id:
        return (
            f"{scheme}://{repository}/runs/{run_id}/artifacts/"
            f"{archive_name}/{member}"
        )
    return f"{scheme}-archive://{archive_name}/{member}"


def build_artifact_index_from_archives(
    archives: Sequence[Path | str],
    *,
    repository: str = "",
    run_id: str = "",
    workflow: str = "",
    run_attempt: str = "",
    source_machine: str = DEFAULT_SOURCE_MACHINE,
    release_id: str = DEFAULT_RELEASE_ID,
    provider: str = PROVIDER,
    provider_query_count: int = 0,
    download_count: int = 0,
    provider_artifacts: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build a harvest-compatible artifact index from provider artifact ZIP files."""

    provider = provider or GENERIC_PROVIDER

    archive_paths = [Path(path).expanduser() for path in archives]
    rows: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    archive_summaries: list[dict[str, Any]] = []
    seen_kinds: set[str] = set()

    for archive_path in archive_paths:
        archive_name = archive_path.name
        archive_summaries.append(
            {
                "name": archive_name,
                "path": str(archive_path),
                "content_sha256": _file_sha256(archive_path),
            }
        )
        for kind, (member, payload) in _payloads_from_archive(archive_path).items():
            if kind in seen_kinds:
                issues.append(
                    {
                        "level": "warning",
                        "location": f"artifacts.{kind}",
                        "message": "multiple provider artifacts contain this evidence kind",
                    }
                )
            seen_kinds.add(kind)
            rows.append(
                {
                    "id": f"{_safe_id(archive_path.stem)}_{kind}",
                    "kind": kind,
                    "path": _artifact_uri(
                        provider=provider,
                        repository=repository,
                        run_id=run_id,
                        archive_name=archive_name,
                        member=member,
                    ),
                    "payload": payload,
                    "source_machine": source_machine,
                    "workflow": workflow,
                    "run_id": run_id,
                    "run_attempt": str(run_attempt),
                    "release_id": release_id,
                    "provider": provider,
                    "provider_archive": archive_name,
                    "provider_member": member,
                }
            )

    missing_required = [
        kind for kind in REQUIRED_ARTIFACT_KINDS if kind not in seen_kinds
    ]
    for kind in missing_required:
        issues.append(
            {
                "level": "error",
                "location": f"artifacts.{kind}",
                "message": "provider artifact archive does not contain required evidence",
            }
        )

    provider_query_count = int(provider_query_count)
    download_count = int(download_count)
    network_probe_count = provider_query_count + download_count
    provider_artifact_rows = [dict(row) for row in provider_artifacts]
    return {
        "schema": SCHEMA,
        "provider": provider,
        "release_id": release_id,
        "repository": repository,
        "run_id": run_id,
        "workflow": workflow,
        "run_attempt": str(run_attempt),
        "source_machine": source_machine,
        "summary": {
            "schema": SCHEMA,
            "archive_count": len(archive_paths),
            "provider_artifact_count": len(provider_artifact_rows)
            or len(archive_summaries),
            "artifact_count": len(rows),
            "required_artifact_count": len(REQUIRED_ARTIFACT_KINDS),
            "loaded_artifact_count": len(rows),
            "missing_required_count": len(missing_required),
            "provider_query_count": provider_query_count,
            "download_count": download_count,
            "network_probe_count": network_probe_count,
            "command_execution_count": 0,
            "artifact_kinds": sorted(seen_kinds),
            "missing_required_artifact_kinds": missing_required,
        },
        "artifacts": rows,
        "provider_artifacts": provider_artifact_rows or archive_summaries,
        "archives": archive_summaries,
        "issues": issues,
        "provenance": {
            "queries_ci_provider": provider_query_count > 0,
            "downloads_provider_archives": download_count > 0,
            "executes_commands": False,
            "safe_for_public_evidence": network_probe_count == 0,
        },
    }


def _github_headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": DEFAULT_USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _gitlab_headers(token: str | None) -> dict[str, str]:
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    if token:
        headers["PRIVATE-TOKEN"] = token
    return headers


def _read_json_url(url: str, *, token: str | None, urlopen: UrlOpen) -> dict[str, Any]:
    req = request.Request(url, headers=_github_headers(token))
    with urlopen(req) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"GitHub API response is not a JSON object: {url}")
    return payload


def _read_gitlab_json_url(url: str, *, token: str | None, urlopen: UrlOpen) -> list[Any]:
    req = request.Request(url, headers=_gitlab_headers(token))
    with urlopen(req) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"GitLab API response is not a JSON list: {url}")
    return payload


def list_github_actions_artifacts(
    *,
    repository: str,
    run_id: str,
    token: str | None = None,
    urlopen: UrlOpen = request.urlopen,
) -> tuple[list[dict[str, Any]], int]:
    """List GitHub Actions artifacts for a workflow run via the GitHub API."""

    artifacts: list[dict[str, Any]] = []
    query_count = 0
    page = 1
    while True:
        url = (
            f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/"
            f"artifacts?per_page=100&page={page}"
        )
        payload = _read_json_url(url, token=token, urlopen=urlopen)
        query_count += 1
        page_artifacts = payload.get("artifacts", [])
        if not isinstance(page_artifacts, list):
            raise ValueError("GitHub artifacts response must contain an artifacts list")
        artifacts.extend(row for row in page_artifacts if isinstance(row, dict))
        total_count = int(payload.get("total_count", len(artifacts)) or 0)
        if not page_artifacts or len(artifacts) >= total_count:
            break
        page += 1
    return artifacts, query_count


def list_gitlab_ci_artifacts(
    *,
    project: str,
    pipeline_id: str,
    gitlab_url: str = "https://gitlab.com",
    token: str | None = None,
    urlopen: UrlOpen = request.urlopen,
) -> tuple[list[dict[str, Any]], int]:
    """List GitLab CI jobs with downloadable artifact archives for a pipeline."""

    artifacts: list[dict[str, Any]] = []
    query_count = 0
    page = 1
    encoded_project = parse.quote(project, safe="")
    base_url = gitlab_url.rstrip("/")
    while True:
        url = (
            f"{base_url}/api/v4/projects/{encoded_project}/pipelines/"
            f"{pipeline_id}/jobs?scope[]=success&per_page=100&page={page}"
        )
        payload = _read_gitlab_json_url(url, token=token, urlopen=urlopen)
        query_count += 1
        page_artifacts = [
            row
            for row in payload
            if isinstance(row, dict) and isinstance(row.get("artifacts_file"), dict)
        ]
        artifacts.extend(page_artifacts)
        if len(payload) < 100:
            break
        page += 1
    return artifacts, query_count


def download_github_actions_artifacts(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    destination: Path,
    token: str | None = None,
    urlopen: UrlOpen = request.urlopen,
) -> tuple[list[Path], int]:
    """Download GitHub Actions artifact archives into ``destination``."""

    destination = destination.expanduser()
    destination.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    download_count = 0
    for artifact in artifacts:
        archive_url = str(artifact.get("archive_download_url", "") or "")
        if not archive_url:
            continue
        name = _safe_id(str(artifact.get("name", "") or "artifact"))
        artifact_id = str(artifact.get("id", "") or len(paths) + 1)
        target = destination / f"{name}-{artifact_id}.zip"
        req = request.Request(archive_url, headers=_github_headers(token))
        with urlopen(req) as response:
            target.write_bytes(response.read())
        paths.append(target)
        download_count += 1
    return paths, download_count


def download_gitlab_ci_artifacts(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    destination: Path,
    project: str,
    gitlab_url: str = "https://gitlab.com",
    token: str | None = None,
    urlopen: UrlOpen = request.urlopen,
) -> tuple[list[Path], int]:
    """Download GitLab CI job artifact archives into ``destination``."""

    destination = destination.expanduser()
    destination.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    download_count = 0
    encoded_project = parse.quote(project, safe="")
    base_url = gitlab_url.rstrip("/")
    for artifact in artifacts:
        job_id = str(artifact.get("id", "") or "")
        if not job_id:
            continue
        artifact_file = artifact.get("artifacts_file", {})
        filename = "artifacts.zip"
        if isinstance(artifact_file, Mapping):
            filename = str(artifact_file.get("filename", "") or filename)
        name = _safe_id(str(artifact.get("name", "") or "job"))
        target = destination / f"{name}-{job_id}-{_safe_id(filename)}.zip"
        url = f"{base_url}/api/v4/projects/{encoded_project}/jobs/{job_id}/artifacts"
        req = request.Request(url, headers=_gitlab_headers(token))
        with urlopen(req) as response:
            target.write_bytes(response.read())
        paths.append(target)
        download_count += 1
    return paths, download_count


def build_github_actions_artifact_index(
    *,
    repository: str,
    run_id: str,
    download_dir: Path | None = None,
    token: str | None = None,
    workflow: str = "",
    run_attempt: str = "",
    source_machine: str = DEFAULT_SOURCE_MACHINE,
    release_id: str = DEFAULT_RELEASE_ID,
    urlopen: UrlOpen = request.urlopen,
) -> dict[str, Any]:
    """Query GitHub Actions, download artifacts, and build a harvest index."""

    provider_artifacts, provider_query_count = list_github_actions_artifacts(
        repository=repository,
        run_id=run_id,
        token=token,
        urlopen=urlopen,
    )
    if download_dir is None:
        with tempfile.TemporaryDirectory(prefix="agilab-github-actions-artifacts-") as tmp:
            archives, download_count = download_github_actions_artifacts(
                provider_artifacts,
                destination=Path(tmp),
                token=token,
                urlopen=urlopen,
            )
            return build_artifact_index_from_archives(
                archives,
                repository=repository,
                run_id=run_id,
                workflow=workflow,
                run_attempt=run_attempt,
                source_machine=source_machine,
                release_id=release_id,
                provider=PROVIDER,
                provider_query_count=provider_query_count,
                download_count=download_count,
                provider_artifacts=provider_artifacts,
            )
    archives, download_count = download_github_actions_artifacts(
        provider_artifacts,
        destination=download_dir,
        token=token,
        urlopen=urlopen,
    )
    return build_artifact_index_from_archives(
        archives,
        repository=repository,
        run_id=run_id,
        workflow=workflow,
        run_attempt=run_attempt,
        source_machine=source_machine,
        release_id=release_id,
        provider=PROVIDER,
        provider_query_count=provider_query_count,
        download_count=download_count,
        provider_artifacts=provider_artifacts,
    )


def build_gitlab_ci_artifact_index(
    *,
    project: str,
    pipeline_id: str,
    gitlab_url: str = "https://gitlab.com",
    download_dir: Path | None = None,
    token: str | None = None,
    workflow: str = "",
    run_attempt: str = "",
    source_machine: str = "gitlab-ci",
    release_id: str = DEFAULT_RELEASE_ID,
    urlopen: UrlOpen = request.urlopen,
) -> dict[str, Any]:
    """Query GitLab CI, download job artifacts, and build a harvest index."""

    provider_artifacts, provider_query_count = list_gitlab_ci_artifacts(
        project=project,
        pipeline_id=pipeline_id,
        gitlab_url=gitlab_url,
        token=token,
        urlopen=urlopen,
    )
    if download_dir is None:
        with tempfile.TemporaryDirectory(prefix="agilab-gitlab-ci-artifacts-") as tmp:
            archives, download_count = download_gitlab_ci_artifacts(
                provider_artifacts,
                destination=Path(tmp),
                project=project,
                gitlab_url=gitlab_url,
                token=token,
                urlopen=urlopen,
            )
            return build_artifact_index_from_archives(
                archives,
                repository=project,
                run_id=pipeline_id,
                workflow=workflow,
                run_attempt=run_attempt,
                source_machine=source_machine,
                release_id=release_id,
                provider=GITLAB_CI_PROVIDER,
                provider_query_count=provider_query_count,
                download_count=download_count,
                provider_artifacts=provider_artifacts,
            )
    archives, download_count = download_gitlab_ci_artifacts(
        provider_artifacts,
        destination=download_dir,
        project=project,
        gitlab_url=gitlab_url,
        token=token,
        urlopen=urlopen,
    )
    return build_artifact_index_from_archives(
        archives,
        repository=project,
        run_id=pipeline_id,
        workflow=workflow,
        run_attempt=run_attempt,
        source_machine=source_machine,
        release_id=release_id,
        provider=GITLAB_CI_PROVIDER,
        provider_query_count=provider_query_count,
        download_count=download_count,
        provider_artifacts=provider_artifacts,
    )


def write_artifact_index(path: Path, index: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_sample_ci_provider_archive(path: Path) -> Path:
    """Write a deterministic provider artifact ZIP for public evidence tests."""

    payload_by_kind = {
        str(artifact["kind"]): artifact["payload"] for artifact in sample_ci_artifacts()
    }
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w") as archive:
        for kind, member in SAMPLE_ARCHIVE_MEMBERS.items():
            archive.writestr(
                member,
                _canonical_json_bytes(payload_by_kind[kind]).decode("utf-8"),
            )
    return path


def write_sample_github_actions_archive(path: Path) -> Path:
    """Write a deterministic GitHub Actions-style ZIP for public evidence tests."""

    return write_sample_ci_provider_archive(path)


def write_sample_ci_provider_directory(path: Path) -> Path:
    """Write deterministic evidence files in a provider artifact upload layout."""

    payload_by_kind = {
        str(artifact["kind"]): artifact["payload"] for artifact in sample_ci_artifacts()
    }
    path = path.expanduser()
    for kind, member in SAMPLE_ARCHIVE_MEMBERS.items():
        target = path / member
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload_by_kind[kind], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return path


def write_sample_github_actions_directory(path: Path) -> Path:
    """Write deterministic evidence files in the layout uploaded by Actions."""

    return write_sample_ci_provider_directory(path)


def token_from_env(name: str = "GITHUB_TOKEN") -> str | None:
    return os.getenv(name) or None
