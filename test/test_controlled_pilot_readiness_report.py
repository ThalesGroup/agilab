from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path("tools/controlled_pilot_readiness_report.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "controlled_pilot_readiness_report_test_module", MODULE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_report_passes_controlled_pilot_contract() -> None:
    module = _load_module()

    report = module.build_report()

    assert report["schema"] == module.SCHEMA
    assert report["evidence_scope"] == "controlled-pilot deployment readiness"
    assert report["supported_score"] == module.SUPPORTED_SCORE
    assert report["status"] == "pass"
    assert report["summary"]["score_boundary"] == (
        "controlled-pilot readiness only; not production MLOps certification"
    )
    assert {check["id"] for check in report["checks"]} == {
        "service_health_execution",
        "service_failure_modes",
        "persisted_artifact_contract",
        "public_bind_and_secret_boundary",
        "compatibility_matrix_entry",
    }


def test_service_health_checks_cover_success_and_failure_modes() -> None:
    module = _load_module()

    success = module._check_service_health_execution(Path.cwd())
    failures = module._check_service_failure_modes(Path.cwd())

    assert success["status"] == "pass"
    assert success["details"]["exit_code"] == 0
    assert success["details"]["missing_prometheus_tokens"] == []
    assert failures["status"] == "pass"
    assert {
        name: result["exit_code"]
        for name, result in failures["details"]["cases"].items()
    } == {
        "unhealthy_workers": 2,
        "idle_without_ack": 4,
        "restart_rate": 5,
    }


def test_main_writes_compact_json_artifact(tmp_path: Path, capsys) -> None:
    module = _load_module()
    output = tmp_path / "controlled-pilot-readiness.json"

    exit_code = module.main(["--compact", "--output", str(output)])

    assert exit_code == 0
    stdout_payload = json.loads(capsys.readouterr().out)
    file_payload = json.loads(output.read_text(encoding="utf-8"))
    assert stdout_payload["schema"] == module.SCHEMA
    assert file_payload["status"] == "pass"


def test_required_source_markers_keep_missing_diagnostics(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / "fixture.py").write_text("SOURCE_MARKER_PRESENT\n", encoding="utf-8")

    missing = module._missing_required_markers(
        tmp_path,
        {"fixture.py": ["SOURCE_MARKER_PRESENT", "SOURCE_MARKER_ABSENT"]},
    )

    assert missing == {"fixture.py": ["SOURCE_MARKER_ABSENT"]}


@pytest.mark.parametrize("compact", [False, True], ids=["pretty", "compact"])
def test_controlled_pilot_json_contract_does_not_resolve_secrets(
    compact, tmp_path: Path, monkeypatch, capsys
) -> None:
    from agilab.security import secret_uri

    module = _load_module()
    sentinel = "synthetic-controlled-pilot-credential-20261006"
    monkeypatch.setenv("AGILAB_API_TOKEN", sentinel)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("source marker checks must not resolve credentials")

    monkeypatch.setattr(secret_uri, "resolve_secret_uri", forbidden)
    monkeypatch.setattr(secret_uri, "_default_keyring_getter", forbidden)
    output = tmp_path / "controlled-pilot-source-marker-evidence.json"
    argv = ["--output", str(output)]
    if compact:
        argv.append("--compact")

    exit_code = module.main(argv)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    saved = json.loads(output.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload == saved
    assert payload["schema"] == module.SCHEMA
    assert payload["summary"] == {
        "passed": 5, "failed": 0, "total": 5,
        "score_boundary": "controlled-pilot readiness only; not production MLOps certification",
    }
    health = next(check for check in payload["checks"] if check["id"] == "service_health_execution")
    assert health["details"]["missing_prometheus_tokens"] == []
    assert sentinel not in captured.out + captured.err + output.read_text(encoding="utf-8")
