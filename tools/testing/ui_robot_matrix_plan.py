#!/usr/bin/env python3
"""Build a bounded, deterministic UI robot job matrix from the built-in app inventory."""

from __future__ import annotations

import argparse
import json
import os
import tomllib
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_APPS_ROOT = REPO_ROOT / "src" / "agilab" / "apps" / "builtin"
SCHEMA = "agilab.ui_robot_matrix_plan.v1"
MAX_ESTIMATED_PAGES_PER_SHARD = 32

CORE_SCENARIOS = (
    "isolated-core-pages",
    "isolated-project-page",
    "isolated-project-editor-page",
    "isolated-project-notebook-import",
    "isolated-project-import-sidebar",
    "isolated-project-rename-sidebar",
    "isolated-settings-page",
    "isolated-all-builtins-orchestrate-smoke",
    "isolated-all-builtins-core-render-smoke",
)
APP_PAGE_SCENARIOS = ("isolated-entry-and-app-pages",)
STATE_MOBILE_SCENARIOS = (
    "isolated-fresh-session-core-pages",
    "isolated-browser-history",
    "isolated-mobile-core-pages",
)
QUALITY_SCENARIOS = (
    "isolated-browser-error-core-pages",
    "isolated-release-evidence",
    "isolated-above-fold-core-pages",
    "isolated-keyboard-focus-core-pages",
    "isolated-accessibility-core-pages",
)
LAYOUT_SCENARIOS = (
    "isolated-layout-integrity-desktop",
    "isolated-layout-integrity-mobile",
)
FOCUSED_SCENARIOS = (
    (
        "isolated-execution-pandas-orchestrate-pool-executor",
        "execution_pandas_project",
    ),
    ("isolated-pytorch-playground-analysis", "pytorch_playground_project"),
)

# The broad scenario groups render this many pages per selected app. Configured
# apps-pages use a dedicated shard so apps without such pages are never selected
# for a zero-page scenario that cannot satisfy exact coverage.
CORE_PAGES_PER_APP = 12
STATE_MOBILE_PAGES_PER_APP = 9
QUALITY_PAGES_PER_APP = 32
LAYOUT_PAGES_PER_APP = 14


def discover_builtin_apps(apps_root: Path = DEFAULT_APPS_ROOT) -> tuple[str, ...]:
    apps = tuple(sorted(path.name for path in apps_root.glob("*_project") if path.is_dir()))
    if not apps:
        raise ValueError(f"no built-in apps found under {apps_root}")
    return apps


def _normalized_requested_app(raw: str, available: set[str]) -> str:
    value = raw.strip()
    if value in available:
        return value
    project_name = f"{value}_project" if value and not value.endswith("_project") else value
    if project_name in available:
        return project_name
    raise ValueError(f"unknown built-in app requested: {raw!r}")


def resolve_requested_apps(
    requested: str,
    *,
    available_apps: Sequence[str],
) -> tuple[str, ...]:
    available = tuple(dict.fromkeys(str(app).strip() for app in available_apps if str(app).strip()))
    available_set = set(available)
    if not available:
        raise ValueError("available app inventory is empty")
    if not requested.strip() or requested.strip().casefold() == "all":
        return tuple(sorted(available))

    selected = {
        _normalized_requested_app(item, available_set)
        for item in requested.split(",")
        if item.strip()
    }
    if not selected:
        raise ValueError("requested app selection is empty")
    return tuple(app for app in sorted(available) if app in selected)


def configured_apps_page_count(app_dir: Path) -> int:
    settings_path = app_dir / "src" / "app_settings.toml"
    try:
        settings = tomllib.loads(settings_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return 0
    pages = settings.get("pages")
    if not isinstance(pages, Mapping):
        return 0

    names: list[str] = []
    default_view = pages.get("default_view")
    if isinstance(default_view, str) and default_view.strip():
        names.append(default_view.strip())
    view_module = pages.get("view_module")
    if isinstance(view_module, list):
        names.extend(
            item.strip()
            for item in view_module
            if isinstance(item, str) and item.strip()
        )
    return len(dict.fromkeys(names))


def _partition_apps(
    apps: Sequence[str],
    *,
    page_loads: Mapping[str, int],
    max_pages: int,
) -> tuple[tuple[str, ...], ...]:
    groups: list[tuple[str, ...]] = []
    current: list[str] = []
    current_pages = 0
    for app in apps:
        app_pages = int(page_loads[app])
        if app_pages <= 0 or app_pages > max_pages:
            raise ValueError(
                f"app {app!r} has invalid estimated load {app_pages}; "
                f"maximum is {max_pages} pages"
            )
        if current and current_pages + app_pages > max_pages:
            groups.append(tuple(current))
            current = []
            current_pages = 0
        current.append(app)
        current_pages += app_pages
    if current:
        groups.append(tuple(current))
    return tuple(groups)


def _broad_shards(
    *,
    prefix: str,
    apps: Sequence[str],
    scenarios: Sequence[str],
    page_loads: Mapping[str, int],
    max_pages: int,
) -> list[dict[str, object]]:
    shards: list[dict[str, object]] = []
    for index, group in enumerate(
        _partition_apps(apps, page_loads=page_loads, max_pages=max_pages),
        start=1,
    ):
        shards.append(
            {
                "shard": f"{prefix}-{index:02d}",
                "scenarios": " ".join(scenarios),
                "apps": ",".join(group),
                "estimated_pages": sum(int(page_loads[app]) for app in group),
            }
        )
    return shards


def build_plan(
    *,
    requested_apps: str = "all",
    apps_root: Path = DEFAULT_APPS_ROOT,
    max_estimated_pages: int = MAX_ESTIMATED_PAGES_PER_SHARD,
) -> dict[str, Any]:
    if max_estimated_pages <= 0:
        raise ValueError("max_estimated_pages must be greater than zero")
    available_apps = discover_builtin_apps(apps_root)
    apps = resolve_requested_apps(requested_apps, available_apps=available_apps)

    configured_page_loads = {
        app: configured_apps_page_count(apps_root / app)
        for app in apps
    }
    apps_with_configured_pages = tuple(
        app for app in apps if configured_page_loads[app] > 0
    )
    core_loads = {app: CORE_PAGES_PER_APP for app in apps}
    state_mobile_loads = {app: STATE_MOBILE_PAGES_PER_APP for app in apps}
    quality_loads = {app: QUALITY_PAGES_PER_APP for app in apps}
    layout_loads = {app: LAYOUT_PAGES_PER_APP for app in apps}

    shards = [
        *_broad_shards(
            prefix="core",
            apps=apps,
            scenarios=CORE_SCENARIOS,
            page_loads=core_loads,
            max_pages=max_estimated_pages,
        ),
        *_broad_shards(
            prefix="app-pages",
            apps=apps_with_configured_pages,
            scenarios=APP_PAGE_SCENARIOS,
            page_loads=configured_page_loads,
            max_pages=max_estimated_pages,
        ),
        *_broad_shards(
            prefix="state-mobile",
            apps=apps,
            scenarios=STATE_MOBILE_SCENARIOS,
            page_loads=state_mobile_loads,
            max_pages=max_estimated_pages,
        ),
        *_broad_shards(
            prefix="quality",
            apps=apps,
            scenarios=QUALITY_SCENARIOS,
            page_loads=quality_loads,
            max_pages=max_estimated_pages,
        ),
        *_broad_shards(
            prefix="layout",
            apps=apps,
            scenarios=LAYOUT_SCENARIOS,
            page_loads=layout_loads,
            max_pages=max_estimated_pages,
        ),
    ]

    selected = set(apps)
    focused = [
        (scenario, app)
        for scenario, app in FOCUSED_SCENARIOS
        if app in selected
    ]
    if focused:
        shards.append(
            {
                "shard": "focused",
                "scenarios": " ".join(scenario for scenario, _app in focused),
                "apps": ",".join(sorted({app for _scenario, app in focused})),
                "estimated_pages": len(focused),
            }
        )

    shard_names = [str(shard["shard"]) for shard in shards]
    if len(shard_names) != len(set(shard_names)):
        raise ValueError("planned UI robot shard names must be unique")
    max_planned_pages = max(int(shard["estimated_pages"]) for shard in shards)
    if max_planned_pages > max_estimated_pages:
        raise ValueError(
            f"planned shard load {max_planned_pages} exceeds {max_estimated_pages} pages"
        )

    return {
        "schema": SCHEMA,
        "apps": list(apps),
        "app_count": len(apps),
        "shard_count": len(shards),
        "expected_shards": shard_names,
        "estimated_page_count": sum(int(shard["estimated_pages"]) for shard in shards),
        "max_estimated_pages": max_planned_pages,
        "max_estimated_pages_per_shard": max_estimated_pages,
        "matrix": {"include": shards},
    }


def _write_github_outputs(plan: Mapping[str, Any], output_path: Path) -> None:
    matrix = plan.get("matrix")
    expected_shards = plan.get("expected_shards")
    apps = plan.get("apps")
    if not isinstance(matrix, Mapping) or not isinstance(expected_shards, list) or not isinstance(apps, list):
        raise ValueError("plan is missing matrix, expected_shards, or apps output")
    lines = (
        f"matrix={json.dumps(matrix, sort_keys=True, separators=(',', ':'))}",
        f"expected_shards={','.join(str(item) for item in expected_shards)}",
        f"expected_apps={','.join(str(item) for item in apps)}",
    )
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apps", default="all")
    parser.add_argument("--apps-root", type=Path, default=DEFAULT_APPS_ROOT)
    parser.add_argument(
        "--max-estimated-pages",
        type=int,
        default=MAX_ESTIMATED_PAGES_PER_SHARD,
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--github-output", action="store_true")
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    plan = build_plan(
        requested_apps=args.apps,
        apps_root=args.apps_root,
        max_estimated_pages=args.max_estimated_pages,
    )
    json_kwargs = {
        "sort_keys": True,
        "separators": ((",", ":") if args.compact else None),
        "indent": (None if args.compact else 2),
    }
    rendered = json.dumps(plan, **json_kwargs) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    if args.github_output:
        github_output = os.environ.get("GITHUB_OUTPUT", "").strip()
        if not github_output:
            raise SystemExit("--github-output requires GITHUB_OUTPUT")
        _write_github_outputs(plan, Path(github_output))
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
