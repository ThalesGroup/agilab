#!/usr/bin/env python3
"""Validate that the AGILAB first launch surface renders useful proof cues."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import platform
import sys
import time
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
ABOUT_PAGE = REPO_ROOT / "src" / "agilab" / "main_page.py"
DEFAULT_ACTIVE_APP = REPO_ROOT / "src" / "agilab" / "apps" / "builtin" / "flight_telemetry_project"
DEFAULT_APPS_PATH = REPO_ROOT / "src" / "agilab" / "apps" / "builtin"
SCHEMA = "agilab.first_launch_robot.v1"
DEFAULT_TARGET_SECONDS = 45.0


def _check_result(
    check_id: str,
    label: str,
    passed: bool,
    summary: str,
    *,
    evidence: Sequence[str] = (),
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "pass" if passed else "fail",
        "summary": summary,
        "evidence": list(evidence),
        "details": details or {},
    }


def _widget_values(widgets: Any, attribute: str) -> list[str]:
    values: list[str] = []
    for widget in list(widgets):
        value = getattr(widget, attribute, "")
        if value is not None:
            values.append(str(value))
    return values


def _contains_any(values: Sequence[str], needles: Sequence[str]) -> bool:
    joined = "\n".join(values)
    return any(needle in joined for needle in needles)


def _docs_menu_items() -> dict[str, str]:
    src_root = REPO_ROOT / "src"
    src_root_str = str(src_root)
    if src_root_str not in sys.path:
        sys.path.insert(0, src_root_str)
    try:
        page_docs_path = src_root / "agilab" / "page_docs.py"
        spec = importlib.util.spec_from_file_location(
            "agilab_first_launch_page_docs",
            page_docs_path,
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load page docs module: {page_docs_path}")
        page_docs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(page_docs)
        return page_docs.get_docs_menu_items(html_file="agilab-help.html")
    except Exception as exc:
        return {"_error": str(exc)}


def build_report(
    *,
    about_page: Path = ABOUT_PAGE,
    active_app: Path = DEFAULT_ACTIVE_APP,
    apps_path: Path = DEFAULT_APPS_PATH,
    timeout: float = DEFAULT_TARGET_SECONDS,
    target_seconds: float = DEFAULT_TARGET_SECONDS,
) -> dict[str, Any]:
    from streamlit.testing.v1 import AppTest

    start = time.perf_counter()
    previous_argv = list(sys.argv)
    sys.argv = [
        about_page.name,
        "--active-app",
        str(active_app),
        "--apps-path",
        str(apps_path),
    ]
    try:
        app = AppTest.from_file(str(about_page), default_timeout=timeout)
        app.run(timeout=timeout)
    finally:
        sys.argv = previous_argv

    duration = time.perf_counter() - start
    exceptions = [str(item) for item in list(app.exception)]
    markdown = _widget_values(app.markdown, "value")
    captions = _widget_values(app.caption, "value")
    buttons = _widget_values(app.button, "label")
    docs_menu = _docs_menu_items()

    has_env = False
    try:
        has_env = "env" in app.session_state
    except Exception:
        has_env = False

    checks = [
        _check_result(
            "first_launch_no_exceptions",
            "First launch renders without exceptions",
            not exceptions,
            "Main page rendered without Streamlit AppTest exceptions"
            if not exceptions
            else "Main page raised Streamlit AppTest exceptions",
            evidence=[str(about_page.relative_to(REPO_ROOT))],
            details={"exceptions": exceptions},
        ),
        _check_result(
            "first_launch_env_initialized",
            "First launch initializes AgiEnv",
            has_env,
            "AgiEnv is present in Streamlit session state"
            if has_env
            else "AgiEnv is missing from Streamlit session state",
            evidence=[str(about_page.relative_to(REPO_ROOT))],
        ),
        _check_result(
            "first_launch_brand_signal",
            "First launch exposes product signal",
            _contains_any(markdown, ["AGILAB logo", "Reproducible AI workflows"]),
            "Landing page exposes the AGILAB brand and workflow proposition",
            evidence=[str(about_page.relative_to(REPO_ROOT))],
        ),
        _check_result(
            "first_launch_first_proof_signal",
            "First launch exposes first-proof action",
            _contains_any(
                [*markdown, *captions, *buttons],
                [
                    "First proof: verify AGILAB end-to-end",
                    "First run: use the built-in flight-telemetry project",
                    "First proof",
                    "Wizard pipeline",
                    "1. Select demo",
                    "1. ORCHESTRATE",
                    "2. ANALYSIS",
                    "1. Open run page",
                    "1. Open PROJECT",
                ],
            ),
            "Landing page tells newcomers where to start",
            evidence=[str(about_page.relative_to(REPO_ROOT))],
        ),
        _check_result(
            "first_launch_workflow_signal",
            "First launch exposes workflow path",
            _contains_any(
                [*markdown, *captions],
                ["DEMO / ORCHESTRATE / ANALYSIS", "PROJECT / ORCHESTRATE / ANALYSIS"],
            )
            or (
                _contains_any(buttons, ["1. ORCHESTRATE", "1. Open run page", "2. Open run page"])
                and _contains_any(buttons, ["2. ANALYSIS", "2. Run first proof", "3. Run first proof"])
            )
            or all(
                _contains_any([*markdown, *captions, *buttons], [token])
                for token in ("DEMO", "ORCHESTRATE", "ANALYSIS")
            )
            or all(
                _contains_any([*markdown, *captions, *buttons], [token])
                for token in ("Project", "Run", "Analyse")
            ),
            "Landing page shows the product journey from project to results",
            evidence=[str(about_page.relative_to(REPO_ROOT))],
        ),
        _check_result(
            "first_launch_docs_action",
            "First launch exposes documentation menu",
            docs_menu.get("Get help", "").startswith("https://thalesgroup.github.io/agilab/"),
            "Landing page exposes documentation through the Streamlit page menu",
            evidence=[str(about_page.relative_to(REPO_ROOT))],
            details={"buttons": buttons, "menu_items": docs_menu},
        ),
        _check_result(
            "first_launch_runtime_budget",
            "First launch stays within runtime budget",
            duration <= target_seconds,
            (
                f"first launch rendered in {duration:.2f}s within "
                f"{target_seconds:.2f}s"
            )
            if duration <= target_seconds
            else (
                f"first launch rendered in {duration:.2f}s, above "
                f"{target_seconds:.2f}s"
            ),
            details={
                "duration_seconds": duration,
                "target_seconds": target_seconds,
            },
        ),
    ]
    failed = [check for check in checks if check["status"] != "pass"]
    return {
        "report": "AGILAB first-launch robot report",
        "schema": SCHEMA,
        "status": "pass" if not failed else "fail",
        "success": not failed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "python": platform.python_version(),
        },
        "active_app": str(active_app),
        "apps_path": str(apps_path),
        "about_page": str(about_page),
        "total_duration_seconds": duration,
        "target_seconds": target_seconds,
        "within_target": duration <= target_seconds,
        "summary": {
            "check_count": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
            "markdown_count": len(markdown),
            "caption_count": len(captions),
            "button_count": len(buttons),
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a lightweight Streamlit AppTest robot against AGILAB first launch."
    )
    parser.add_argument("--about-page", type=Path, default=ABOUT_PAGE)
    parser.add_argument("--active-app", type=Path, default=DEFAULT_ACTIVE_APP)
    parser.add_argument("--apps-path", type=Path, default=DEFAULT_APPS_PATH)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TARGET_SECONDS)
    parser.add_argument("--target-seconds", type=float, default=DEFAULT_TARGET_SECONDS)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.timeout <= 0:
        parser.error("--timeout must be greater than 0")
    if args.target_seconds <= 0:
        parser.error("--target-seconds must be greater than 0")

    report = build_report(
        about_page=args.about_page,
        active_app=args.active_app,
        apps_path=args.apps_path,
        timeout=args.timeout,
        target_seconds=args.target_seconds,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            "AGILAB first-launch robot: "
            + ("PASS" if report["status"] == "pass" else "FAIL")
        )
        for check in report["checks"]:
            print(f"- {check['label']}: {check['status']} ({check['summary']})")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
