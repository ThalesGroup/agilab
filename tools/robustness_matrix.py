#!/usr/bin/env python3
"""Run AGILAB P0 robustness scenarios against known bad states."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Callable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "agilab.robustness_matrix.v1"
DEFAULT_PROFILE = "p0"


def _ensure_repo_on_path(repo_root: Path) -> None:
    candidates = (
        repo_root / "src",
        repo_root / "src" / "agilab" / "core" / "agi-env" / "src",
        repo_root / "src" / "agilab" / "core" / "agi-cluster" / "src",
        repo_root / "src" / "agilab" / "core" / "agi-node" / "src",
        repo_root / "src" / "agilab" / "core" / "agi-core" / "src",
        repo_root,
    )
    for candidate in candidates:
        value = str(candidate)
        if value not in sys.path:
            sys.path.insert(0, value)


def _load_tool_module(repo_root: Path, name: str):
    module_path = repo_root / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"agilab_robustness_{name}", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load tool module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class ScenarioObservation:
    passed: bool
    observed: str
    details: dict[str, Any] | None = None
    evidence: Sequence[str] = ()


@dataclass(frozen=True)
class RobustnessScenario:
    id: str
    domain: str
    fault: str
    expected_behavior: str
    remediation: str
    replay_command: str
    runner: Callable[[Path, Path], ScenarioObservation]
    profiles: tuple[str, ...] = (DEFAULT_PROFILE,)


def _replay_command(scenario_id: str) -> str:
    return f"./dev robust --scenario {scenario_id} --compact"


def _check_exception(
    func: Callable[[], Any],
    *,
    expected_type: type[BaseException],
    required_tokens: Sequence[str],
) -> ScenarioObservation:
    try:
        func()
    except expected_type as exc:
        message = str(exc)
        missing = [token for token in required_tokens if token not in message]
        return ScenarioObservation(
            passed=not missing,
            observed=message,
            details={"missing_message_tokens": missing, "exception_type": type(exc).__name__},
        )
    except Exception as exc:  # pragma: no cover - defensive contract reporting.
        return ScenarioObservation(
            passed=False,
            observed=f"Unexpected exception type {type(exc).__name__}: {exc}",
            details={"exception_type": type(exc).__name__},
        )
    return ScenarioObservation(
        passed=False,
        observed=f"Expected {expected_type.__name__}, but the bad state was accepted.",
        details={"exception_type": ""},
    )


def _cluster_share_same_as_local(repo_root: Path, tmp_root: Path) -> ScenarioObservation:
    del repo_root
    from agi_env.share_mount_support import resolve_share_path

    share = tmp_root / "same-share"
    share.mkdir()
    env_path = tmp_root / ".env"
    env_path.write_text("AGI_CLUSTER_SHARE=same-share\nAGI_LOCAL_SHARE=same-share\n", encoding="utf-8")

    return _check_exception(
        lambda: resolve_share_path(
            cluster_share=str(share),
            local_share=str(share),
            cluster_enabled=True,
            env_path=env_path,
            home_path=tmp_root,
        ),
        expected_type=RuntimeError,
        required_tokens=("requires AGI_CLUSTER_SHARE to be distinct", str(env_path)),
    )


def _cluster_share_missing(repo_root: Path, tmp_root: Path) -> ScenarioObservation:
    del repo_root
    from agi_env.share_mount_support import resolve_share_path

    local_share = tmp_root / "localshare"
    local_share.mkdir()
    cluster_share = tmp_root / "missing-clustershare"
    env_path = tmp_root / ".env"
    env_path.write_text(
        f"AGI_CLUSTER_SHARE={cluster_share}\nAGI_LOCAL_SHARE={local_share}\n",
        encoding="utf-8",
    )

    return _check_exception(
        lambda: resolve_share_path(
            cluster_share=str(cluster_share),
            local_share=str(local_share),
            cluster_enabled=True,
            env_path=env_path,
            home_path=tmp_root,
        ),
        expected_type=RuntimeError,
        required_tokens=("requires AGI_CLUSTER_SHARE to be mounted and writable", str(env_path)),
    )


def _public_bind_without_controls(repo_root: Path, tmp_root: Path) -> ScenarioObservation:
    del tmp_root
    _ensure_repo_on_path(repo_root)
    from agilab.ui_public_bind_guard import PublicBindPolicyError, enforce_public_bind_policy

    return _check_exception(
        lambda: enforce_public_bind_policy({"AGILAB_UI_HOST": "0.0.0.0"}),
        expected_type=PublicBindPolicyError,
        required_tokens=("refuses to bind", "auth/TLS", "AGILAB_PUBLIC_BIND_OK"),
    )


def _public_bind_incomplete_controls(repo_root: Path, tmp_root: Path) -> ScenarioObservation:
    del tmp_root
    _ensure_repo_on_path(repo_root)
    from agilab.ui_public_bind_guard import PublicBindPolicyError, enforce_public_bind_policy

    return _check_exception(
        lambda: enforce_public_bind_policy(
            {"AGILAB_UI_HOST": "0.0.0.0", "AGILAB_PUBLIC_BIND_OK": "1"}
        ),
        expected_type=PublicBindPolicyError,
        required_tokens=("refuses to bind", "auth/TLS", "AGILAB_PUBLIC_BIND_OK"),
    )


def _service_health_unhealthy_workers(repo_root: Path, tmp_root: Path) -> ScenarioObservation:
    del tmp_root
    service_health_check = _load_tool_module(repo_root, "service_health_check")
    exit_code, message, details = service_health_check._evaluate_health(
        {"status": "running", "workers_unhealthy_count": 2, "workers_running_count": 4},
        allow_idle=False,
        max_unhealthy=0,
        max_restart_rate=0.25,
    )
    return ScenarioObservation(
        passed=exit_code == 2 and "exceeds limit" in message,
        observed=message,
        details={"exit_code": exit_code, **details},
        evidence=("tools/service_health_check.py",),
    )


def _service_health_idle_without_override(repo_root: Path, tmp_root: Path) -> ScenarioObservation:
    del tmp_root
    service_health_check = _load_tool_module(repo_root, "service_health_check")
    exit_code, message, details = service_health_check._evaluate_health(
        {"status": "idle", "workers_unhealthy_count": 0, "workers_running_count": 1},
        allow_idle=False,
        max_unhealthy=0,
        max_restart_rate=0.25,
    )
    return ScenarioObservation(
        passed=exit_code == 4 and "use --allow-idle" in message,
        observed=message,
        details={"exit_code": exit_code, **details},
        evidence=("tools/service_health_check.py",),
    )


def _missing_run_manifest_fails_verification(repo_root: Path, tmp_root: Path) -> ScenarioObservation:
    _ensure_repo_on_path(repo_root)
    from agilab.evidence_contract import verify_manifest

    manifest_path = tmp_root / "missing-run_manifest.json"
    report = verify_manifest(manifest_path)
    checks = {check["id"]: check for check in report.get("checks", [])}
    manifest_check = checks.get("manifest_exists", {})
    return ScenarioObservation(
        passed=report.get("status") == "fail" and manifest_check.get("status") == "fail",
        observed=str(manifest_check.get("summary", "")),
        details={
            "report_status": report.get("status"),
            "check_status": manifest_check.get("status"),
            "manifest_path": str(manifest_path),
        },
        evidence=("src/agilab/evidence_contract.py",),
    )


def _invalid_run_manifest_fails_verification(repo_root: Path, tmp_root: Path) -> ScenarioObservation:
    _ensure_repo_on_path(repo_root)
    from agilab.evidence_contract import verify_manifest

    manifest_path = tmp_root / "run_manifest.json"
    manifest_path.write_text("{not valid json\n", encoding="utf-8")
    report = verify_manifest(manifest_path)
    checks = {check["id"]: check for check in report.get("checks", [])}
    schema_check = checks.get("manifest_schema_supported", {})
    return ScenarioObservation(
        passed=report.get("status") == "fail" and schema_check.get("status") == "fail",
        observed=str(schema_check.get("summary", "")),
        details={
            "report_status": report.get("status"),
            "check_status": schema_check.get("status"),
            "manifest_path": str(manifest_path),
        },
        evidence=("src/agilab/evidence_contract.py",),
    )


def _invalid_notebook_import_fails_preflight(repo_root: Path, tmp_root: Path) -> ScenarioObservation:
    notebook_import_preflight = _load_tool_module(repo_root, "notebook_import_preflight")
    notebook_path = tmp_root / "bad.ipynb"
    notebook_path.write_text(
        json.dumps({"cells": "not-a-list", "metadata": {}, "nbformat": 4, "nbformat_minor": 5}),
        encoding="utf-8",
    )
    report = notebook_import_preflight.build_report(notebook_path=notebook_path)
    checks = {check["id"]: check for check in report.get("checks", [])}
    load_check = checks.get("notebook_import_preflight_load", {})
    return ScenarioObservation(
        passed=report.get("status") == "fail" and "cells must be a list" in str(load_check),
        observed=str(load_check.get("summary", "")),
        details={"report_status": report.get("status"), "load_check": load_check},
        evidence=("tools/notebook_import_preflight.py", "src/agilab/notebook_pipeline_import.py"),
    )


def _unsupported_app_settings_schema(repo_root: Path, tmp_root: Path) -> ScenarioObservation:
    del repo_root, tmp_root
    from agi_env.app_settings_support import prepare_app_settings_for_write

    return _check_exception(
        lambda: prepare_app_settings_for_write(
            {"__meta__": {"schema": "agilab.app_settings.v1", "version": 999}}
        ),
        expected_type=ValueError,
        required_tokens=("Unsupported app_settings.toml schema version", "upgrade AGILAB"),
    )


def _conflicting_app_settings_run_payload(repo_root: Path, tmp_root: Path) -> ScenarioObservation:
    del repo_root, tmp_root
    from agi_env.app_settings_support import prepare_app_settings_for_write

    return _check_exception(
        lambda: prepare_app_settings_for_write({"args": {"args": [], "stages": []}}),
        expected_type=ValueError,
        required_tokens=("cannot contain both", "legacy 'args.args'", "current 'args.stages'"),
    )


def _streamlit_route_static_guard(repo_root: Path, tmp_root: Path) -> ScenarioObservation:
    del tmp_root
    scan_roots = (
        repo_root / "src" / "agilab" / "main_page.py",
        repo_root / "src" / "agilab" / "about_page",
        repo_root / "src" / "agilab" / "pages",
    )
    pattern = re.compile(r"switch_page\(\s*Path\(\s*[\"']pages/")
    offenders: list[str] = []
    for root in scan_roots:
        paths = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in paths:
            text = path.read_text(encoding="utf-8", errors="ignore")
            if pattern.search(text):
                offenders.append(str(path.relative_to(repo_root)))
    return ScenarioObservation(
        passed=not offenders,
        observed=(
            "No hard-coded Streamlit pages/<n> routes found."
            if not offenders
            else "Hard-coded Streamlit page routes found."
        ),
        details={"offenders": offenders},
        evidence=tuple(str(path.relative_to(repo_root)) for path in scan_roots),
    )


SCENARIOS: tuple[RobustnessScenario, ...] = (
    RobustnessScenario(
        id="cluster_share_same_as_local_fails_closed",
        domain="cluster",
        fault="Cluster mode points AGI_CLUSTER_SHARE and AGI_LOCAL_SHARE to the same directory.",
        expected_behavior="Reject the configuration instead of silently falling back to localshare.",
        remediation="Set AGI_CLUSTER_SHARE to an explicit mounted cluster share distinct from AGI_LOCAL_SHARE.",
        replay_command=_replay_command("cluster_share_same_as_local_fails_closed"),
        runner=_cluster_share_same_as_local,
    ),
    RobustnessScenario(
        id="cluster_share_missing_fails_closed",
        domain="cluster",
        fault="Cluster mode is enabled but AGI_CLUSTER_SHARE is missing or not writable.",
        expected_behavior="Reject the run before dispatch so workers cannot diverge on local storage.",
        remediation="Mount the cluster share, run agilab doctor share setup, or disable cluster mode.",
        replay_command=_replay_command("cluster_share_missing_fails_closed"),
        runner=_cluster_share_missing,
    ),
    RobustnessScenario(
        id="public_streamlit_bind_without_controls_refused",
        domain="ui-security",
        fault="Streamlit is configured to bind 0.0.0.0 without explicit auth/TLS controls.",
        expected_behavior="Fail before exposing the UI publicly.",
        remediation="Use 127.0.0.1 or set AGILAB_PUBLIC_BIND_OK=1 plus an auth/TLS indicator.",
        replay_command=_replay_command("public_streamlit_bind_without_controls_refused"),
        runner=_public_bind_without_controls,
    ),
    RobustnessScenario(
        id="public_streamlit_bind_incomplete_controls_refused",
        domain="ui-security",
        fault="Public bind opt-in is set without an auth or TLS indicator.",
        expected_behavior="Fail because both explicit opt-in and protection evidence are required.",
        remediation="Add AGILAB_TLS_TERMINATED=1 or an auth-required indicator, or bind locally.",
        replay_command=_replay_command("public_streamlit_bind_incomplete_controls_refused"),
        runner=_public_bind_incomplete_controls,
    ),
    RobustnessScenario(
        id="service_unhealthy_workers_block_promotion",
        domain="service",
        fault="Service health reports unhealthy workers above the configured threshold.",
        expected_behavior="Return a non-zero health gate code and a concise reason.",
        remediation="Restart or redeploy the unhealthy workers, then rerun service health.",
        replay_command=_replay_command("service_unhealthy_workers_block_promotion"),
        runner=_service_health_unhealthy_workers,
    ),
    RobustnessScenario(
        id="service_idle_requires_explicit_override",
        domain="service",
        fault="Service status is idle while allow_idle is disabled.",
        expected_behavior="Block the health gate unless the operator explicitly accepts idle services.",
        remediation="Use --allow-idle only when idle is valid for this service profile.",
        replay_command=_replay_command("service_idle_requires_explicit_override"),
        runner=_service_health_idle_without_override,
    ),
    RobustnessScenario(
        id="missing_run_manifest_fails_verification",
        domain="evidence",
        fault="The run_manifest.json path is missing.",
        expected_behavior="Verification fails with manifest_exists rather than treating evidence as optional.",
        remediation="Rerun the project or point the verifier to the correct run_manifest.json.",
        replay_command=_replay_command("missing_run_manifest_fails_verification"),
        runner=_missing_run_manifest_fails_verification,
    ),
    RobustnessScenario(
        id="invalid_run_manifest_fails_verification",
        domain="evidence",
        fault="The run_manifest.json file exists but is invalid JSON/schema.",
        expected_behavior="Verification fails at schema loading with a stable evidence report.",
        remediation="Regenerate run evidence from AGILAB instead of editing manifest JSON by hand.",
        replay_command=_replay_command("invalid_run_manifest_fails_verification"),
        runner=_invalid_run_manifest_fails_verification,
    ),
    RobustnessScenario(
        id="invalid_notebook_import_fails_preflight",
        domain="notebook-import",
        fault="Notebook import receives an invalid notebook cell structure.",
        expected_behavior="Preflight fails without executing cells.",
        remediation="Use a valid .ipynb and rerun notebook import preflight before project creation.",
        replay_command=_replay_command("invalid_notebook_import_fails_preflight"),
        runner=_invalid_notebook_import_fails_preflight,
    ),
    RobustnessScenario(
        id="unsupported_app_settings_schema_fails_closed",
        domain="app-settings",
        fault="app_settings.toml declares a future unsupported schema version.",
        expected_behavior="Refuse the file instead of silently rewriting unknown settings.",
        remediation="Upgrade AGILAB before editing settings produced by a newer release.",
        replay_command=_replay_command("unsupported_app_settings_schema_fails_closed"),
        runner=_unsupported_app_settings_schema,
    ),
    RobustnessScenario(
        id="conflicting_app_settings_run_payload_fails_closed",
        domain="app-settings",
        fault="app_settings.toml contains both legacy args.args and current args.stages.",
        expected_behavior="Refuse ambiguous run payloads instead of choosing one silently.",
        remediation="Keep only args.stages in current app settings.",
        replay_command=_replay_command("conflicting_app_settings_run_payload_fails_closed"),
        runner=_conflicting_app_settings_run_payload,
    ),
    RobustnessScenario(
        id="streamlit_routes_do_not_hardcode_pages_directory",
        domain="ui-routing",
        fault="A wizard or page hard-codes Streamlit pages/<n> paths.",
        expected_behavior="Use central page routing so installed packages and source launches agree.",
        remediation="Route via the central page registry or current Streamlit navigation objects.",
        replay_command=_replay_command("streamlit_routes_do_not_hardcode_pages_directory"),
        runner=_streamlit_route_static_guard,
    ),
)


def _scenario_to_result(
    scenario: RobustnessScenario,
    observation: ScenarioObservation,
) -> dict[str, Any]:
    return {
        "id": scenario.id,
        "domain": scenario.domain,
        "status": "pass" if observation.passed else "fail",
        "fault": scenario.fault,
        "expected_behavior": scenario.expected_behavior,
        "observed": observation.observed,
        "remediation": scenario.remediation,
        "replay_command": scenario.replay_command,
        "evidence": list(observation.evidence),
        "details": observation.details or {},
        "cleanup_status": "pending",
    }


def _selected_scenarios(
    *,
    profile: str,
    scenario_ids: Sequence[str] = (),
    scenario_specs: Sequence[RobustnessScenario] | None = None,
) -> list[RobustnessScenario]:
    specs = list(SCENARIOS if scenario_specs is None else scenario_specs)
    known_ids = {scenario.id for scenario in specs}
    unknown = sorted(set(scenario_ids) - known_ids)
    if unknown:
        raise ValueError(f"Unknown robustness scenario(s): {', '.join(unknown)}")
    if scenario_ids:
        wanted = set(scenario_ids)
        return [scenario for scenario in specs if scenario.id in wanted]
    if profile == "all":
        return specs
    return [scenario for scenario in specs if profile in scenario.profiles]


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    profile: str = DEFAULT_PROFILE,
    scenario_ids: Sequence[str] = (),
    scenario_specs: Sequence[RobustnessScenario] | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    _ensure_repo_on_path(repo_root)
    selected = _selected_scenarios(
        profile=profile,
        scenario_ids=scenario_ids,
        scenario_specs=scenario_specs,
    )
    results: list[dict[str, Any]] = []
    cleanup_status = "not_started"
    with tempfile.TemporaryDirectory(prefix="agilab-robustness-") as raw_tmp:
        tmp_root = Path(raw_tmp)
        for scenario in selected:
            scenario_tmp = tmp_root / scenario.id
            scenario_tmp.mkdir(parents=True, exist_ok=True)
            try:
                observation = scenario.runner(repo_root, scenario_tmp)
            except Exception as exc:  # pragma: no cover - defensive report boundary.
                observation = ScenarioObservation(
                    passed=False,
                    observed=f"Scenario raised unexpected {type(exc).__name__}: {exc}",
                    details={"exception_type": type(exc).__name__},
                )
            results.append(_scenario_to_result(scenario, observation))
        cleanup_path = tmp_root
    cleanup_status = "removed" if not cleanup_path.exists() else "left_on_disk"
    for result in results:
        result["cleanup_status"] = cleanup_status

    failed = [result for result in results if result["status"] != "pass"]
    domains = sorted({result["domain"] for result in results})
    return {
        "report": "AGILAB robustness matrix",
        "schema": SCHEMA,
        "status": "pass" if not failed and results else "fail",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "summary": {
            "scenario_count": len(results),
            "passed": len(results) - len(failed),
            "failed": len(failed),
            "domains": domains,
            "cleanup_status": cleanup_status,
        },
        "scenarios": results,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run synthetic P0 robustness scenarios. A scenario passes when the "
            "known bad state is rejected with a clear recovery contract."
        )
    )
    parser.add_argument(
        "--profile",
        choices=(DEFAULT_PROFILE, "all"),
        default=DEFAULT_PROFILE,
        help="Scenario profile to run.",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        default=[],
        help="Run one scenario id. Can be repeated.",
    )
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path.")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON.")
    parser.add_argument("--json", action="store_true", help="Alias for --compact.")
    parser.add_argument("--list-scenarios", action="store_true", help="List scenario ids and exit.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    if args.list_scenarios:
        for scenario in SCENARIOS:
            print(f"{scenario.id}\t{scenario.domain}")
        return 0
    try:
        report = build_report(profile=args.profile, scenario_ids=args.scenario)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.compact or args.json:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
