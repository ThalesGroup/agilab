from __future__ import annotations

import importlib.util
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
write_github_output = pypi_distribution_state.write_github_output


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

    assert "all-exist=false" in output.read_text(encoding="utf-8")
    assert "missing-count=1" in output.read_text(encoding="utf-8")


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
