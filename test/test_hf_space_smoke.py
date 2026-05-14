from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/hf_space_smoke.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("hf_space_smoke_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_space_url_encodes_current_page_query() -> None:
    module = _load_module()
    spec = module.route_specs()[3]

    url = module.build_space_url("https://demo.hf.space/", spec)

    assert url.startswith("https://demo.hf.space?")
    assert "active_app=flight_telemetry_project" in url
    assert "current_page=%2Fapp%2Fsrc%2Fagilab%2Fapps-pages%2Fview_maps%2Fsrc%2Fview_maps%2Fview_maps.py" in url


def test_build_space_url_encodes_meteo_view_query() -> None:
    module = _load_module()
    spec = module.route_specs()[5]

    url = module.build_space_url("https://demo.hf.space/", spec)

    assert url.startswith("https://demo.hf.space?")
    assert "active_app=weather_forecast_project" in url
    assert (
        "current_page=%2Fapp%2Fsrc%2Fagilab%2Fapps-pages%2Fview_forecast_analysis"
        "%2Fsrc%2Fview_forecast_analysis%2Fview_forecast_analysis.py"
    ) in url


def test_private_app_entries_flags_only_direct_non_public_apps() -> None:
    module = _load_module()

    offenders = module.private_app_entries(
        [
            {"path": "src/agilab/apps/builtin"},
            {"path": "src/agilab/apps/install.py"},
            {"path": "src/agilab/apps/uav_graph_routing_project"},
            {"path": "src/agilab/apps/builtin/flight_telemetry_project"},
        ]
    )

    assert offenders == ["uav_graph_routing_project"]


def test_unexpected_page_entries_flags_only_direct_extra_pages() -> None:
    module = _load_module()

    offenders = module.unexpected_page_entries(
        [
            {"path": "src/agilab/apps-pages/README.md"},
            {"path": "src/agilab/apps-pages/view_maps"},
            {"path": "src/agilab/apps-pages/view_forecast_analysis"},
            {"path": "src/agilab/apps-pages/view_release_decision"},
            {"path": "src/agilab/apps-pages/view_scenario_cockpit"},
            {"path": "src/agilab/apps-pages/view_maps_network"},
            {"path": "src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py"},
        ]
    )

    assert offenders == ["view_maps_network"]


def test_unexpected_core_page_entries_flags_stale_renamed_pages() -> None:
    module = _load_module()

    offenders = module.unexpected_core_page_entries(
        [
            {"path": "src/agilab/pages/1_PROJECT.py"},
            {"path": "src/agilab/pages/2_ORCHESTRATE.py"},
            {"path": "src/agilab/pages/3_WORKFLOW.py"},
            {"path": "src/agilab/pages/4_ANALYSIS.py"},
            {"path": "src/agilab/pages/1_\u25b6\ufe0f PROJECT.py"},
            {"path": "src/agilab/pages/3_PIPELINE.py"},
            {"path": "src/agilab/pages/1_PROJECT.py/child"},
        ]
    )

    assert offenders == ["1_\u25b6\ufe0f PROJECT.py", "3_PIPELINE.py"]


def test_check_route_rejects_localhost_connection_body() -> None:
    module = _load_module()

    def _fetcher(_url: str, _timeout: float):
        return 200, "iframe refused to connect to 127.0.0.1"

    result = module.check_route(
        "https://demo.hf.space",
        module.RouteSpec("demo"),
        timeout=1.0,
        fetcher=_fetcher,
        clock=iter([0.0, 0.2]).__next__,
    )

    assert result.success is False
    assert "127.0.0.1" in result.detail


def test_check_route_rejects_streamlit_api_exception_body() -> None:
    module = _load_module()

    def _fetcher(_url: str, _timeout: float):
        return 200, "streamlit.errors.StreamlitAPIException: Multiple Pages specified"

    result = module.check_route(
        "https://demo.hf.space",
        module.RouteSpec("demo"),
        timeout=1.0,
        fetcher=_fetcher,
        clock=iter([0.0, 0.2]).__next__,
    )

    assert result.success is False
    assert "streamlitapiexception" in result.detail


def test_run_smoke_summarizes_routes_and_public_app_tree() -> None:
    module = _load_module()
    clock = iter(
        [
            0.0,
            0.1,
            0.1,
            0.3,
            0.3,
            0.6,
            0.6,
            1.0,
            1.0,
            1.5,
            1.5,
            2.1,
            2.1,
            2.8,
            2.8,
            3.6,
            3.6,
            4.5,
        ]
    )

    def _fetch_text(_url: str, _timeout: float):
        return 200, "ok"

    def _fetch_json(_url: str, _timeout: float):
        if _url.endswith("src/agilab/apps"):
            return [{"path": "src/agilab/apps/builtin"}, {"path": "src/agilab/apps/install.py"}]
        if _url.endswith("src/agilab/pages"):
            return [
                {"path": "src/agilab/pages/1_PROJECT.py"},
                {"path": "src/agilab/pages/2_ORCHESTRATE.py"},
                {"path": "src/agilab/pages/3_WORKFLOW.py"},
                {"path": "src/agilab/pages/4_ANALYSIS.py"},
            ]
        return [
            {"path": "src/agilab/apps-pages/view_maps"},
            {"path": "src/agilab/apps-pages/view_forecast_analysis"},
            {"path": "src/agilab/apps-pages/view_release_decision"},
        ]

    summary = module.run_smoke(
        space_id="demo/agilab",
        space_url="https://demo.hf.space",
        timeout=1.0,
        target_seconds=5.0,
        fetch_text_fn=_fetch_text,
        fetch_json_fn=_fetch_json,
        clock=clock.__next__,
    )

    assert summary.success is True
    assert summary.total_duration_seconds == 4.5
    assert summary.within_target is True
    assert [check.label for check in summary.checks][-3:] == [
        "public app tree",
        "public pages tree",
        "core pages tree",
    ]


def test_run_tree_checks_uses_only_repository_tree_checks() -> None:
    module = _load_module()
    clock = iter([0.0, 0.1, 0.1, 0.3, 0.3, 0.6])

    def _fetch_json(_url: str, _timeout: float):
        if _url.endswith("src/agilab/apps"):
            return [{"path": "src/agilab/apps/builtin"}, {"path": "src/agilab/apps/install.py"}]
        if _url.endswith("src/agilab/pages"):
            return [
                {"path": "src/agilab/pages/1_PROJECT.py"},
                {"path": "src/agilab/pages/2_ORCHESTRATE.py"},
                {"path": "src/agilab/pages/3_WORKFLOW.py"},
                {"path": "src/agilab/pages/4_ANALYSIS.py"},
            ]
        return [
            {"path": "src/agilab/apps-pages/view_maps"},
            {"path": "src/agilab/apps-pages/view_forecast_analysis"},
            {"path": "src/agilab/apps-pages/view_release_decision"},
        ]

    summary = module.run_tree_checks(
        space_id="demo/agilab",
        timeout=1.0,
        target_seconds=5.0,
        fetch_json_fn=_fetch_json,
        clock=clock.__next__,
    )

    assert summary.success is True
    assert summary.total_duration_seconds == 0.6
    assert [check.label for check in summary.checks] == [
        "public app tree",
        "public pages tree",
        "core pages tree",
    ]


def test_main_json_returns_failure_for_private_app(monkeypatch, capsys) -> None:
    module = _load_module()

    def _run_smoke(**_kwargs):
        return module.SmokeSummary(
            success=False,
            total_duration_seconds=1.0,
            target_seconds=30.0,
            within_target=False,
            checks=[
                module.CheckResult(
                    label="public app tree",
                    success=False,
                    duration_seconds=1.0,
                    detail="non-public app entries: private_project",
                    url="https://huggingface.co/api/spaces/demo/agilab/tree/main/src/agilab/apps",
                )
            ],
        )

    monkeypatch.setattr(module, "run_smoke", _run_smoke)

    exit_code = module.main(["--json"])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is False
    assert payload["checks"][0]["detail"] == "non-public app entries: private_project"


def test_main_tree_only_returns_failure_for_stale_core_page(monkeypatch, capsys) -> None:
    module = _load_module()

    def _run_tree_checks(**_kwargs):
        return module.SmokeSummary(
            success=False,
            total_duration_seconds=1.0,
            target_seconds=30.0,
            within_target=False,
            checks=[
                module.CheckResult(
                    label="core pages tree",
                    success=False,
                    duration_seconds=1.0,
                    detail="unexpected core page entries: 1_legacy PROJECT.py",
                    url="https://huggingface.co/api/spaces/demo/agilab/tree/main/src/agilab/pages",
                )
            ],
        )

    monkeypatch.setattr(module, "run_tree_checks", _run_tree_checks)

    exit_code = module.main(["--tree-only", "--json"])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is False
    assert payload["checks"][0]["label"] == "core pages tree"
