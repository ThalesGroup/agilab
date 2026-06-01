from __future__ import annotations

import importlib.util
import json
import runpy
import sys
import urllib.request
from pathlib import Path

import pytest


MODULE_PATH = Path("tools/hf_space_smoke.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("hf_space_smoke_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _clock(*values: float):
    return iter(values).__next__


def test_profile_helpers_reject_unknown_profiles() -> None:
    module = _load_module()

    with pytest.raises(ValueError, match="unknown HF Space profile"):
        module.profile_builtin_app_entries("missing")
    with pytest.raises(ValueError, match="unknown HF Space profile"):
        module.profile_page_entries("missing")


def test_advanced_profile_accepts_full_public_payload() -> None:
    module = _load_module()

    missing, unexpected = module.builtin_app_entry_mismatch(
        [{"path": f"src/agilab/apps/builtin/{name}"} for name in module.profile_builtin_app_entries("advanced")],
        profile="advanced",
    )
    page_offenders = module.unexpected_page_entries(
        [{"path": f"src/agilab/apps-pages/{name}"} for name in module.profile_page_entries("advanced")],
        profile="advanced",
    )

    assert missing == []
    assert unexpected == []
    assert page_offenders == []


def test_build_space_url_encodes_current_page_query() -> None:
    module = _load_module()
    spec = module.route_specs()[3]

    url = module.build_space_url("https://demo.hf.space/", spec)

    assert url.startswith("https://demo.hf.space?")
    assert "active_app=flight_telemetry_project" in url
    assert "current_page=%2Fapp%2Fsrc%2Fagilab%2Fapps-pages%2Fview_maps%2Fsrc%2Fview_maps%2Fview_maps.py" in url


def test_build_space_url_encodes_weather_view_query() -> None:
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


def test_builtin_app_profile_requires_current_first_proof_apps() -> None:
    module = _load_module()

    missing, unexpected = module.builtin_app_entry_mismatch(
        [
            {"path": "src/agilab/apps/builtin/flight_telemetry_project"},
            {"path": "src/agilab/apps/builtin/pytorch_playground_project"},
            {"path": "src/agilab/apps/builtin/tescia_diagnostic_project"},
        ]
    )

    assert missing == ["weather_forecast_project"]
    assert unexpected == ["tescia_diagnostic_project"]


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

    assert offenders == ["view_maps_network", "view_scenario_cockpit"]


def test_unexpected_core_page_entries_flags_stale_renamed_pages() -> None:
    module = _load_module()

    offenders = module.unexpected_core_page_entries(
        [
            {"path": "src/agilab/pages/0_SETTINGS.py"},
            {"path": "src/agilab/pages/1_PROJECT.py"},
            {"path": "src/agilab/pages/1_PROJECT_STATUS.py"},
            {"path": "src/agilab/pages/2_ORCHESTRATE.py"},
            {"path": "src/agilab/pages/3_WORKFLOW.py"},
            {"path": "src/agilab/pages/4_ANALYSIS.py"},
            {"path": "src/agilab/pages/1_\u25b6\ufe0f PROJECT.py"},
            {"path": "src/agilab/pages/3_PIPELINE.py"},
            {"path": "src/agilab/pages/1_PROJECT.py/child"},
        ]
    )

    assert offenders == ["1_\u25b6\ufe0f PROJECT.py", "3_PIPELINE.py"]


def test_build_tree_api_url_quotes_space_and_tree_path() -> None:
    module = _load_module()

    url = module.build_tree_api_url("demo org/agilab space", "src/agilab/apps-pages/view maps")

    assert url == (
        "https://huggingface.co/api/spaces/demo%20org/agilab%20space/tree/main/"
        "src/agilab/apps-pages/view%20maps"
    )


def test_fetch_text_uses_hf_token_and_decodes_response(monkeypatch) -> None:
    module = _load_module()
    captured = {}

    class _Response:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *_exc_info):
            return None

        def getcode(self):
            return 200

        def read(self):
            return b"ready"

    def _urlopen(request, *, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setenv("HF_TOKEN", "secret-token")
    monkeypatch.setattr(module.urllib.request, "urlopen", _urlopen)

    status, body = module.fetch_text("https://demo.hf.space", 3.5)

    assert status == 202
    assert body == "ready"
    assert captured == {
        "url": "https://demo.hf.space",
        "headers": {
            "Authorization": "Bearer secret-token",
            "User-agent": "agilab-hf-space-smoke/1.0",
        },
        "timeout": 3.5,
    }


def test_fetch_json_rejects_http_error_status(monkeypatch) -> None:
    module = _load_module()

    monkeypatch.setattr(module, "fetch_text", lambda _url, _timeout: (503, "service unavailable"))

    with pytest.raises(module.urllib.error.HTTPError) as exc_info:
        module.fetch_json("https://demo.hf.space/api", 2.0)

    assert exc_info.value.code == 503
    assert exc_info.value.reason == "service unavailable"


def test_fetch_json_decodes_success_payload_without_auth_header(monkeypatch) -> None:
    module = _load_module()
    captured = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_exc_info):
            return None

        def getcode(self):
            return 200

        def read(self):
            return b'{"status": "ok"}'

    def _urlopen(request, *, timeout):
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setattr(module.urllib.request, "urlopen", _urlopen)

    payload = module.fetch_json("https://demo.hf.space/api", 4.0)

    assert payload == {"status": "ok"}
    assert captured["headers"] == {"User-agent": "agilab-hf-space-smoke/1.0"}
    assert captured["timeout"] == 4.0


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


def test_check_route_reports_fetch_exception_and_http_error() -> None:
    module = _load_module()

    def _raise(_url: str, _timeout: float):
        raise TimeoutError("too slow")

    failed_request = module.check_route(
        "https://demo.hf.space/",
        module.RouteSpec("analysis", path="/ANALYSIS"),
        timeout=1.0,
        fetcher=_raise,
        clock=_clock(0.0, 0.4),
    )
    http_error = module.check_route(
        "https://demo.hf.space/",
        module.RouteSpec("health", path="/_stcore/health"),
        timeout=1.0,
        fetcher=lambda _url, _timeout: (500, "boom"),
        clock=_clock(1.0, 1.3),
    )

    assert failed_request.success is False
    assert failed_request.detail == "request failed: too slow"
    assert failed_request.url == "https://demo.hf.space/ANALYSIS"
    assert http_error.success is False
    assert http_error.detail == "HTTP 500"


def test_tree_checks_report_fetch_non_list_and_offender_failures() -> None:
    module = _load_module()

    request_error = module.check_public_app_tree(
        "demo/agilab",
        timeout=1.0,
        fetcher=lambda _url, _timeout: (_ for _ in ()).throw(RuntimeError("api down")),
        clock=_clock(0.0, 0.2),
    )
    non_list = module.check_public_pages_tree(
        "demo/agilab",
        timeout=1.0,
        fetcher=lambda _url, _timeout: {"path": "src/agilab/apps-pages"},
        clock=_clock(1.0, 1.1),
    )
    public_app_non_list = module.check_public_app_tree(
        "demo/agilab",
        timeout=1.0,
        fetcher=lambda _url, _timeout: {"path": "src/agilab/apps"},
        clock=_clock(1.5, 1.6),
    )
    private_app = module.check_public_app_tree(
        "demo/agilab",
        timeout=1.0,
        fetcher=lambda _url, _timeout: [
            {"path": "outside/src/agilab/apps/private_project"},
            {"path": "src/agilab/apps/private_project"},
        ],
        clock=_clock(2.0, 2.1),
    )
    core_exception = module.check_core_pages_tree(
        "demo/agilab",
        timeout=1.0,
        fetcher=lambda _url, _timeout: (_ for _ in ()).throw(RuntimeError("core api down")),
        clock=_clock(2.5, 2.7),
    )
    core_non_list = module.check_core_pages_tree(
        "demo/agilab",
        timeout=1.0,
        fetcher=lambda _url, _timeout: {"path": "src/agilab/pages"},
        clock=_clock(2.8, 2.9),
    )
    stale_page = module.check_core_pages_tree(
        "demo/agilab",
        timeout=1.0,
        fetcher=lambda _url, _timeout: [{"path": "src/agilab/pages/2_legacy.py"}],
        clock=_clock(3.0, 3.1),
    )

    assert request_error.detail == "request failed: api down"
    assert non_list.detail == "tree API returned non-list payload"
    assert public_app_non_list.detail == "tree API returned non-list payload"
    assert private_app.detail == "non-public app entries: private_project"
    assert core_exception.detail == "request failed: core api down"
    assert core_non_list.detail == "tree API returned non-list payload"
    assert stale_page.detail == "unexpected core page entries: 2_legacy.py"


def test_builtin_and_public_pages_tree_report_profile_mismatches() -> None:
    module = _load_module()

    builtin = module.check_builtin_app_tree(
        "demo/agilab",
        timeout=1.0,
        fetcher=lambda _url, _timeout: [
            {"path": "src/agilab/apps/builtin/flight_telemetry_project"},
            {"path": "src/agilab/apps/builtin/pytorch_playground_project"},
            {"path": "src/agilab/apps/builtin/private_project"},
        ],
        clock=_clock(0.0, 0.1),
    )
    pages = module.check_public_pages_tree(
        "demo/agilab",
        timeout=1.0,
        fetcher=lambda _url, _timeout: [
            {"path": "src/agilab/apps-pages/view_maps"},
            {"path": "src/agilab/apps-pages/view_unknown"},
        ],
        clock=_clock(1.0, 1.1),
    )
    builtin_request_error = module.check_builtin_app_tree(
        "demo/agilab",
        timeout=1.0,
        fetcher=lambda _url, _timeout: (_ for _ in ()).throw(RuntimeError("builtin api down")),
        clock=_clock(2.0, 2.2),
    )
    builtin_non_list = module.check_builtin_app_tree(
        "demo/agilab",
        timeout=1.0,
        fetcher=lambda _url, _timeout: {"path": "src/agilab/apps/builtin"},
        clock=_clock(3.0, 3.1),
    )
    missing_only = module.check_builtin_app_tree(
        "demo/agilab",
        timeout=1.0,
        fetcher=lambda _url, _timeout: [
            {"path": "src/agilab/apps/builtin/flight_telemetry_project"},
            {"path": "src/agilab/apps/builtin/pytorch_playground_project"},
        ],
        clock=_clock(4.0, 4.1),
    )
    unexpected_only = module.check_builtin_app_tree(
        "demo/agilab",
        timeout=1.0,
        fetcher=lambda _url, _timeout: [
            {"path": "src/agilab/apps/builtin/flight_telemetry_project"},
            {"path": "src/agilab/apps/builtin/pytorch_playground_project"},
            {"path": "src/agilab/apps/builtin/weather_forecast_project"},
            {"path": "src/agilab/apps/builtin/private_project"},
        ],
        clock=_clock(5.0, 5.1),
    )
    pages_request_error = module.check_public_pages_tree(
        "demo/agilab",
        timeout=1.0,
        fetcher=lambda _url, _timeout: (_ for _ in ()).throw(RuntimeError("pages api down")),
        clock=_clock(6.0, 6.2),
    )

    assert builtin.success is False
    assert builtin.detail == "missing: weather_forecast_project; unexpected: private_project"
    assert pages.success is False
    assert pages.detail == "unexpected page entries: view_unknown"
    assert builtin_request_error.detail == "request failed: builtin api down"
    assert builtin_non_list.detail == "tree API returned non-list payload"
    assert missing_only.detail == "missing: weather_forecast_project"
    assert unexpected_only.detail == "unexpected: private_project"
    assert pages_request_error.detail == "request failed: pages api down"


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
            3.8,
            3.8,
            4.7,
            4.7,
            4.9,
        ]
    )

    def _fetch_text(_url: str, _timeout: float):
        return 200, "ok"

    def _fetch_json(_url: str, _timeout: float):
        if _url.endswith("src/agilab/apps"):
            return [{"path": "src/agilab/apps/builtin"}, {"path": "src/agilab/apps/install.py"}]
        if _url.endswith("src/agilab/apps/builtin"):
            return [
                {"path": "src/agilab/apps/builtin/flight_telemetry_project"},
                {"path": "src/agilab/apps/builtin/pytorch_playground_project"},
                {"path": "src/agilab/apps/builtin/weather_forecast_project"},
            ]
        if _url.endswith("src/agilab/pages"):
            return [
                {"path": "src/agilab/pages/0_SETTINGS.py"},
                {"path": "src/agilab/pages/1_PROJECT.py"},
                {"path": "src/agilab/pages/1_PROJECT_STATUS.py"},
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
    assert summary.total_duration_seconds == 4.9
    assert summary.within_target is True
    assert [check.label for check in summary.checks][-4:] == [
        "public app tree",
        "builtin app profile tree",
        "public pages tree",
        "core pages tree",
    ]


def test_run_smoke_marks_successful_slow_run_outside_target() -> None:
    module = _load_module()
    clock = iter(
        [
            0.0,
            0.3,
            0.3,
            0.6,
            0.6,
            0.9,
            0.9,
            1.2,
            1.2,
            1.5,
            1.5,
            1.8,
            1.8,
            2.1,
            2.1,
            2.4,
            2.4,
            2.7,
            2.7,
            3.0,
            3.0,
            3.3,
        ]
    )

    def _fetch_json(_url: str, _timeout: float):
        if _url.endswith("src/agilab/apps"):
            return [{"path": "src/agilab/apps/builtin"}]
        if _url.endswith("src/agilab/apps/builtin"):
            return [
                {"path": "src/agilab/apps/builtin/flight_telemetry_project"},
                {"path": "src/agilab/apps/builtin/pytorch_playground_project"},
                {"path": "src/agilab/apps/builtin/weather_forecast_project"},
            ]
        if _url.endswith("src/agilab/pages"):
            return [
                {"path": "src/agilab/pages/0_SETTINGS.py"},
                {"path": "src/agilab/pages/1_PROJECT.py"},
                {"path": "src/agilab/pages/1_PROJECT_STATUS.py"},
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
        timeout=1.0,
        target_seconds=1.0,
        fetch_text_fn=lambda _url, _timeout: (200, "ok"),
        fetch_json_fn=_fetch_json,
        clock=clock.__next__,
    )

    assert summary.success is True
    assert summary.total_duration_seconds == pytest.approx(3.3)
    assert summary.within_target is False


def test_run_tree_checks_uses_only_repository_tree_checks() -> None:
    module = _load_module()
    clock = iter([0.0, 0.1, 0.1, 0.3, 0.3, 0.6, 0.6, 1.0])

    def _fetch_json(_url: str, _timeout: float):
        if _url.endswith("src/agilab/apps"):
            return [{"path": "src/agilab/apps/builtin"}, {"path": "src/agilab/apps/install.py"}]
        if _url.endswith("src/agilab/apps/builtin"):
            return [
                {"path": "src/agilab/apps/builtin/flight_telemetry_project"},
                {"path": "src/agilab/apps/builtin/pytorch_playground_project"},
                {"path": "src/agilab/apps/builtin/weather_forecast_project"},
            ]
        if _url.endswith("src/agilab/pages"):
            return [
                {"path": "src/agilab/pages/0_SETTINGS.py"},
                {"path": "src/agilab/pages/1_PROJECT.py"},
                {"path": "src/agilab/pages/1_PROJECT_STATUS.py"},
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
    assert summary.total_duration_seconds == 1.0
    assert [check.label for check in summary.checks] == [
        "public app tree",
        "builtin app profile tree",
        "public pages tree",
        "core pages tree",
    ]


def test_render_human_formats_failed_checks() -> None:
    module = _load_module()
    summary = module.SmokeSummary(
        success=False,
        total_duration_seconds=2.5,
        target_seconds=2.0,
        within_target=False,
        checks=[module.CheckResult("analysis", False, 2.5, "HTTP 500", "https://demo/ANALYSIS")],
    )

    rendered = module.render_human(summary, space_id="demo/agilab", space_url="https://demo.hf.space")

    assert "verdict: FAIL" in rendered
    assert "kpi: total=2.50s target<=2.00s within_target=no" in rendered
    assert "- analysis: FAIL in 2.50s (HTTP 500)" in rendered


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


def test_main_human_success_passes_custom_options(monkeypatch, capsys) -> None:
    module = _load_module()
    captured = {}

    def _run_smoke(**kwargs):
        captured.update(kwargs)
        return module.SmokeSummary(
            success=True,
            total_duration_seconds=0.5,
            target_seconds=2.0,
            within_target=True,
            checks=[module.CheckResult("base app", True, 0.5, "HTTP 200", "https://demo.hf.space")],
        )

    monkeypatch.setattr(module, "run_smoke", _run_smoke)

    exit_code = module.main(
        [
            "--space",
            "demo/agilab",
            "--url",
            "https://demo.hf.space/",
            "--profile",
            "advanced",
            "--timeout",
            "3",
            "--target-seconds",
            "2",
        ]
    )

    assert exit_code == 0
    assert captured == {
        "space_id": "demo/agilab",
        "space_url": "https://demo.hf.space/",
        "profile": "advanced",
        "timeout": 3.0,
        "target_seconds": 2.0,
    }
    assert "verdict: PASS" in capsys.readouterr().out


def test_main_rejects_non_positive_time_options() -> None:
    module = _load_module()

    with pytest.raises(SystemExit):
        module.main(["--timeout", "0"])
    with pytest.raises(SystemExit):
        module.main(["--target-seconds", "-1"])


def test_module_entrypoint_runs_tree_only_json_without_network(monkeypatch, capsys) -> None:
    class _Response:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_exc_info):
            return None

        def getcode(self):
            return 200

        def read(self):
            return json.dumps(self._payload).encode("utf-8")

    def _urlopen(request, *, timeout):
        assert timeout == 1.0
        url = request.full_url
        if url.endswith("src/agilab/apps/builtin"):
            return _Response(
                [
                    {"path": "src/agilab/apps/builtin/flight_telemetry_project"},
                    {"path": "src/agilab/apps/builtin/pytorch_playground_project"},
                    {"path": "src/agilab/apps/builtin/weather_forecast_project"},
                ]
            )
        if url.endswith("src/agilab/apps"):
            return _Response([{"path": "src/agilab/apps/builtin"}])
        if url.endswith("src/agilab/apps-pages"):
            return _Response(
                [
                    {"path": "src/agilab/apps-pages/view_maps"},
                    {"path": "src/agilab/apps-pages/view_forecast_analysis"},
                    {"path": "src/agilab/apps-pages/view_release_decision"},
                ]
            )
        if url.endswith("src/agilab/pages"):
            return _Response(
                [
                    {"path": "src/agilab/pages/0_SETTINGS.py"},
                    {"path": "src/agilab/pages/1_PROJECT.py"},
                    {"path": "src/agilab/pages/1_PROJECT_STATUS.py"},
                    {"path": "src/agilab/pages/2_ORCHESTRATE.py"},
                    {"path": "src/agilab/pages/3_WORKFLOW.py"},
                    {"path": "src/agilab/pages/4_ANALYSIS.py"},
                ]
            )
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    monkeypatch.setattr(
        sys,
        "argv",
        [str(MODULE_PATH), "--tree-only", "--json", "--timeout", "1", "--target-seconds", "10"],
    )

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(MODULE_PATH), run_name="__main__")

    assert exc_info.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
    assert [check["label"] for check in payload["checks"]] == [
        "public app tree",
        "builtin app profile tree",
        "public pages tree",
        "core pages tree",
    ]
