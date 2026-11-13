"""Exercise the installed public-package gate without installing another package."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_qualifier():
    path = ROOT / "tools/testing/public_install_qualification.py"
    spec = importlib.util.spec_from_file_location(
        "public_install_qualification_test", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_install(
    monkeypatch, module, installed_version, *, outside=None, proof_ok=True
):
    calls = []
    environment = None

    def run(argv, **kwargs):
        nonlocal environment
        calls.append(list(argv))
        if argv[1:3] == ["-m", "venv"]:
            environment = Path(argv[3])
        if "first-proof" in argv:
            return subprocess.CompletedProcess(
                argv, 0, json.dumps({"success": proof_ok, "within_target": True}), ""
            )
        return subprocess.CompletedProcess(argv, 0, "", "")

    def check_output(argv, **kwargs):
        assert environment is not None
        location = outside or environment / "lib/site-packages/agilab/__init__.py"
        return json.dumps({"module": str(location), "version": installed_version})

    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module.subprocess, "check_output", check_output)
    return calls


@pytest.mark.parametrize(
    ("installed_version", "passes"),
    [
        ("2026.11.2", True),
        ("2026.11.02", True),
        ("2026.11.3", False),
        ("2026.11.20", False),
        ("2026.11.2.post1", False),
        ("2026.11.2rc1", False),
        ("2026.11.2.dev1", False),
        ("2026.11.2+local", False),
    ],
)
def test_public_install_accepts_only_the_pinned_release(
    monkeypatch, tmp_path, installed_version, passes
):
    module = _load_qualifier()
    calls = _fake_install(monkeypatch, module, installed_version)
    output = tmp_path / "qualification.json"
    monkeypatch.chdir(tmp_path)

    result = module.qualify(output)

    assert result["status"] == ("passed" if passes else "failed")
    assert any("first-proof" in call for call in calls) is passes
    assert result["version"] == "2026.11.02"
    assert result["installed"]["version"] == installed_version
    assert json.loads(output.read_text()) == result
    if not passes:
        assert "differs from the manifest pin" in result["error"]


def test_normalized_version_does_not_accept_an_external_package(monkeypatch, tmp_path):
    module = _load_qualifier()
    calls = _fake_install(
        monkeypatch,
        module,
        "2026.11.2",
        outside=tmp_path / "external/agilab/__init__.py",
    )

    result = module.qualify(tmp_path / "qualification.json")

    assert result["status"] == "failed"
    assert "outside the isolated environment" in result["error"]
    assert not any("first-proof" in call for call in calls)


def test_normalized_version_still_requires_a_successful_installed_proof(
    monkeypatch, tmp_path
):
    module = _load_qualifier()
    calls = _fake_install(monkeypatch, module, "2026.11.2", proof_ok=False)

    result = module.qualify(tmp_path / "qualification.json")

    assert result["status"] == "failed"
    assert any("first-proof" in call for call in calls)
    assert result["first_proof"]["success"] is False
    assert "Installed public first-proof failed" in result["error"]


def test_missing_installer_version_policy_is_a_failed_receipt(monkeypatch, tmp_path):
    module = _load_qualifier()
    calls = _fake_install(monkeypatch, module, "2026.11.2")
    monkeypatch.setattr(
        module.importlib.util, "spec_from_file_location", lambda *args: None
    )

    result = module.qualify(tmp_path / "qualification.json")

    assert result["status"] == "failed"
    assert "version policy is unavailable" in result["error"]
    assert not any("first-proof" in call for call in calls)
