from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import urllib.error
from pathlib import Path

import pytest
from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "pypi_distribution_state.py"
SPEC = importlib.util.spec_from_file_location("pypi_distribution_state", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
pypi_distribution_state = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pypi_distribution_state
SPEC.loader.exec_module(pypi_distribution_state)

DistributionStateError = pypi_distribution_state.DistributionStateError
analyze_distribution_dir = pypi_distribution_state.analyze_distribution_dir
analyze_expected_project_distributions = pypi_distribution_state.analyze_expected_project_distributions
download_reused_artifacts = pypi_distribution_state.download_reused_artifacts
expected_distribution_filenames = pypi_distribution_state.expected_distribution_filenames
write_github_output = pypi_distribution_state.write_github_output
write_reused_artifact_manifests = pypi_distribution_state.write_reused_artifact_manifests


def test_pypi_distribution_state_marks_existing_artifacts(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / ".gitignore").write_text("*\n", encoding="utf-8")
    wheel = dist / "agi_env-2026.4.29.post2-py3-none-any.whl"
    wheel.write_bytes(b"")

    states = analyze_distribution_dir(
        dist,
        fetch_releases=lambda name: {"agi-env": {Version("2026.4.29.post2")}}[name],
    )

    assert len(states) == 1
    assert states[0].name == "agi-env"
    assert states[0].filename == "agi_env-2026.4.29.post2-py3-none-any.whl"
    assert states[0].exists is True
    assert states[0].latest == Version("2026.4.29.post2")


def test_pypi_distribution_state_rejects_stale_local_metadata(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "agilab-2026.4.29.post1-py3-none-any.whl"
    wheel.write_bytes(b"")

    with pytest.raises(DistributionStateError, match="PyPI latest for agilab is 2026.4.29.post2"):
        analyze_distribution_dir(
            dist,
            fetch_releases=lambda _name: {Version("2026.4.29.post2")},
        )


def test_pypi_distribution_state_writes_github_outputs(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "agilab-2026.4.29.post3-py3-none-any.whl").write_bytes(b"")

    states = analyze_distribution_dir(
        dist,
        fetch_releases=lambda _name: {Version("2026.4.29.post2")},
    )
    output = tmp_path / "github-output.txt"
    write_github_output(output, states)

    text = output.read_text(encoding="utf-8")
    assert "all-exist=false" in text
    assert "missing-count=1" in text
    assert "release-action=build" in text


def test_pypi_distribution_state_requires_exact_remote_filename(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "agilab-2026.5.12.post3-py3-none-any.whl").write_bytes(b"")
    (dist / "agilab-2026.5.12.post3.tar.gz").write_bytes(b"")

    states = analyze_distribution_dir(
        dist,
        fetch_distributions=lambda _name: {
            Version("2026.5.12.post3"): {"agilab-2026.5.12.post3-py3-none-any.whl"}
        },
    )

    by_filename = {state.filename: state for state in states}
    assert by_filename["agilab-2026.5.12.post3-py3-none-any.whl"].exists is True
    assert by_filename["agilab-2026.5.12.post3.tar.gz"].exists is False


def test_fetch_pypi_distribution_files_returns_empty_mapping_for_missing_project(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_not_found(*_args: object, **_kwargs: object) -> object:
        raise urllib.error.HTTPError(
            url="https://pypi.org/pypi/example-missing-package/json",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(pypi_distribution_state.urllib.request, "urlopen", raise_not_found)

    assert pypi_distribution_state.fetch_pypi_distribution_files("example-missing-package") == {}


def test_expected_distribution_filenames_match_wheel_and_sdist_policy() -> None:
    filenames = expected_distribution_filenames(
        "agi-app-multi-app-dag",
        Version("2026.5.18"),
        artifact_policy="wheel+sdist",
    )

    assert filenames == [
        "agi_app_multi_app_dag-2026.5.18-py3-none-any.whl",
        "agi_app_multi_app_dag-2026.5.18.tar.gz",
    ]


def test_expected_project_distribution_state_reuses_existing_remote_artifacts(tmp_path: Path) -> None:
    project = tmp_path / "agi-env"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        """
[project]
name = "agi-env"
version = "2026.5.18"
""".lstrip(),
        encoding="utf-8",
    )

    states = analyze_expected_project_distributions(
        package="agi-env",
        project=project,
        artifact_policy="wheel+sdist",
        fetch_distributions=lambda _name: {
            Version("2026.5.18"): {
                "agi_env-2026.5.18-py3-none-any.whl": {
                    "filename": "agi_env-2026.5.18-py3-none-any.whl",
                    "size": 123,
                    "url": "https://files.pythonhosted.org/packages/agi_env-2026.5.18.whl",
                    "digests": {"sha256": "a" * 64},
                },
                "agi_env-2026.5.18.tar.gz": {
                    "filename": "agi_env-2026.5.18.tar.gz",
                    "size": 456,
                    "url": "https://files.pythonhosted.org/packages/agi_env-2026.5.18.tar.gz",
                    "digests": {"sha256": "b" * 64},
                },
            }
        },
    )

    assert [state.filename for state in states] == [
        "agi_env-2026.5.18-py3-none-any.whl",
        "agi_env-2026.5.18.tar.gz",
    ]
    assert all(state.exists for state in states)
    assert {state.kind for state in states} == {"wheel", "sdist"}
    assert {state.sha256 for state in states} == {"a" * 64, "b" * 64}


def test_expected_project_distribution_state_rejects_package_metadata_mismatch(tmp_path: Path) -> None:
    project = tmp_path / "agi-env"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        """
[project]
name = "agi-core"
version = "2026.5.18"
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(DistributionStateError, match="declares package agi-core, expected agi-env"):
        analyze_expected_project_distributions(
            package="agi-env",
            project=project,
            artifact_policy="wheel-only",
            fetch_distributions=lambda _name: {},
        )


def test_reused_artifact_manifests_record_remote_hashes(tmp_path: Path) -> None:
    project = tmp_path / "agilab"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        """
[project]
name = "agilab"
version = "2026.5.18"
""".lstrip(),
        encoding="utf-8",
    )
    states = analyze_expected_project_distributions(
        package="agilab",
        project=project,
        artifact_policy="wheel-only",
        fetch_distributions=lambda _name: {
            Version("2026.5.18"): {
                "agilab-2026.5.18-py3-none-any.whl": {
                    "filename": "agilab-2026.5.18-py3-none-any.whl",
                    "size": 789,
                    "url": "https://files.pythonhosted.org/packages/agilab-2026.5.18.whl",
                    "digests": {"sha256": "c" * 64},
                },
            }
        },
    )

    json_path, sums_path = write_reused_artifact_manifests(
        states,
        output_dir=tmp_path / "evidence",
        output_prefix="agilab",
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "agilab.release_artifact_manifest.v1"
    assert payload["source"] == "pypi"
    assert payload["reused"] is True
    assert payload["artifacts"] == [
        {
            "filename": "agilab-2026.5.18-py3-none-any.whl",
            "name": "agilab",
            "version": "2026.5.18",
            "kind": "wheel",
            "size": 789,
            "sha256": "c" * 64,
        }
    ]
    assert sums_path.read_text(encoding="utf-8") == (
        f"{'c' * 64}  agilab-2026.5.18-py3-none-any.whl\n"
    )


def test_download_reused_artifacts_verifies_remote_hashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "agilab"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        """
[project]
name = "agilab"
version = "2026.5.18"
""".lstrip(),
        encoding="utf-8",
    )
    wheel_bytes = b"published wheel"
    states = analyze_expected_project_distributions(
        package="agilab",
        project=project,
        artifact_policy="wheel-only",
        fetch_distributions=lambda _name: {
            Version("2026.5.18"): {
                "agilab-2026.5.18-py3-none-any.whl": {
                    "filename": "agilab-2026.5.18-py3-none-any.whl",
                    "size": len(wheel_bytes),
                    "url": "https://files.pythonhosted.org/packages/agilab-2026.5.18.whl",
                    "digests": {"sha256": hashlib.sha256(wheel_bytes).hexdigest()},
                },
            }
        },
    )

    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return wheel_bytes

    monkeypatch.setattr(
        pypi_distribution_state.urllib.request,
        "urlopen",
        lambda url, timeout: FakeResponse(),
    )

    paths = download_reused_artifacts(states, download_dir=tmp_path / "dist")

    assert [path.name for path in paths] == ["agilab-2026.5.18-py3-none-any.whl"]
    assert paths[0].read_bytes() == wheel_bytes
