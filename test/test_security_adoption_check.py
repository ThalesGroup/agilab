from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/security_adoption_check.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("security_adoption_check_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_adoption_check_writes_advisory_artifact_without_blocking(tmp_path: Path, monkeypatch, capsys):
    module = _load_module()
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "security-check.json"

    rc = module.main(["--output", str(output)])

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert rc == 0
    assert payload["schema"] == "agilab.security_check.v1"
    assert payload["status"] == "fail"
    assert payload["summary"]["profile"] == "shared"
    output_text = capsys.readouterr().out
    assert "profile=shared" in output_text
    assert "mode=advisory" in output_text


def test_adoption_check_strict_env_fails_on_warnings(tmp_path: Path, monkeypatch):
    module = _load_module()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGILAB_SECURITY_CHECK_STRICT", "1")

    rc = module.main(["--output", str(tmp_path / "security-check.json")])

    assert rc == 1
