from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

SRC_ROOT = Path("src").resolve()
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
package = sys.modules.get("agilab")
package_paths = getattr(package, "__path__", None)
if package_paths is not None and str(SRC_ROOT / "agilab") not in list(package_paths):
    package_paths.append(str(SRC_ROOT / "agilab"))

from agilab.ci_artifact_harvest import (
    build_ci_artifact_harvest,
    sample_ci_artifacts,
)
from agilab import ci_provider_artifacts as provider_artifacts
from agilab.ci_provider_artifacts import (
    build_artifact_index_from_archives,
    build_gitlab_ci_artifact_index,
    build_github_actions_artifact_index,
    write_sample_ci_provider_archive,
    write_sample_github_actions_archive,
    write_sample_github_actions_directory,
)


TOOL_PATH = Path("tools/github_actions_artifact_index.py").resolve()
GENERIC_TOOL_PATH = Path("tools/ci_provider_artifact_index.py").resolve()


def _load_tool_module(
    path: Path = TOOL_PATH,
    name: str = "github_actions_artifact_index_test_module",
):
    spec = importlib.util.spec_from_file_location(
        name,
        path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sample_payload(kind: str) -> dict[str, object]:
    return next(
        artifact["payload"]
        for artifact in sample_ci_artifacts()
        if artifact["kind"] == kind
    )


def test_github_actions_archive_index_feeds_harvest_contract(tmp_path: Path) -> None:
    archive_path = write_sample_github_actions_archive(tmp_path / "public-evidence.zip")

    index = build_artifact_index_from_archives(
        [archive_path],
        repository="ThalesGroup/agilab",
        run_id="123456789",
        workflow="public-evidence.yml",
        run_attempt="1",
        source_machine="github-actions:ubuntu-24.04",
    )

    assert index["schema"] == "agilab.ci_provider_artifact_index.v1"
    assert index["provider"] == "github_actions"
    assert index["summary"]["archive_count"] == 1
    assert index["summary"]["artifact_count"] == 4
    assert index["summary"]["missing_required_count"] == 0
    assert index["summary"]["provider_query_count"] == 0
    assert index["summary"]["download_count"] == 0
    assert index["summary"]["network_probe_count"] == 0
    assert index["provenance"]["safe_for_public_evidence"] is True
    assert all(
        artifact["path"].startswith(
            "github-actions://ThalesGroup/agilab/runs/123456789/artifacts/"
        )
        for artifact in index["artifacts"]
    )

    harvest = build_ci_artifact_harvest(
        index["artifacts"],
        release_id=index["release_id"],
        run_id=index["run_id"],
    )

    assert harvest["run_status"] == "harvest_ready"
    assert harvest["summary"]["artifact_count"] == 4
    assert harvest["summary"]["missing_required_count"] == 0
    assert harvest["release"]["public_status"] == "validated"


def test_gitlab_ci_archive_index_feeds_harvest_contract(tmp_path: Path) -> None:
    archive_path = write_sample_ci_provider_archive(tmp_path / "public-evidence.zip")

    index = build_artifact_index_from_archives(
        [archive_path],
        provider="gitlab_ci",
        repository="thales/agilab",
        run_id="987654321",
        workflow="release-evidence",
        run_attempt="1",
        source_machine="gitlab-ci:shared-runner",
    )

    assert index["schema"] == "agilab.ci_provider_artifact_index.v1"
    assert index["provider"] == "gitlab_ci"
    assert index["summary"]["archive_count"] == 1
    assert index["summary"]["artifact_count"] == 4
    assert index["summary"]["missing_required_count"] == 0
    assert index["summary"]["provider_query_count"] == 0
    assert index["summary"]["download_count"] == 0
    assert index["summary"]["network_probe_count"] == 0
    assert index["provenance"]["safe_for_public_evidence"] is True
    assert all(
        artifact["path"].startswith(
            "gitlab-ci://thales/agilab/runs/987654321/artifacts/"
        )
        for artifact in index["artifacts"]
    )

    harvest = build_ci_artifact_harvest(
        index["artifacts"],
        release_id=index["release_id"],
        run_id=index["run_id"],
    )

    assert harvest["run_status"] == "harvest_ready"
    assert harvest["summary"]["artifact_count"] == 4
    assert harvest["summary"]["missing_required_count"] == 0
    assert harvest["release"]["public_status"] == "validated"


def test_github_actions_archive_index_reports_missing_required_payloads(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "partial-evidence.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "nested/run_manifest.json",
            json.dumps(_sample_payload("run_manifest"), sort_keys=True),
        )

    index = build_artifact_index_from_archives([archive_path])

    assert index["summary"]["artifact_count"] == 1
    assert index["summary"]["missing_required_count"] == 3
    assert index["summary"]["missing_required_artifact_kinds"] == [
        "kpi_evidence_bundle",
        "compatibility_report",
        "promotion_decision",
    ]
    assert {issue["level"] for issue in index["issues"]} == {"error"}


def test_github_actions_artifact_index_cli_writes_harvest_input(
    tmp_path: Path,
) -> None:
    module = _load_tool_module()
    archive_path = write_sample_github_actions_archive(tmp_path / "public-evidence.zip")
    output_path = tmp_path / "artifact_index.json"

    exit_code = module.main(
        [
            "--archive",
            str(archive_path),
            "--repo",
            "ThalesGroup/agilab",
            "--run-id",
            "123456789",
            "--workflow",
            "public-evidence.yml",
            "--run-attempt",
            "1",
            "--output",
            str(output_path),
            "--compact",
        ]
    )

    assert exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "agilab.ci_provider_artifact_index.v1"
    assert payload["summary"]["artifact_count"] == 4
    assert payload["summary"]["missing_required_count"] == 0
    assert payload["artifacts"][0]["workflow"] == "public-evidence.yml"


def test_generic_ci_provider_artifact_index_cli_writes_gitlab_input(
    tmp_path: Path,
) -> None:
    module = _load_tool_module(
        GENERIC_TOOL_PATH,
        "ci_provider_artifact_index_test_module",
    )
    archive_path = write_sample_ci_provider_archive(tmp_path / "public-evidence.zip")
    output_path = tmp_path / "artifact_index.json"

    exit_code = module.main(
        [
            "--provider",
            "gitlab_ci",
            "--archive",
            str(archive_path),
            "--repo",
            "thales/agilab",
            "--run-id",
            "987654321",
            "--workflow",
            "release-evidence",
            "--source-machine",
            "gitlab-ci:shared-runner",
            "--output",
            str(output_path),
            "--compact",
        ]
    )

    assert exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "agilab.ci_provider_artifact_index.v1"
    assert payload["provider"] == "gitlab_ci"
    assert payload["summary"]["artifact_count"] == 4
    assert payload["summary"]["missing_required_count"] == 0
    assert payload["summary"]["network_probe_count"] == 0
    assert payload["artifacts"][0]["provider"] == "gitlab_ci"


def test_github_actions_sample_directory_matches_archive_layout(tmp_path: Path) -> None:
    sample_dir = write_sample_github_actions_directory(tmp_path / "public-evidence")

    assert (sample_dir / "ci/source-checkout-first-proof/run_manifest.json").is_file()
    assert (sample_dir / "ci/evidence/kpi_evidence_bundle.json").is_file()
    assert (sample_dir / "ci/evidence/compatibility_report.json").is_file()
    assert (sample_dir / "ci/release/promotion_decision.json").is_file()


def test_live_github_artifact_index_uses_api_downloads(tmp_path: Path) -> None:
    archive_bytes = io.BytesIO()
    with ZipFile(archive_bytes, "w") as archive:
        archive.writestr(
            "ci/source-checkout-first-proof/run_manifest.json",
            json.dumps(_sample_payload("run_manifest"), sort_keys=True),
        )
    archive_payload = archive_bytes.getvalue()
    requested_urls: list[str] = []
    artifact_requests: list[object] = []

    class _Response:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return self.payload

    def fake_urlopen(req: object) -> _Response:
        url = str(getattr(req, "full_url"))
        requested_urls.append(url)
        if url.endswith("/artifacts?per_page=100&page=1"):
            return _Response(
                json.dumps(
                    {
                        "total_count": 1,
                        "artifacts": [
                            {
                                "id": 17,
                                "name": "first-proof",
                                "archive_download_url": "https://example.invalid/artifacts/17.zip",
                            }
                        ],
                    }
                ).encode("utf-8")
            )
        artifact_requests.append(req)
        return _Response(archive_payload)

    index = build_github_actions_artifact_index(
        repository="ThalesGroup/agilab",
        run_id="123456789",
        download_dir=tmp_path / "downloads",
        token="token",
        workflow="public-evidence.yml",
        run_attempt="1",
        urlopen=fake_urlopen,
    )

    assert requested_urls == [
        "https://api.github.com/repos/ThalesGroup/agilab/actions/runs/123456789/artifacts?per_page=100&page=1",
        "https://example.invalid/artifacts/17.zip",
    ]
    assert artifact_requests
    artifact_request = artifact_requests[0]
    assert "Authorization" not in getattr(artifact_request, "headers", {})
    assert getattr(artifact_request, "unredirected_hdrs", {}).get("Authorization") == "Bearer token"
    assert index["summary"]["provider_query_count"] == 1
    assert index["summary"]["download_count"] == 1
    assert index["summary"]["network_probe_count"] == 2
    assert index["provenance"]["queries_ci_provider"] is True
    assert index["provenance"]["downloads_provider_archives"] is True
    assert index["summary"]["missing_required_count"] == 3


def test_live_gitlab_ci_artifact_index_uses_api_downloads(tmp_path: Path) -> None:
    archive_bytes = io.BytesIO()
    with ZipFile(archive_bytes, "w") as archive:
        archive.writestr(
            "ci/source-checkout-first-proof/run_manifest.json",
            json.dumps(_sample_payload("run_manifest"), sort_keys=True),
        )
    archive_payload = archive_bytes.getvalue()
    requested_urls: list[str] = []

    class _Response:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return self.payload

    def fake_urlopen(req: object) -> _Response:
        url = str(getattr(req, "full_url"))
        requested_urls.append(url)
        if url.endswith("/pipelines/987654321/jobs?scope[]=success&per_page=100&page=1"):
            return _Response(
                json.dumps(
                    [
                        {
                            "id": 42,
                            "name": "public-evidence",
                            "artifacts_file": {
                                "filename": "public-evidence.zip",
                                "size": len(archive_payload),
                            },
                        }
                    ]
                ).encode("utf-8")
            )
        return _Response(archive_payload)

    index = build_gitlab_ci_artifact_index(
        project="thales/agilab",
        pipeline_id="987654321",
        download_dir=tmp_path / "downloads",
        token="token",
        workflow="release-evidence",
        run_attempt="1",
        urlopen=fake_urlopen,
    )

    assert requested_urls == [
        "https://gitlab.com/api/v4/projects/thales%2Fagilab/pipelines/987654321/jobs?scope[]=success&per_page=100&page=1",
        "https://gitlab.com/api/v4/projects/thales%2Fagilab/jobs/42/artifacts",
    ]
    assert index["provider"] == "gitlab_ci"
    assert index["summary"]["provider_query_count"] == 1
    assert index["summary"]["download_count"] == 1
    assert index["summary"]["network_probe_count"] == 2
    assert index["provenance"]["queries_ci_provider"] is True
    assert index["provenance"]["downloads_provider_archives"] is True
    assert index["summary"]["missing_required_count"] == 3


def test_provider_archive_edge_cases_cover_validation_and_duplicates(tmp_path: Path) -> None:
    bad_archive = tmp_path / "bad-json.zip"
    with ZipFile(bad_archive, "w") as archive:
        archive.writestr("run_manifest.json", "[]")

    with pytest.raises(ValueError, match="not a JSON object"):
        provider_artifacts.build_artifact_index_from_archives([bad_archive])

    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    for path in (first, second):
        with ZipFile(path, "w") as archive:
            archive.writestr(
                "run_manifest.json",
                json.dumps(_sample_payload("run_manifest"), sort_keys=True),
            )

    index = provider_artifacts.build_artifact_index_from_archives(
        [first, second],
        provider="My Provider!",
    )

    assert index["artifacts"][0]["path"].startswith("my-provider-archive://")
    assert any(issue["level"] == "warning" for issue in index["issues"])


def test_provider_api_error_and_pagination_edges(tmp_path: Path) -> None:
    class _Response:
        def __init__(self, payload: object) -> None:
            self.payload = payload

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    with pytest.raises(ValueError, match="GitHub API response is not a JSON object"):
        provider_artifacts._read_json_url("https://api.example.invalid", token=None, urlopen=lambda _req: _Response([]))

    with pytest.raises(ValueError, match="GitLab API response is not a JSON list"):
        provider_artifacts._read_gitlab_json_url(
            "https://gitlab.example.invalid",
            token=None,
            urlopen=lambda _req: _Response({}),
        )

    with pytest.raises(ValueError, match="artifacts list"):
        provider_artifacts.list_github_actions_artifacts(
            repository="ThalesGroup/agilab",
            run_id="1",
            urlopen=lambda _req: _Response({"total_count": 1, "artifacts": {}}),
        )

    github_pages = iter(
        [
            {"total_count": 2, "artifacts": [{"id": 1, "name": "a"}]},
            {"total_count": 2, "artifacts": [{"id": 2, "name": "b"}]},
        ]
    )
    github_artifacts, query_count = provider_artifacts.list_github_actions_artifacts(
        repository="ThalesGroup/agilab",
        run_id="1",
        urlopen=lambda _req: _Response(next(github_pages)),
    )
    assert [artifact["id"] for artifact in github_artifacts] == [1, 2]
    assert query_count == 2

    gitlab_page = [{"id": index, "artifacts_file": {"filename": "a.zip"}} for index in range(100)]
    gitlab_pages = iter([gitlab_page, []])
    gitlab_artifacts, gitlab_query_count = provider_artifacts.list_gitlab_ci_artifacts(
        project="thales/agilab",
        pipeline_id="1",
        urlopen=lambda _req: _Response(next(gitlab_pages)),
    )
    assert len(gitlab_artifacts) == 100
    assert gitlab_query_count == 2


def test_provider_download_helpers_cover_skips_headers_and_default_filenames(tmp_path: Path) -> None:
    req = provider_artifacts._github_artifact_download_request("https://example.invalid/a.zip", token=None)
    assert "Authorization" not in req.headers
    assert "Authorization" not in req.unredirected_hdrs
    assert "PRIVATE-TOKEN" not in provider_artifacts._gitlab_headers(None)

    class _ZipResponse:
        def __enter__(self) -> "_ZipResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            archive_bytes = io.BytesIO()
            with ZipFile(archive_bytes, "w") as archive:
                archive.writestr("run_manifest.json", json.dumps(_sample_payload("run_manifest"), sort_keys=True))
            return archive_bytes.getvalue()

    github_paths, github_downloads = provider_artifacts.download_github_actions_artifacts(
        [{"id": 1, "name": "ignored-without-url"}, {"id": 2, "name": "valid", "archive_download_url": "https://x/a.zip"}],
        destination=tmp_path / "github",
        urlopen=lambda _req: _ZipResponse(),
    )
    assert github_downloads == 1
    assert github_paths[0].name == "valid-2.zip"

    gitlab_paths, gitlab_downloads = provider_artifacts.download_gitlab_ci_artifacts(
        [{"name": "missing-id"}, {"id": 7, "name": "job", "artifacts_file": "not-a-mapping"}],
        destination=tmp_path / "gitlab",
        project="thales/agilab",
        urlopen=lambda _req: _ZipResponse(),
    )
    assert gitlab_downloads == 1
    assert gitlab_paths[0].name == "job-7-artifacts_zip.zip"


def test_provider_indexes_support_temporary_download_dirs_and_env_token(monkeypatch) -> None:
    class _Response:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return self.payload

    archive_bytes = io.BytesIO()
    with ZipFile(archive_bytes, "w") as archive:
        archive.writestr("run_manifest.json", json.dumps(_sample_payload("run_manifest"), sort_keys=True))
    archive_payload = archive_bytes.getvalue()

    def github_urlopen(req: object) -> _Response:
        url = str(getattr(req, "full_url"))
        if "actions/runs" in url:
            return _Response(
                json.dumps(
                    {
                        "total_count": 1,
                        "artifacts": [
                            {"id": 1, "name": "proof", "archive_download_url": "https://example.invalid/proof.zip"}
                        ],
                    }
                ).encode("utf-8")
            )
        return _Response(archive_payload)

    github_index = provider_artifacts.build_github_actions_artifact_index(
        repository="ThalesGroup/agilab",
        run_id="1",
        urlopen=github_urlopen,
    )
    assert github_index["summary"]["download_count"] == 1

    def gitlab_urlopen(req: object) -> _Response:
        url = str(getattr(req, "full_url"))
        if "/pipelines/" in url:
            return _Response(
                json.dumps([{"id": 2, "name": "proof", "artifacts_file": {"filename": "proof.zip"}}]).encode(
                    "utf-8"
                )
            )
        return _Response(archive_payload)

    gitlab_index = provider_artifacts.build_gitlab_ci_artifact_index(
        project="thales/agilab",
        pipeline_id="2",
        urlopen=gitlab_urlopen,
    )
    assert gitlab_index["summary"]["download_count"] == 1

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert provider_artifacts.token_from_env() is None
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    assert provider_artifacts.token_from_env() == "token"
