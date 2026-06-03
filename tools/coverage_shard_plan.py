#!/usr/bin/env python3
"""Build timing-balanced pytest shard plans for coverage workflows."""

from __future__ import annotations

import argparse
import json
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "agilab.coverage_shard_plan.v1"
DEFAULT_OUTPUT_DIR = Path("test-results") / "coverage-agi-gui-shards"
DEFAULT_TIMING_PATTERNS = (
    "test-results/coverage-agi-gui-timing-cache/junit-agi-gui-*.xml",
    "test-results/junit-agi-gui-*.xml",
)
JUNIT_CHUNK_PREFIX = "junit-agi-gui-"
DEFAULT_SECONDS = 1.0
GLOBAL_IGNORES = {"src/agilab/test/test_model_returns_code.py"}
AGI_GUI_CHUNKS = (
    "support",
    "pipeline",
    "robots",
    "pages-flow",
    "pages-rest",
    "views",
    "reports",
)
STATIC_AGI_GUI_CHUNKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "support",
        (
            "src/agilab/lib/agi-gui/test",
            "src/agilab/lib/agi-web/test",
            "test/test_action_execution.py",
            "test/test_agent_config_and_capabilities.py",
            "test/test_agent_run.py",
            "test/test_agent_trace.py",
            "test/test_agent_tool_safety.py",
            "test/test_app_surface.py",
            "test/test_audience_bridges.py",
            "test/test_environment_health.py",
            "test/test_kubernetes_job.py",
            "test/test_lightning_evidence.py",
            "test/test_orchestrate_cluster.py",
            "test/test_orchestrate_distribution.py",
            "test/test_orchestrate_execute.py",
            "test/test_orchestrate_page_helpers.py",
            "test/test_orchestrate_page_state.py",
            "test/test_orchestrate_page_support.py",
            "test/test_orchestrate_services.py",
            "test/test_orchestrate_support.py",
            "test/test_analysis_page_helpers.py",
            "test/test_about_agilab_helpers.py",
            "test/test_app_template_registry.py",
            "test/test_pytorch_playground_app.py",
            "test/test_code_editor_support.py",
            "test/test_cluster_flight_validation.py",
            "test/test_cluster_lan_discovery.py",
            "test/test_dag_distributed_submitter.py",
            "test/test_agilab_dev_shortcuts.py",
            "test/test_ga_regression_selector.py",
            "test/test_evidence_contract.py",
            "test/test_evidence_graph.py",
            "test/test_env_file_utils.py",
            "test/test_env_footprint.py",
            "test/test_import_guard.py",
            "test/test_logging_utils.py",
            "test/test_page_bundle_registry.py",
            "test/test_python_versions.py",
            "test/test_pinned_expander.py",
            "test/test_security_check.py",
            "test/test_secret_uri.py",
            "test/test_snippet_registry.py",
            "test/test_streamlit_156_adoption.py",
            "test/test_runtime_diagnostics.py",
            "test/test_dag_execution_adapters.py",
            "test/test_dag_execution_registry.py",
            "test/test_dag_run_engine.py",
            "test/test_ui_public_bind_guard.py",
            "test/test_ui_performance.py",
            "test/test_venv_linker.py",
            "test/test_workflow_run_manifest.py",
            "test/test_workflow_runtime_contract.py",
            "test/test_workflow_ui.py",
            "src/agilab/apps/builtin/uav_queue_project/test/test_uav_queue_project.py",
            "src/agilab/apps/builtin/uav_relay_queue_project/test/test_uav_relay_queue_project.py",
        ),
    ),
    (
        "pipeline",
        (
            "test/test_first_proof_cli.py",
            "test/test_first_proof_wizard.py",
            "test/test_generated_actions.py",
            "test/test_promotion_dossier.py",
            "test/test_run_markdown_evidence.py",
            "test/test_run_storyboard.py",
            "test/test_notebook_colab_support.py",
            "test/test_notebook_demo.py",
            "test/test_notebook_import_sample.py",
            "test/test_notebook_import_doctor.py",
            "test/test_page_docs.py",
            "test/test_pipeline_ai.py",
            "test/test_pipeline_ai_support.py",
            "test/test_pipeline_editor.py",
            "test/test_pipeline_lab.py",
            "test/test_pipeline_mistral.py",
            "test/test_pipeline_openai.py",
            "test/test_pipeline_openai_compatible.py",
            "test/test_pipeline_page_state.py",
            "test/test_pipeline_recipe_memory.py",
            "test/test_pipeline_run_controls.py",
            "test/test_pipeline_runtime.py",
            "test/test_pipeline_service_guard.py",
            "test/test_pipeline_sidebar.py",
            "test/test_pipeline_stage_templates.py",
            "test/test_pipeline_stages.py",
            "test/test_pipeline_views.py",
            "test/test_multi_app_dag_draft.py",
            "test/test_multi_app_dag_templates.py",
            "test/test_tracking.py",
            "test/test_flight_telemetry_project_runtime_args.py",
            "test/test_untrusted_content_boundary.py",
            "test/test_workflow_validation.py",
        ),
    ),
    (
        "robots",
        (
            "test/test_agilab_web_robot.py",
            "test/test_agilab_widget_robot_matrix.py",
            "test/test_agilab_widget_robot.py",
            "test/test_first_launch_robot.py",
            "test/test_screenshot_manifest.py",
            "test/test_ui_robot_coverage_contract.py",
            "test/test_ui_robot_action_contract.py",
            "test/test_ui_robot_failure_replay.py",
            "test/test_ui_robot_canary.py",
            "test/test_ui_robot_trend_report.py",
            "test/test_ui_visual_baseline_report.py",
        ),
    ),
    (
        "pages-flow",
        (
            "test/test_ui_pages.py",
            "-k",
            "execute_page or experiment_page or pipeline_page_project_selectbox",
        ),
    ),
    (
        "pages-rest",
        (
            "test/test_ui_pages.py",
            "-k",
            "not (execute_page or experiment_page or pipeline_page_project_selectbox)",
            "test/test_apps_pages_launcher.py",
            "test/test_app_args.py",
            "test/test_pypi_app_packages.py",
            "test/test_streamlit_args.py",
            "test/test_agi_pages_chart_spec.py",
            "test/test_agi_pages_runtime.py",
            "test/test_pagelib.py",
            "test/test_connector_registry.py",
            "test/test_page_project_selector.py",
            "test/test_run_manifest.py",
            "test/test_run_storyboard.py",
        ),
    ),
    ("views", ("test/test_view*.py",)),
    (
        "reports",
        (
            "test/test_ci_provider_artifacts.py",
            "test/test_*_report.py",
        ),
    ),
)


@dataclass(frozen=True)
class TimingRecord:
    chunk: str
    test_path: str
    seconds: float
    source: str


@dataclass(frozen=True)
class ShardItem:
    id: str
    pytest_args: tuple[str, ...]
    timing_paths: tuple[str, ...]
    fallback_chunk: str
    index: int
    seconds: float = 0.0
    locked_chunk: str | None = None


@dataclass(frozen=True)
class Shard:
    name: str
    pytest_args: tuple[str, ...]
    estimated_seconds: float
    item_count: int
    items: tuple[dict[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["pytest_args"] = list(self.pytest_args)
        payload["estimated_seconds"] = round(self.estimated_seconds, 3)
        payload["items"] = list(self.items)
        return payload


@dataclass(frozen=True)
class ShardPlan:
    schema: str
    mode: str
    timing_sources: tuple[str, ...]
    generated_at: str
    shards: tuple[Shard, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "mode": self.mode,
            "timing_sources": list(self.timing_sources),
            "generated_at": self.generated_at,
            "shards": [shard.to_dict() for shard in self.shards],
        }


def static_chunk_args() -> dict[str, list[str]]:
    return {name: list(args) for name, args in STATIC_AGI_GUI_CHUNKS}


def _repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _expand_paths(raw_paths: Sequence[str]) -> list[Path]:
    patterns = list(raw_paths) or list(DEFAULT_TIMING_PATTERNS)
    paths: list[Path] = []
    seen: set[Path] = set()
    for raw in patterns:
        raw_path = Path(raw)
        if raw_path.is_absolute():
            matches = sorted(raw_path.parent.glob(raw_path.name)) if any(token in raw for token in "*?[") else [raw_path]
        else:
            matches = sorted(REPO_ROOT.glob(raw)) if any(token in raw for token in "*?[") else [REPO_ROOT / raw]
        for match in matches:
            resolved = match.resolve()
            if resolved in seen or not match.is_file():
                continue
            paths.append(match)
            seen.add(resolved)
    return sorted(paths, key=_repo_relative)


def _chunk_from_path(path: Path) -> str:
    stem = path.stem
    if stem.startswith(JUNIT_CHUNK_PREFIX):
        chunk = stem.removeprefix(JUNIT_CHUNK_PREFIX)
        if chunk:
            return chunk
    return "unknown"


def _module_to_test_path(classname: str) -> str:
    module = classname.split("[", 1)[0].strip()
    if not module:
        return "unknown"
    candidates = [module.replace(".", "/") + ".py"]
    if module.startswith("test_"):
        candidates.append(f"test/{module}.py")
    parts = module.split(".")
    for index, part in enumerate(parts):
        if part.startswith("test_"):
            candidates.append("/".join(parts[:index] + [part]) + ".py")
    for candidate in dict.fromkeys(candidates):
        if (REPO_ROOT / candidate).is_file():
            return candidate
    for candidate in dict.fromkeys(candidates):
        if candidate.startswith("test/"):
            return candidate
    return candidates[0]


def _case_seconds(testcase: ET.Element) -> float:
    try:
        return max(0.0, float(testcase.attrib.get("time", "0") or 0))
    except ValueError:
        return 0.0


def load_timing_records(paths: Sequence[str] = ()) -> tuple[TimingRecord, ...]:
    records: list[TimingRecord] = []
    for path in _expand_paths(paths):
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError) as exc:
            print(f"coverage_shard_plan: ignoring unreadable JUnit {path}: {exc}", file=sys.stderr)
            continue
        chunk = _chunk_from_path(path)
        source = _repo_relative(path)
        for testcase in root.iter("testcase"):
            records.append(
                TimingRecord(
                    chunk=chunk,
                    test_path=_module_to_test_path(testcase.attrib.get("classname", "")),
                    seconds=_case_seconds(testcase),
                    source=source,
                )
            )
    return tuple(records)


def _discover_target_files(target: str) -> tuple[str, ...]:
    if any(token in target for token in "*?["):
        matches = sorted(
            _repo_relative(path)
            for path in REPO_ROOT.glob(target)
            if path.is_file() and _repo_relative(path) not in GLOBAL_IGNORES
        )
        return tuple(matches) or (target,)
    path = REPO_ROOT / target
    if path.is_dir():
        matches = sorted(
            _repo_relative(child)
            for child in path.rglob("test*.py")
            if child.is_file() and _repo_relative(child) not in GLOBAL_IGNORES
        )
        return tuple(matches) or (target,)
    return (target,)


def _has_global_pytest_options(args: Sequence[str]) -> bool:
    return any(arg.startswith("-") for arg in args)


def _timing_paths_for_args(args: Sequence[str]) -> tuple[str, ...]:
    paths: list[str] = []
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg in {"-k", "-m", "-o"}:
            skip_next = True
            continue
        if arg.startswith("-"):
            continue
        paths.extend(_discover_target_files(arg))
    return tuple(dict.fromkeys(paths))


def _timing_items() -> list[ShardItem]:
    items: list[ShardItem] = []
    for chunk_name, args in STATIC_AGI_GUI_CHUNKS:
        if _has_global_pytest_options(args):
            items.append(
                ShardItem(
                    id=f"{chunk_name}:selector",
                    pytest_args=args,
                    timing_paths=_timing_paths_for_args(args),
                    fallback_chunk=chunk_name,
                    locked_chunk=chunk_name,
                    index=len(items),
                )
            )
            continue
        for arg in args:
            for target in _discover_target_files(arg):
                items.append(
                    ShardItem(
                        id=target,
                        pytest_args=(target,),
                        timing_paths=(target,),
                        fallback_chunk=chunk_name,
                        index=len(items),
                    )
                )
    return items


def _seconds_by_path(records: Sequence[TimingRecord]) -> dict[str, float]:
    timings: dict[str, float] = {}
    for record in records:
        timings[record.test_path] = timings.get(record.test_path, 0.0) + record.seconds
    return timings


def _seconds_by_chunk_path(records: Sequence[TimingRecord]) -> dict[tuple[str, str], float]:
    timings: dict[tuple[str, str], float] = {}
    for record in records:
        key = (record.chunk, record.test_path)
        timings[key] = timings.get(key, 0.0) + record.seconds
    return timings


def _item_seconds(
    item: ShardItem,
    *,
    by_path: dict[str, float],
    by_chunk_path: dict[tuple[str, str], float],
    default_seconds: float,
) -> float:
    if item.locked_chunk is not None:
        locked_seconds = sum(by_chunk_path.get((item.locked_chunk, path), 0.0) for path in item.timing_paths)
        if locked_seconds > 0:
            return locked_seconds
    seconds = sum(by_path.get(path, 0.0) for path in item.timing_paths)
    if seconds > 0:
        return seconds
    return default_seconds


def _item_payload(item: ShardItem) -> dict[str, object]:
    return {
        "id": item.id,
        "fallback_chunk": item.fallback_chunk,
        "pytest_args": list(item.pytest_args),
        "seconds": round(item.seconds, 3),
        "locked": item.locked_chunk is not None,
    }


def _flatten_items(items: Sequence[ShardItem]) -> tuple[str, ...]:
    flattened: list[str] = []
    for item in sorted(items, key=lambda value: value.index):
        flattened.extend(item.pytest_args)
    return tuple(flattened)


def _static_plan() -> ShardPlan:
    assignments: dict[str, list[ShardItem]] = {chunk: [] for chunk in AGI_GUI_CHUNKS}
    for item in _timing_items():
        assignments[item.fallback_chunk].append(item)

    shards = tuple(
        Shard(
            name=name,
            pytest_args=_flatten_items(assignments[name]),
            estimated_seconds=0.0,
            item_count=len(assignments[name]),
            items=tuple(_item_payload(item) for item in assignments[name]),
        )
        for name in AGI_GUI_CHUNKS
    )
    return ShardPlan(
        schema=SCHEMA,
        mode="static",
        timing_sources=(),
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        shards=shards,
    )


def build_plan(paths: Sequence[str] = (), *, default_seconds: float = DEFAULT_SECONDS) -> ShardPlan:
    records = load_timing_records(paths)
    if not records:
        return _static_plan()

    by_path = _seconds_by_path(records)
    by_chunk_path = _seconds_by_chunk_path(records)
    assignments: dict[str, list[ShardItem]] = {chunk: [] for chunk in AGI_GUI_CHUNKS}
    totals: dict[str, float] = {chunk: 0.0 for chunk in AGI_GUI_CHUNKS}
    locked_chunks: set[str] = set()
    unlocked_items: list[ShardItem] = []

    for item in _timing_items():
        timed_item = replace(
            item,
            seconds=_item_seconds(
                item,
                by_path=by_path,
                by_chunk_path=by_chunk_path,
                default_seconds=default_seconds,
            ),
        )
        if timed_item.locked_chunk is not None:
            assignments[timed_item.locked_chunk].append(timed_item)
            totals[timed_item.locked_chunk] += timed_item.seconds
            locked_chunks.add(timed_item.locked_chunk)
        else:
            unlocked_items.append(timed_item)

    candidate_chunks = [chunk for chunk in AGI_GUI_CHUNKS if chunk not in locked_chunks] or list(AGI_GUI_CHUNKS)
    chunk_order = {chunk: index for index, chunk in enumerate(AGI_GUI_CHUNKS)}
    for item in sorted(unlocked_items, key=lambda value: (-value.seconds, value.id)):
        chunk = min(candidate_chunks, key=lambda name: (totals[name], chunk_order[name]))
        assignments[chunk].append(item)
        totals[chunk] += item.seconds

    shards = tuple(
        Shard(
            name=chunk,
            pytest_args=_flatten_items(assignments[chunk]),
            estimated_seconds=totals[chunk],
            item_count=len(assignments[chunk]),
            items=tuple(_item_payload(item) for item in sorted(assignments[chunk], key=lambda value: value.index)),
        )
        for chunk in AGI_GUI_CHUNKS
    )
    return ShardPlan(
        schema=SCHEMA,
        mode="timing-balanced",
        timing_sources=tuple(sorted({record.source for record in records})),
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        shards=shards,
    )


def _write_plan_files(plan: ShardPlan, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = output_dir / "plan.json"
    plan_payload = plan.to_dict()
    plan_path.write_text(json.dumps(plan_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for shard in plan.shards:
        (output_dir / f"{shard.name}.json").write_text(
            json.dumps(shard.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return plan_path


def _load_plan(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError(f"unexpected shard plan schema in {path}")
    return payload


def _chunk_args_from_plan(path: Path, chunk: str) -> list[str]:
    payload = _load_plan(path)
    shards = payload.get("shards")
    if not isinstance(shards, list):
        raise ValueError(f"missing shards in {path}")
    for shard in shards:
        if not isinstance(shard, dict) or shard.get("name") != chunk:
            continue
        raw_args = shard.get("pytest_args")
        if not isinstance(raw_args, list) or not all(isinstance(arg, str) for arg in raw_args):
            raise ValueError(f"invalid pytest_args for shard {chunk}")
        return list(raw_args)
    raise ValueError(f"unknown shard {chunk!r}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or read an AGI-GUI coverage shard plan.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    write = subparsers.add_parser("write", help="Write a shard plan and per-shard JSON files.")
    write.add_argument("timings", nargs="*", help="JUnit XML files or globs. Defaults to cached AGI-GUI timings.")
    write.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    write.add_argument("--default-seconds", type=float, default=DEFAULT_SECONDS)
    write.add_argument("--json", action="store_true", help="Print the full plan JSON to stdout.")

    print_args = subparsers.add_parser("print-args", help="Print one planned pytest argument per line.")
    print_args.add_argument("--plan", type=Path, required=True)
    print_args.add_argument("--chunk", choices=AGI_GUI_CHUNKS, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "write":
        plan = build_plan(args.timings, default_seconds=args.default_seconds)
        plan_path = _write_plan_files(plan, args.output_dir)
        payload = plan.to_dict()
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(
                json.dumps(
                    {
                        "schema": SCHEMA,
                        "mode": plan.mode,
                        "plan_path": plan_path.as_posix(),
                        "timing_sources": list(plan.timing_sources),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    if args.command == "print-args":
        for arg in _chunk_args_from_plan(args.plan, args.chunk):
            print(arg)
        return 0
    parser.error(f"unsupported command {args.command!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
