from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from zipfile import ZipFile

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
from agilab.ci_provider_artifacts import (
    build_artifact_index_from_archives,
    build_github_actions_artifact_index,
    write_sample_github_actions_archive,
    write_sample_github_actions_directory,
)


TOOL_PATH = Path("tools/github_actions_artifact_index.py").resolve()


def _load_tool_module():
    spec = importlib.util.spec_from_file_location(
        "github_actions_artifact_index_test_module",
        TOOL_PATH,
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
    assert index["summary"]["provider_query_count"] == 1
    assert index["summary"]["download_count"] == 1
    assert index["summary"]["network_probe_count"] == 2
    assert index["provenance"]["queries_ci_provider"] is True
    assert index["provenance"]["downloads_provider_archives"] is True
    assert index["summary"]["missing_required_count"] == 3
