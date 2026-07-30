from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "maintenance_dashboard.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("maintenance_dashboard_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_maintenance_dashboard_exposes_long_term_contract_checks() -> None:
    module = _load_module()

    report = module.build_report(
        repo_root=ROOT,
        include_app_contracts=False,
        include_hotspots=False,
    )

    assert report["schema"] == "agilab.maintenance_dashboard.v1"
    check_ids = {check["id"] for check in report["checks"]}
    assert {
        "extension_contract_kit",
        "architecture_decision_records",
        "docs_mirror",
        "package_split_contract",
        "release_skip_existing_packages",
        "evidence_core_docs",
        "product_tier_labels",
        "shared_core_guardrails",
        "generated_artifact_hygiene",
        "coverage_badge_signal",
    } <= check_ids


def test_docs_mirror_fails_for_explicit_missing_canonical_source_after_target_check(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    configured_source = tmp_path / "canonical-docs" / "source"
    calls: list[str] = []

    def verify_target(_target: Path) -> tuple[bool, str]:
        calls.append("target")
        return True, "target integrity verified"

    def verify_canonical(
        _target: Path,
        source: Path,
        *,
        source_required: bool,
    ) -> tuple[str, str]:
        calls.append("canonical")
        assert source == configured_source
        assert source_required is True
        return "fail", f"configured canonical docs source not found: {source}"

    fake_sync_docs = SimpleNamespace(
        verify_target_mirror_integrity=verify_target,
        canonical_source_configuration=lambda _repo_root: SimpleNamespace(
            path=configured_source,
            origin="env:AGILAB_DOCS_SOURCE",
            required=True,
        ),
        verify_canonical_mirror_alignment=verify_canonical,
    )
    monkeypatch.setattr(module, "_load_tool", lambda *_args: fake_sync_docs)

    check = module.check_docs_mirror(ROOT).as_dict()

    assert check["status"] == "fail"
    assert "configured canonical docs source not found" in check["summary"]
    assert check["details"]["source"] == configured_source.as_posix()
    assert check["details"]["target_integrity_ok"] is True
    assert check["details"]["canonical_alignment_checked"] is False
    assert calls == ["target", "canonical"]


def test_docs_mirror_default_missing_source_warns_after_target_integrity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    default_source = tmp_path / "missing-default-source"
    fake_sync_docs = SimpleNamespace(
        verify_target_mirror_integrity=lambda _target: (
            True,
            "target integrity verified",
        ),
        canonical_source_configuration=lambda _repo_root: SimpleNamespace(
            path=default_source,
            origin="default",
            required=False,
        ),
        verify_canonical_mirror_alignment=lambda *_args, **_kwargs: (
            "skipped",
            "canonical drift NOT CHECKED",
        ),
    )
    monkeypatch.setattr(module, "_load_tool", lambda *_args: fake_sync_docs)

    check = module.check_docs_mirror(ROOT).as_dict()

    assert check["status"] == "warn"
    assert check["details"]["target_integrity_ok"] is True
    assert check["details"]["canonical_alignment_checked"] is False
    assert "canonical drift NOT CHECKED" in check["summary"]


def test_docs_mirror_target_failure_blocks_canonical_alignment(monkeypatch) -> None:
    module = _load_module()

    def unexpected_configuration(_repo_root: Path):
        raise AssertionError("canonical configuration must not be read")

    fake_sync_docs = SimpleNamespace(
        verify_target_mirror_integrity=lambda _target: (
            False,
            "target stamp mismatch",
        ),
        canonical_source_configuration=unexpected_configuration,
    )
    monkeypatch.setattr(module, "_load_tool", lambda *_args: fake_sync_docs)

    check = module.check_docs_mirror(ROOT).as_dict()

    assert check["status"] == "fail"
    assert "target integrity failed" in check["summary"]
    assert check["details"]["canonical_alignment_checked"] is False


def test_docs_mirror_drift_failure_summary_does_not_claim_alignment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    canonical_source = tmp_path / "canonical"
    canonical_source.mkdir()
    plan = SimpleNamespace(created=["new.rst"], updated=[], deleted=[])
    fake_sync_docs = SimpleNamespace(
        verify_target_mirror_integrity=lambda _target: (
            True,
            "target integrity verified",
        ),
        canonical_source_configuration=lambda _repo_root: SimpleNamespace(
            path=canonical_source,
            origin="env:AGILAB_DOCS_SOURCE",
            required=True,
        ),
        make_sync_plan=lambda *_args, **_kwargs: plan,
        canonical_mirror_alignment_result=lambda *_args, **_kwargs: SimpleNamespace(
            status="fail",
            message="canonical source drift: create=1 update=0 delete=0",
            checked=True,
        ),
    )
    monkeypatch.setattr(module, "_load_tool", lambda *_args: fake_sync_docs)

    check = module.check_docs_mirror(ROOT).as_dict()

    assert check["status"] == "fail"
    assert "canonical source drift" in check["summary"]
    assert "are aligned" not in check["summary"]
    assert check["details"]["canonical_alignment_checked"] is True
    assert check["details"]["create"] == 1


def test_docs_mirror_does_not_claim_unfinished_structured_alignment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_module()
    canonical_source = tmp_path / "canonical"
    canonical_source.mkdir()
    fake_sync_docs = SimpleNamespace(
        verify_target_mirror_integrity=lambda _target: (
            True,
            "target integrity verified",
        ),
        canonical_source_configuration=lambda _repo_root: SimpleNamespace(
            path=canonical_source,
            origin="env:AGILAB_DOCS_SOURCE",
            required=True,
        ),
        make_sync_plan=lambda *_args, **_kwargs: SimpleNamespace(
            created=[],
            updated=[],
            deleted=[],
        ),
        canonical_mirror_alignment_result=lambda *_args, **_kwargs: SimpleNamespace(
            status="fail",
            message="canonical source changed while alignment was checked",
            checked=False,
        ),
    )
    monkeypatch.setattr(module, "_load_tool", lambda *_args: fake_sync_docs)

    check = module.check_docs_mirror(ROOT).as_dict()

    assert check["status"] == "fail"
    assert "changed while alignment" in check["summary"]
    assert check["details"]["canonical_alignment_checked"] is False


def test_extension_contract_kit_declares_required_extension_types() -> None:
    module = _load_module()

    check = module.check_extension_contract_kit(ROOT).as_dict()

    assert check["status"] == "pass"
    assert set(module.REQUIRED_EXTENSION_TYPES) <= set(check["details"]["type_ids"])
    assert check["details"]["missing_types"] == []
    assert check["details"]["malformed"] == []


def test_release_friction_check_proves_skip_existing_mode_without_network() -> None:
    module = _load_module()

    check = module.check_release_friction(ROOT).as_dict()

    assert check["status"] == "pass"
    assert check["details"]["pypi_selection_mode"] == "missing-artifacts"
    assert check["details"]["pypi_publish_selected"] == "false"
    assert check["details"]["existing_count"] > 0


def test_maintenance_dashboard_cli_writes_machine_readable_report(tmp_path: Path, capsys) -> None:
    module = _load_module()
    output = tmp_path / "maintenance.json"

    rc = module.main(
        [
            "--repo-root",
            str(ROOT),
            "--skip-app-contracts",
            "--skip-hotspots",
            "--output",
            str(output),
            "--compact",
        ]
    )

    captured = capsys.readouterr()
    assert rc in {0, 1}
    report = json.loads(output.read_text(encoding="utf-8"))
    stdout_report = json.loads(captured.out)
    assert report["schema"] == "agilab.maintenance_dashboard.v1"
    assert stdout_report["summary"]["check_count"] == report["summary"]["check_count"]


def test_coverage_badge_signal_passes_above_floor_and_reports_aspiration(tmp_path: Path) -> None:
    module = _load_module()
    badge = tmp_path / "badges" / "coverage-agilab.svg"
    badge.parent.mkdir()
    badge.write_text("<svg><text>coverage: 97%</text></svg>\n", encoding="utf-8")

    check = module.check_coverage_badges(tmp_path).as_dict()

    assert check["status"] == "pass"
    assert check["details"]["percent"] == 97
    assert check["details"]["warning_floor"] == module.COVERAGE_WARNING_FLOOR
    assert check["details"]["aspirational_target"] == module.COVERAGE_ASPIRATIONAL_TARGET
    assert check["details"]["gap_to_aspirational_target"] == 2


def test_coverage_badge_signal_warns_below_floor(tmp_path: Path) -> None:
    module = _load_module()
    badge = tmp_path / "badges" / "coverage-agilab.svg"
    badge.parent.mkdir()
    badge.write_text("<svg><text>coverage: 94%</text></svg>\n", encoding="utf-8")

    check = module.check_coverage_badges(tmp_path).as_dict()

    assert check["status"] == "warn"
    assert check["details"]["percent"] == 94


def test_todo_hotspot_scanner_counts_real_comment_markers_only(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "src" / "agilab" / "sample.py"
    docs = tmp_path / "docs" / "source" / "maintenance.rst"
    source.parent.mkdir(parents=True)
    docs.parent.mkdir(parents=True)
    source.write_text(
        'label = "TODO/FIXME hotspot vocabulary is not backlog"\n'
        "# TODO tighten this sample later\n",
        encoding="utf-8",
    )
    docs.write_text("The dashboard reports TODO/FIXME hotspot vocabulary.\n", encoding="utf-8")

    check = module.check_todo_hotspots(tmp_path).as_dict()

    assert check["status"] == "warn"
    assert check["details"]["total"] == 1
    assert check["details"]["top"] == [("src/agilab/sample.py", 1)]
