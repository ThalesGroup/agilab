from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/kpi_evidence_bundle.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("kpi_evidence_bundle_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_bundle_passes_static_public_evidence_contracts() -> None:
    module = _load_module()

    bundle = module.build_bundle(run_hf_smoke=False)

    assert bundle["kpi"] == "Overall public evaluation"
    assert bundle["supported_score"] == "3.6 / 5"
    assert bundle["baseline_review_score"] == "3.2 / 5"
    assert bundle["status"] == "pass"
    assert bundle["summary"]["hf_smoke_executed"] is False
    assert bundle["summary"]["score_components"] == {
        "Ease of adoption": "3.5 / 5",
        "Research experimentation": "4.0 / 5",
        "Engineering prototyping": "4.0 / 5",
        "Production readiness": "3.0 / 5",
    }
    assert bundle["summary"]["score_formula"] == "(3.5 + 4.0 + 4.0 + 3.0) / 4 = 3.625"
    check_ids = {check["id"] for check in bundle["checks"]}
    assert check_ids == {
        "compatibility_matrix_public_paths",
        "newcomer_first_proof_contract",
        "hf_space_smoke_contract",
        "web_ui_robot_contract",
        "production_readiness_report_contract",
        "docs_mirror_stamp",
        "public_docs_evidence_links",
    }


def test_compatibility_matrix_requires_hf_demo_validated() -> None:
    module = _load_module()

    check = module._check_compatibility_matrix(Path.cwd())

    assert check["status"] == "pass"
    assert check["details"]["actual_statuses"]["agilab-hf-demo"] == "validated"


def test_optional_hf_smoke_run_is_explicit(monkeypatch) -> None:
    module = _load_module()

    @dataclass(frozen=True)
    class _FakeCheck:
        label: str
        success: bool
        duration_seconds: float
        detail: str
        url: str | None = None

    @dataclass(frozen=True)
    class _FakeRoute:
        label: str

    @dataclass(frozen=True)
    class _FakeSummary:
        success: bool
        total_duration_seconds: float
        target_seconds: float
        within_target: bool
        checks: list[_FakeCheck]

    class _FakeHfSmoke:
        DEFAULT_SPACE_ID = "jpmorard/agilab"
        DEFAULT_SPACE_URL = "https://jpmorard-agilab.hf.space"

        @staticmethod
        def route_specs():
            return [
                _FakeRoute(label)
                for label in (
                    "streamlit health",
                    "base app",
                    "flight project",
                    "flight view_maps",
                    "flight view_maps_network",
                )
            ]

        @staticmethod
        def check_public_app_tree():
            return None

        @staticmethod
        def run_smoke():
            return _FakeSummary(
                success=True,
                total_duration_seconds=1.0,
                target_seconds=30.0,
                within_target=True,
                checks=[_FakeCheck("public app tree", True, 1.0, "ok")],
            )

    original_loader = module._load_tool_module

    def _load_tool_module(repo_root, name):
        if name == "hf_space_smoke":
            return _FakeHfSmoke
        return original_loader(repo_root, name)

    monkeypatch.setattr(module, "_load_tool_module", _load_tool_module)

    bundle = module.build_bundle(run_hf_smoke=True)

    assert bundle["status"] == "pass"
    assert bundle["summary"]["hf_smoke_executed"] is True
    check = next(check for check in bundle["checks"] if check["id"] == "hf_space_smoke_run")
    assert check["executed"] is True
    assert check["details"]["checks"][0]["label"] == "public app tree"


def test_main_emits_json_and_returns_success(capsys) -> None:
    module = _load_module()

    exit_code = module.main(["--compact"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kpi"] == "Overall public evaluation"
    assert payload["status"] == "pass"
    assert payload["summary"]["failed"] == 0
