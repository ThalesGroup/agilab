from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPORT_PATH = Path("tools/data_connector_live_ui_report.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_data_connector_live_ui_report_passes(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "data_connector_live_ui_report_test_module")

    report = module.build_report(
        repo_root=Path.cwd(),
        output_path=tmp_path / "data_connector_live_ui.json",
    )

    assert report["report"] == "Data connector live UI report"
    assert report["status"] == "pass"
    assert report["summary"]["schema"] == "agilab.data_connector_live_ui.v1"
    assert report["summary"]["run_status"] == "ready_for_live_ui"
    assert report["summary"]["execution_mode"] == "streamlit_render_contract_only"
    assert report["summary"]["connector_card_count"] == 5
    assert report["summary"]["page_binding_count"] == 2
    assert report["summary"]["legacy_fallback_count"] == 2
    assert report["summary"]["health_probe_status_count"] == 5
    assert report["summary"]["streamlit_metric_count"] == 4
    assert report["summary"]["streamlit_dataframe_count"] == 4
    assert report["summary"]["network_probe_count"] == 0
    assert report["summary"]["operator_opt_in_required_for_health"] is True
    assert report["summary"]["release_decision_hooked"] is True
    assert report["summary"]["round_trip_ok"] is True
    assert {check["id"] for check in report["checks"]} == {
        "data_connector_live_ui_schema",
        "data_connector_live_ui_release_decision_hook",
        "data_connector_live_ui_components",
        "data_connector_live_ui_health_boundary",
        "data_connector_live_ui_release_decision_provenance",
        "data_connector_live_ui_no_network",
        "data_connector_live_ui_persistence",
        "data_connector_live_ui_docs_reference",
    }


def test_data_connector_live_ui_persists_render_contract(tmp_path: Path) -> None:
    module = _load_module(REPORT_PATH, "data_connector_live_ui_report_json_test_module")
    json_path = tmp_path / "data_connector_live_ui.json"

    report = module.build_report(repo_root=Path.cwd(), output_path=json_path)

    assert report["status"] == "pass"
    payload = module.json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "agilab.data_connector_live_ui.v1"
    assert payload["summary"]["streamlit_call_methods"]["dataframe"] == 4
    assert payload["render_payload"]["summary"]["page_ids"] == ["release_decision"]
    assert payload["render_payload"]["provenance"]["executes_network_probe"] is False


def test_data_connector_live_ui_recorder_and_fallback_helpers() -> None:
    module = _load_module(REPORT_PATH, "data_connector_live_ui_helpers_test_module")
    from agilab import data_connector_live_ui as core_module

    recorder = core_module.StreamlitCallRecorder()
    with recorder as active:
        active.dataframe([{"a": 1}, {"a": 2}])
        active.columns(("left", "right"))

    assert [call["method"] for call in recorder.calls] == [
        "__enter__",
        "dataframe",
        "columns",
        "__exit__",
    ]
    assert recorder.calls[1]["row_count"] == 2
    assert core_module._call(object(), "missing") is None

    class TupleColumns:
        def columns(self, _count: int):
            return ("left", "right")

    class BadColumns:
        def columns(self, _count: int):
            return ["only-one"]

    assert core_module._columns(TupleColumns(), 2) == ["left", "right"]
    fallback_columns = core_module._columns(BadColumns(), 2)
    assert len(fallback_columns) == 2
    assert all(isinstance(column, BadColumns) for column in fallback_columns)

    payload = core_module.render_connector_live_ui(
        object(),
        {
            "schema": core_module.UI_PREVIEW_SCHEMA,
            "run_status": "ready_for_ui_preview",
            "summary": {"execution_mode": "static_ui_preview_only"},
            "connector_cards": [{"status": "unknown_not_probed"}],
            "health_probes": [{"operator_context_required": False}],
            "provenance": {"operator_opt_in_required_for_health": True},
        },
    )

    assert payload["run_status"] == "ready_for_live_ui"
    assert payload["summary"]["operator_opt_in_required_for_health"] is False
    assert module.REPO_ROOT.name == "agilab"

    warning_recorder = core_module.StreamlitCallRecorder()
    core_module.render_connector_live_ui(
        warning_recorder,
        {
            "schema": core_module.UI_PREVIEW_SCHEMA,
            "run_status": "ready_for_ui_preview",
            "summary": {"execution_mode": "static_ui_preview_only"},
            "connector_cards": [],
            "health_probes": [],
            "provenance": {"operator_opt_in_required_for_health": False},
        },
    )
    assert any(call["method"] == "warning" for call in warning_recorder.calls)


def test_data_connector_live_ui_reports_missing_hook_and_invalid_preview(tmp_path: Path) -> None:
    _load_module(REPORT_PATH, "data_connector_live_ui_invalid_test_module")
    from agilab import data_connector_live_ui as core_module

    missing_hook = core_module.release_decision_live_ui_hook(tmp_path / "missing.py")
    assert missing_hook["loaded"] is False
    assert missing_hook["imports_renderer"] is False

    state = core_module.build_data_connector_live_ui(
        settings={},
        catalog={},
        settings_path=tmp_path / "app_settings.toml",
        catalog_path=tmp_path / "connectors.toml",
        release_decision_page=tmp_path / "missing.py",
    )

    assert state["run_status"] == "invalid"
    assert {
        issue["message"] for issue in state["issues"]
    } >= {
        "connector live UI payload is not ready",
        "release decision hook missing loaded",
    }
    assert state["summary"]["release_decision_hooked"] is False


def test_data_connector_live_ui_persist_accepts_relative_paths(tmp_path: Path) -> None:
    _load_module(REPORT_PATH, "data_connector_live_ui_persist_test_module")
    from agilab import data_connector_live_ui as core_module

    repo_root = tmp_path / "repo"
    settings_path = repo_root / "config" / "app_settings.toml"
    catalog_path = repo_root / "config" / "connectors.toml"
    page_path = repo_root / "pages" / "release_decision.py"
    settings_path.parent.mkdir(parents=True)
    page_path.parent.mkdir(parents=True)
    settings_path.write_text(
        """
[connector_catalog]
path = "config/connectors.toml"

[connector_refs]
warehouse = "warehouse_sql"
search = "ops_opensearch"
artifacts = "artifact_object_store"

[page_connector_refs.release_decision]
evidence_index = "ops_opensearch"
artifact_store = "artifact_object_store"

[legacy_paths]
artifact_root = "~/agilab/artifacts"
telemetry_csv = "~/agilab/telemetry.csv"
""",
        encoding="utf-8",
    )
    catalog_path.write_text(
        """
[[connectors]]
id = "warehouse_sql"
kind = "sql"
label = "Warehouse SQL"
uri = "sqlite:///warehouse.db"
driver = "sqlite"
query_mode = "read_only"

[[connectors]]
id = "ops_opensearch"
kind = "opensearch"
label = "Operations OpenSearch"
url = "https://opensearch.example.invalid"
index = "agilab-runs-*"
auth_ref = "env:OPENSEARCH_TOKEN"

[[connectors]]
id = "artifact_object_store"
kind = "object_storage"
label = "Artifact Object Store"
provider = "s3"
bucket = "agilab-artifacts"
prefix = "experiments/"
auth_ref = "env:AWS_PROFILE"
""",
        encoding="utf-8",
    )
    page_path.write_text(
        """
from agilab.data_connector_ui_preview import build_data_connector_ui_preview
from agilab.data_connector_live_ui import render_connector_live_ui

release_decision_connector_live_ui = render_connector_live_ui(
    st,
    build_data_connector_ui_preview(settings={}, catalog={}, settings_path="", catalog_path=""),
)
""",
        encoding="utf-8",
    )

    proof = core_module.persist_data_connector_live_ui(
        repo_root=repo_root,
        output_path=tmp_path / "live-ui.json",
        settings_path=Path("config/app_settings.toml"),
        catalog_path=Path("config/connectors.toml"),
        release_decision_page=Path("pages/release_decision.py"),
    )

    assert proof["ok"] is True
    assert proof["settings_path"] == str(settings_path)
    assert proof["catalog_path"] == str(catalog_path)
    assert proof["release_decision_page"] == str(page_path)
