from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess


MODULE_PATH = Path("tools/install_release_proof_package.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "install_release_proof_package_test_module",
        MODULE_PATH,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_release_package_spec_reads_manifest_version(tmp_path: Path) -> None:
    module = _load_module()
    manifest = tmp_path / "release_proof.toml"
    manifest.write_text(
        "[release]\n"
        'package_name = "agilab"\n'
        'package_version = "2026.05.05.post2"\n',
        encoding="utf-8",
    )

    assert module.release_package_spec(manifest) == (
        "agilab",
        "2026.05.05.post2",
        "agilab==2026.05.05.post2",
    )


def test_release_package_spec_includes_manifest_extras(tmp_path: Path) -> None:
    module = _load_module()
    manifest = tmp_path / "release_proof.toml"
    manifest.write_text(
        "[release]\n"
        'package_name = "agilab"\n'
        'package_version = "2026.05.05.post2"\n'
        'package_extras = ["ui", "examples"]\n',
        encoding="utf-8",
    )

    assert module.release_package_spec(manifest) == (
        "agilab",
        "2026.05.05.post2",
        "agilab[examples,ui]==2026.05.05.post2",
    )


def test_current_release_proof_installs_public_example_payload() -> None:
    module = _load_module()

    package_name, _package_version, package_spec = module.release_package_spec(
        Path("docs/source/data/release_proof.toml")
    )

    assert package_name == "agilab"
    assert package_spec.startswith("agilab[")
    assert "examples" in package_spec


def test_install_with_retry_uses_exact_spec_and_refreshes_index(monkeypatch) -> None:
    module = _load_module()
    install_calls: list[list[str]] = []
    sleeps: list[float] = []
    monkeypatch.setattr(
        module.metadata,
        "version",
        lambda _package_name: "2026.5.5.post2",
    )

    def runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        install_calls.append(cmd)
        return subprocess.CompletedProcess(
            cmd,
            returncode=1 if len(install_calls) == 1 else 0,
        )

    rc = module.install_with_retry(
        "agilab",
        "agilab==2026.05.05.post2",
        retries=2,
        delay_seconds=0.25,
        runner=runner,
        sleeper=sleeps.append,
        diagnose=False,
    )

    assert rc == 0
    assert [call[-1] for call in install_calls] == [
        "agilab==2026.05.05.post2",
        "agilab==2026.05.05.post2",
    ]
    assert all("--no-cache-dir" in call for call in install_calls)
    assert sleeps == [0.25]


class _JsonResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> "_JsonResponse":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_pypi_release_visible_normalizes_zero_padded_calendar_versions() -> None:
    module = _load_module()

    def opener(_url: str, *, timeout: float) -> _JsonResponse:
        assert timeout == 20.0
        return _JsonResponse({"releases": {"2026.5.12.post3": []}})

    assert module.pypi_release_visible(
        "agilab",
        "2026.05.12.post3",
        opener=opener,
    )


def test_pypi_release_visible_returns_false_when_release_is_absent() -> None:
    module = _load_module()

    def opener(_url: str, *, timeout: float) -> _JsonResponse:
        assert timeout == 20.0
        return _JsonResponse({"releases": {"2026.5.12.post2": []}})

    assert not module.pypi_release_visible(
        "agilab",
        "2026.05.12.post3",
        opener=opener,
    )
