#!/usr/bin/env python3
"""Smoke-check the AGILAB Hugging Face Space runtime."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Callable, Sequence


DEFAULT_SPACE_ID = "jpmorard/agilab"
DEFAULT_SPACE_URL = "https://jpmorard-agilab.hf.space"
DEFAULT_TARGET_SECONDS = 30.0
APP_TREE_PATH = "src/agilab/apps"
BUILTIN_APP_TREE_PATH = "src/agilab/apps/builtin"
PAGES_TREE_PATH = "src/agilab/apps-pages"
CORE_PAGES_TREE_PATH = "src/agilab/pages"
ALLOWED_APP_ENTRIES = {
    ".DS_Store",
    ".gitignore",
    "README.md",
    "__init__.py",
    "__pycache__",
    "builtin",
    "install.py",
    "src",
    "templates",
}
EXPECTED_BUILTIN_APP_ENTRIES = {
    "flight_project",
    "meteo_forecast_project",
}
ALLOWED_PAGE_ENTRIES = {
    ".DS_Store",
    ".gitignore",
    "README.md",
    "__init__.py",
    "__pycache__",
    "view_forecast_analysis",
    "view_maps",
    "view_release_decision",
    "view_scenario_cockpit",
}
ALLOWED_CORE_PAGE_ENTRIES = {
    ".DS_Store",
    "__pycache__",
    "0_SETTINGS.py",
    "1_PROJECT.py",
    "2_ORCHESTRATE.py",
    "3_WORKFLOW.py",
    "4_ANALYSIS.py",
}
BAD_BODY_PATTERNS = (
    "127.0.0.1",
    "refused to connect",
    "streamlitapiexception",
    "multiple pages specified",
    "this site can't be reached",
    "this site cannot be reached",
)


@dataclass(frozen=True)
class RouteSpec:
    label: str
    path: str = ""
    query: dict[str, str] | None = None


@dataclass(frozen=True)
class CheckResult:
    label: str
    success: bool
    duration_seconds: float
    detail: str
    url: str | None = None


@dataclass(frozen=True)
class SmokeSummary:
    success: bool
    total_duration_seconds: float
    target_seconds: float
    within_target: bool
    checks: list[CheckResult]


TextFetcher = Callable[[str, float], tuple[int, str]]
JsonFetcher = Callable[[str, float], Any]
Clock = Callable[[], float]


def route_specs() -> list[RouteSpec]:
    return [
        RouteSpec("streamlit health", path="/_stcore/health"),
        RouteSpec("base app"),
        RouteSpec("flight project", query={"active_app": "flight_project"}),
        RouteSpec(
            "flight view_maps",
            query={
                "active_app": "flight_project",
                "current_page": "/app/src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py",
            },
        ),
        RouteSpec("meteo forecast project", query={"active_app": "meteo_forecast_project"}),
        RouteSpec(
            "meteo forecast view",
            query={
                "active_app": "meteo_forecast_project",
                "current_page": "/app/src/agilab/apps-pages/view_forecast_analysis/src/view_forecast_analysis/view_forecast_analysis.py",
            },
        ),
    ]


def build_space_url(base_url: str, spec: RouteSpec) -> str:
    url = base_url.rstrip("/") + spec.path
    if spec.query:
        url += "?" + urllib.parse.urlencode(spec.query)
    return url


def build_tree_api_url(space_id: str, tree_path: str = APP_TREE_PATH) -> str:
    quoted_space = "/".join(urllib.parse.quote(part, safe="") for part in space_id.split("/"))
    quoted_path = urllib.parse.quote(tree_path, safe="/")
    return f"https://huggingface.co/api/spaces/{quoted_space}/tree/main/{quoted_path}"


def fetch_text(url: str, timeout: float) -> tuple[int, str]:
    headers = {"User-Agent": "agilab-hf-space-smoke/1.0"}
    token = os.environ.get("HF_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        status = int(getattr(response, "status", response.getcode()))
        body = response.read().decode("utf-8", errors="replace")
    return status, body


def fetch_json(url: str, timeout: float) -> Any:
    status, body = fetch_text(url, timeout)
    if status >= 400:
        raise urllib.error.HTTPError(url, status, body, None, None)
    return json.loads(body)


def body_has_connection_failure(body: str) -> str | None:
    normalized = body.lower()
    for pattern in BAD_BODY_PATTERNS:
        if pattern in normalized:
            return pattern
    return None


def check_route(
    base_url: str,
    spec: RouteSpec,
    *,
    timeout: float,
    fetcher: TextFetcher = fetch_text,
    clock: Clock = time.perf_counter,
) -> CheckResult:
    url = build_space_url(base_url, spec)
    start = clock()
    try:
        status, body = fetcher(url, timeout)
    except Exception as exc:
        return CheckResult(spec.label, False, clock() - start, f"request failed: {exc}", url)

    duration = clock() - start
    if status >= 400:
        return CheckResult(spec.label, False, duration, f"HTTP {status}", url)
    bad_pattern = body_has_connection_failure(body)
    if bad_pattern:
        return CheckResult(spec.label, False, duration, f"body contains {bad_pattern!r}", url)
    return CheckResult(spec.label, True, duration, f"HTTP {status}", url)


def _direct_tree_entry_name(path_value: str, tree_path: str) -> str | None:
    prefix = tree_path + "/"
    if not path_value.startswith(prefix):
        return None
    relative = path_value[len(prefix) :]
    if not relative or "/" in relative:
        return None
    return relative


def _unexpected_direct_entries(
    entries: Sequence[dict[str, Any]],
    *,
    tree_path: str,
    allowed_entries: set[str],
) -> list[str]:
    offenders: list[str] = []
    for entry in entries:
        name = _direct_tree_entry_name(str(entry.get("path", "")), tree_path)
        if name and name not in allowed_entries:
            offenders.append(name)
    return sorted(set(offenders))


def private_app_entries(entries: Sequence[dict[str, Any]]) -> list[str]:
    return _unexpected_direct_entries(
        entries,
        tree_path=APP_TREE_PATH,
        allowed_entries=ALLOWED_APP_ENTRIES,
    )


def builtin_app_entry_mismatch(entries: Sequence[dict[str, Any]]) -> tuple[list[str], list[str]]:
    names = {
        name
        for entry in entries
        if (name := _direct_tree_entry_name(str(entry.get("path", "")), BUILTIN_APP_TREE_PATH))
    }
    missing = sorted(EXPECTED_BUILTIN_APP_ENTRIES - names)
    unexpected = sorted(names - EXPECTED_BUILTIN_APP_ENTRIES)
    return missing, unexpected


def unexpected_page_entries(entries: Sequence[dict[str, Any]]) -> list[str]:
    return _unexpected_direct_entries(
        entries,
        tree_path=PAGES_TREE_PATH,
        allowed_entries=ALLOWED_PAGE_ENTRIES,
    )


def unexpected_core_page_entries(entries: Sequence[dict[str, Any]]) -> list[str]:
    return _unexpected_direct_entries(
        entries,
        tree_path=CORE_PAGES_TREE_PATH,
        allowed_entries=ALLOWED_CORE_PAGE_ENTRIES,
    )


def check_public_app_tree(
    space_id: str,
    *,
    timeout: float,
    fetcher: JsonFetcher = fetch_json,
    clock: Clock = time.perf_counter,
) -> CheckResult:
    url = build_tree_api_url(space_id)
    start = clock()
    try:
        payload = fetcher(url, timeout)
    except Exception as exc:
        return CheckResult("public app tree", False, clock() - start, f"request failed: {exc}", url)

    duration = clock() - start
    if not isinstance(payload, list):
        return CheckResult("public app tree", False, duration, "tree API returned non-list payload", url)
    offenders = private_app_entries(payload)
    if offenders:
        return CheckResult(
            "public app tree",
            False,
            duration,
            "non-public app entries: " + ", ".join(offenders),
            url,
        )
    return CheckResult("public app tree", True, duration, "no non-public app entries", url)


def check_builtin_app_tree(
    space_id: str,
    *,
    timeout: float,
    fetcher: JsonFetcher = fetch_json,
    clock: Clock = time.perf_counter,
) -> CheckResult:
    url = build_tree_api_url(space_id, BUILTIN_APP_TREE_PATH)
    start = clock()
    try:
        payload = fetcher(url, timeout)
    except Exception as exc:
        return CheckResult("builtin app profile tree", False, clock() - start, f"request failed: {exc}", url)

    duration = clock() - start
    if not isinstance(payload, list):
        return CheckResult("builtin app profile tree", False, duration, "tree API returned non-list payload", url)
    missing, unexpected = builtin_app_entry_mismatch(payload)
    if missing or unexpected:
        details: list[str] = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unexpected:
            details.append("unexpected: " + ", ".join(unexpected))
        return CheckResult("builtin app profile tree", False, duration, "; ".join(details), url)
    return CheckResult("builtin app profile tree", True, duration, "only expected first-proof built-in apps", url)


def check_public_pages_tree(
    space_id: str,
    *,
    timeout: float,
    fetcher: JsonFetcher = fetch_json,
    clock: Clock = time.perf_counter,
) -> CheckResult:
    url = build_tree_api_url(space_id, PAGES_TREE_PATH)
    start = clock()
    try:
        payload = fetcher(url, timeout)
    except Exception as exc:
        return CheckResult("public pages tree", False, clock() - start, f"request failed: {exc}", url)

    duration = clock() - start
    if not isinstance(payload, list):
        return CheckResult("public pages tree", False, duration, "tree API returned non-list payload", url)
    offenders = unexpected_page_entries(payload)
    if offenders:
        return CheckResult(
            "public pages tree",
            False,
            duration,
            "unexpected page entries: " + ", ".join(offenders),
            url,
        )
    return CheckResult("public pages tree", True, duration, "only expected public pages", url)


def check_core_pages_tree(
    space_id: str,
    *,
    timeout: float,
    fetcher: JsonFetcher = fetch_json,
    clock: Clock = time.perf_counter,
) -> CheckResult:
    url = build_tree_api_url(space_id, CORE_PAGES_TREE_PATH)
    start = clock()
    try:
        payload = fetcher(url, timeout)
    except Exception as exc:
        return CheckResult("core pages tree", False, clock() - start, f"request failed: {exc}", url)

    duration = clock() - start
    if not isinstance(payload, list):
        return CheckResult("core pages tree", False, duration, "tree API returned non-list payload", url)
    offenders = unexpected_core_page_entries(payload)
    if offenders:
        return CheckResult(
            "core pages tree",
            False,
            duration,
            "unexpected core page entries: " + ", ".join(offenders),
            url,
        )
    return CheckResult("core pages tree", True, duration, "only expected core pages", url)


def run_smoke(
    *,
    space_id: str = DEFAULT_SPACE_ID,
    space_url: str = DEFAULT_SPACE_URL,
    timeout: float = 20.0,
    target_seconds: float = DEFAULT_TARGET_SECONDS,
    fetch_text_fn: TextFetcher = fetch_text,
    fetch_json_fn: JsonFetcher = fetch_json,
    clock: Clock = time.perf_counter,
) -> SmokeSummary:
    checks = [
        check_route(space_url, spec, timeout=timeout, fetcher=fetch_text_fn, clock=clock)
        for spec in route_specs()
    ]
    checks.append(check_public_app_tree(space_id, timeout=timeout, fetcher=fetch_json_fn, clock=clock))
    checks.append(check_builtin_app_tree(space_id, timeout=timeout, fetcher=fetch_json_fn, clock=clock))
    checks.append(check_public_pages_tree(space_id, timeout=timeout, fetcher=fetch_json_fn, clock=clock))
    checks.append(check_core_pages_tree(space_id, timeout=timeout, fetcher=fetch_json_fn, clock=clock))
    total = sum(check.duration_seconds for check in checks)
    success = all(check.success for check in checks)
    return SmokeSummary(
        success=success,
        total_duration_seconds=total,
        target_seconds=target_seconds,
        within_target=success and total <= target_seconds,
        checks=checks,
    )


def run_tree_checks(
    *,
    space_id: str = DEFAULT_SPACE_ID,
    timeout: float = 20.0,
    target_seconds: float = DEFAULT_TARGET_SECONDS,
    fetch_json_fn: JsonFetcher = fetch_json,
    clock: Clock = time.perf_counter,
) -> SmokeSummary:
    checks = [
        check_public_app_tree(space_id, timeout=timeout, fetcher=fetch_json_fn, clock=clock),
        check_builtin_app_tree(space_id, timeout=timeout, fetcher=fetch_json_fn, clock=clock),
        check_public_pages_tree(space_id, timeout=timeout, fetcher=fetch_json_fn, clock=clock),
        check_core_pages_tree(space_id, timeout=timeout, fetcher=fetch_json_fn, clock=clock),
    ]
    total = sum(check.duration_seconds for check in checks)
    success = all(check.success for check in checks)
    return SmokeSummary(
        success=success,
        total_duration_seconds=total,
        target_seconds=target_seconds,
        within_target=success and total <= target_seconds,
        checks=checks,
    )


def render_human(summary: SmokeSummary, *, space_id: str, space_url: str) -> str:
    lines = [
        "AGILAB Hugging Face Space smoke",
        f"space: {space_id}",
        f"url: {space_url}",
        f"verdict: {'PASS' if summary.success else 'FAIL'}",
        (
            "kpi: "
            f"total={summary.total_duration_seconds:.2f}s "
            f"target<={summary.target_seconds:.2f}s "
            f"within_target={'yes' if summary.within_target else 'no'}"
        ),
    ]
    for check in summary.checks:
        status = "OK" if check.success else "FAIL"
        lines.append(f"- {check.label}: {status} in {check.duration_seconds:.2f}s ({check.detail})")
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke-check the public AGILAB Hugging Face Space.")
    parser.add_argument("--space", default=DEFAULT_SPACE_ID, help=f"Space ID (default: {DEFAULT_SPACE_ID}).")
    parser.add_argument("--url", default=DEFAULT_SPACE_URL, help=f"Space URL (default: {DEFAULT_SPACE_URL}).")
    parser.add_argument("--timeout", type=float, default=20.0, help="Per-request timeout in seconds.")
    parser.add_argument(
        "--target-seconds",
        type=float,
        default=DEFAULT_TARGET_SECONDS,
        help=f"KPI target for the whole smoke in seconds (default: {DEFAULT_TARGET_SECONDS}).",
    )
    parser.add_argument(
        "--tree-only",
        action="store_true",
        help="Check only the HF repository tree contract; use this immediately after upload.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.timeout <= 0:
        parser.error("--timeout must be greater than 0")
    if args.target_seconds <= 0:
        parser.error("--target-seconds must be greater than 0")

    if args.tree_only:
        summary = run_tree_checks(
            space_id=args.space,
            timeout=args.timeout,
            target_seconds=args.target_seconds,
        )
    else:
        summary = run_smoke(
            space_id=args.space,
            space_url=args.url,
            timeout=args.timeout,
            target_seconds=args.target_seconds,
        )
    if args.json:
        print(json.dumps(asdict(summary), indent=2))
    else:
        print(render_human(summary, space_id=args.space, space_url=args.url))
    return 0 if summary.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
