#!/usr/bin/env python3
"""Aggregate sharded UI robot matrix artifacts into one audit report."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import shlex
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "agilab.ui_robot_matrix_aggregate.v1"
SHARD_MANIFEST_SCHEMA = "agilab.ui_robot_matrix_shard_manifest.v1"
SHARD_MANIFEST_FILENAME = "shard-manifest.json"
TREND_REPORT_SCHEMA = "agilab.ui_robot_trend_report.v1"
DEFAULT_EXPECTED_SHARDS = ("core", "state", "quality", "layout")
FAILURE_SAMPLE_LIMIT = 20
FAILURE_REPLAY_COMMAND_PREFIX = (
    "uv",
    "--preview-features",
    "extra-build-dependencies",
    "run",
    "python",
    "tools/ui_robot_failure_replay.py",
)


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _int_value(payload: Mapping[str, Any], key: str) -> int:
    return int(payload.get(key) or 0)


def _float_value(payload: Mapping[str, Any], key: str) -> float:
    return float(payload.get(key) or 0.0)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _relative_to_base(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return os.path.relpath(path, start=base).replace(os.sep, "/")


def _resolve_manifest_path(manifest_path: Path, value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return (manifest_path.parent / value).resolve(strict=False)


def _shard_from_summary_path(summary_path: Path) -> str:
    parts = summary_path.parts
    for index, part in enumerate(parts[:-2]):
        if part == "test-results" and parts[index + 1] == "ui-robot-matrix":
            return parts[index + 2]
    return summary_path.parent.name


def _scenario_from_bundle_manifest(path: Path) -> str:
    try:
        payload = _load_json(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return ""
    command = payload.get("command")
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        return ""
    return str(payload.get("scenario") or path.parent.parent.name)


def _replay_command(bundle_path: str) -> dict[str, object]:
    argv = [*FAILURE_REPLAY_COMMAND_PREFIX, bundle_path]
    return {
        "argv": argv,
        "shell": shlex.join(argv),
    }


def write_shard_manifest(
    *,
    result_dir: Path,
    screenshot_dir: Path,
    shard: str,
    output: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    result_dir = result_dir.resolve(strict=False)
    screenshot_dir = screenshot_dir.resolve(strict=False)
    result_dir.mkdir(parents=True, exist_ok=True)
    output = (output or result_dir / SHARD_MANIFEST_FILENAME).resolve(strict=False)
    failure_bundle_dir = result_dir / "failure-bundles"
    failure_manifest_paths = (
        sorted(path for path in failure_bundle_dir.rglob("manifest.json") if path.is_file())
        if failure_bundle_dir.exists()
        else []
    )
    screenshot_count = (
        sum(1 for path in screenshot_dir.rglob("*.png") if path.is_file())
        if screenshot_dir.exists()
        else 0
    )
    payload = {
        "schema": SHARD_MANIFEST_SCHEMA,
        "generated_at": generated_at or utc_now_iso(),
        "shard": shard,
        "summary_file": "summary.json",
        "trend_report_file": "trend-report.json",
        "trend_text_file": "trend-report.txt",
        "exit_code_file": "exit-code.txt",
        "failure_bundle_dir": "failure-bundles",
        "failure_bundle_manifests": [
            _relative_to_base(path, result_dir) for path in failure_manifest_paths
        ],
        "screenshot_dir": _relative_to_base(screenshot_dir, result_dir),
        "screenshot_count": screenshot_count,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def discover_failure_bundles(
    root: Path,
    shard_dir: Path,
    *,
    manifest_paths: Sequence[Path] | None = None,
) -> dict[str, list[dict[str, object]]]:
    bundles: dict[str, list[dict[str, object]]] = {}
    if manifest_paths is None:
        failure_root = shard_dir / "failure-bundles"
        if not failure_root.exists():
            return bundles
        discovered_manifest_paths = sorted(failure_root.rglob("manifest.json"))
    else:
        discovered_manifest_paths = sorted(path for path in manifest_paths if path.is_file())
    for manifest_path in discovered_manifest_paths:
        scenario = _scenario_from_bundle_manifest(manifest_path)
        if not scenario:
            continue
        try:
            manifest = _load_json(manifest_path)
        except (OSError, json.JSONDecodeError, ValueError):
            manifest = {}
        retry = _mapping(manifest.get("failure_artifact_retry"))
        retry_payload: dict[str, object] = {}
        if retry:
            command = retry.get("command")
            retry_payload = {
                "success": retry.get("success") is True,
                "returncode": _int_value(retry, "returncode"),
                "duration_seconds": _float_value(retry, "duration_seconds"),
                "summary_path": str(retry.get("summary_path") or ""),
                "progress_path": str(retry.get("progress_path") or ""),
                "trace_dir": str(retry.get("trace_dir") or ""),
                "har_dir": str(retry.get("har_dir") or ""),
                "video_dir": str(retry.get("video_dir") or ""),
                "command": command if isinstance(command, list) else [],
                "command_shell": (
                    shlex.join(command)
                    if isinstance(command, list) and all(isinstance(item, str) for item in command)
                    else ""
                ),
            }
        bundle_path = _relative(manifest_path.parent, root)
        replay = _replay_command(bundle_path)
        bundle_payload: dict[str, object] = {
            "scenario": scenario,
            "bundle": bundle_path,
            "manifest": _relative(manifest_path, root),
            "replay_command": replay["shell"],
            "replay_argv": replay["argv"],
        }
        if retry_payload:
            bundle_payload["failure_artifact_retry"] = retry_payload
        bundles.setdefault(scenario, []).append(bundle_payload)
    return bundles


def discover_shard_summary_paths(root: Path) -> dict[str, Path]:
    summaries: dict[str, Path] = {}
    for summary_path in sorted(root.rglob("summary.json")):
        shard_dir = summary_path.parent
        if not (shard_dir / "exit-code.txt").is_file():
            continue
        shard = _shard_from_summary_path(summary_path)
        summaries.setdefault(shard, summary_path)
    return summaries


def discover_shard_manifests(root: Path) -> dict[str, tuple[Path, dict[str, Any]]]:
    manifests: dict[str, tuple[Path, dict[str, Any]]] = {}
    for manifest_path in sorted(root.rglob(SHARD_MANIFEST_FILENAME)):
        try:
            payload = _load_json(manifest_path)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if payload.get("schema") != SHARD_MANIFEST_SCHEMA:
            continue
        shard = str(payload.get("shard") or "").strip()
        if not shard:
            continue
        manifests.setdefault(shard, (manifest_path, payload))
    return manifests


def _trend_ok(trend_report: Mapping[str, Any]) -> bool:
    trend_summary = _mapping(trend_report.get("summary"))
    return (
        trend_report.get("schema") == TREND_REPORT_SCHEMA
        and trend_report.get("success") is True
        and _int_value(trend_summary, "failed_page_count") == 0
        and _int_value(trend_summary, "flaky_page_count") == 0
        and _int_value(trend_summary, "parse_error_count") == 0
        and _int_value(trend_summary, "budget_violation_count") == 0
    )


def _load_shard_payload(
    root: Path,
    shard: str,
    *,
    shard_dir: Path,
    summary_path: Path,
    trend_path: Path,
    exit_code_path: Path,
    manifest_path: Path | None = None,
    failure_manifest_paths: Sequence[Path] | None = None,
    screenshot_count: int = 0,
) -> dict[str, Any]:
    summary = _load_json(summary_path) if summary_path.is_file() else {}
    trend_report = _load_json(trend_path) if trend_path.is_file() else {}
    trend_summary = _mapping(trend_report.get("summary"))
    exit_code = exit_code_path.read_text(encoding="utf-8").strip() if exit_code_path.is_file() else ""
    failed_scenarios = [str(item) for item in summary.get("failed_scenarios") or []]
    failure_bundles = discover_failure_bundles(
        root,
        shard_dir,
        manifest_paths=failure_manifest_paths,
    )
    failure_samples = []
    for sample in summary.get("failure_samples") or []:
        if isinstance(sample, Mapping):
            sample_payload: dict[str, object] = {
                "shard": shard,
                **{str(key): str(value) for key, value in sample.items()},
            }
            bundles = failure_bundles.get(str(sample_payload.get("scenario", "")), [])
            if bundles:
                first_bundle = bundles[0]
                sample_payload["failure_bundle"] = str(first_bundle.get("bundle", ""))
                sample_payload["failure_replay_command"] = str(first_bundle.get("replay_command", ""))
                sample_payload["failure_replay_argv"] = list(first_bundle.get("replay_argv", []))
                retry = _mapping(first_bundle.get("failure_artifact_retry"))
                if retry:
                    sample_payload["failure_artifact_retry"] = dict(retry)
                    sample_payload["failure_artifact_retry_status"] = (
                        "PASS" if retry.get("success") is True else "FAIL"
                    )
                    sample_payload["failure_artifact_retry_trace_dir"] = str(retry.get("trace_dir") or "")
                    sample_payload["failure_artifact_retry_har_dir"] = str(retry.get("har_dir") or "")
                    sample_payload["failure_artifact_retry_video_dir"] = str(retry.get("video_dir") or "")
            failure_samples.append(sample_payload)
    success = (
        summary.get("success") is True
        and exit_code == "0"
        and _trend_ok(trend_report)
        and _int_value(summary, "failed_count") == 0
    )
    return {
        "name": shard,
        "success": success,
        "exit_code": exit_code,
        "manifest_file": _relative(manifest_path, root) if manifest_path is not None else "",
        "summary_file": _relative(summary_path, root),
        "trend_report_file": _relative(trend_path, root) if trend_path.is_file() else "",
        "exit_code_file": _relative(exit_code_path, root) if exit_code_path.is_file() else "",
        "scenario_count": _int_value(summary, "scenario_count"),
        "app_count": _int_value(summary, "app_count"),
        "page_count": _int_value(summary, "page_count"),
        "widget_count": _int_value(summary, "widget_count"),
        "interacted_count": _int_value(summary, "interacted_count"),
        "probed_count": _int_value(summary, "probed_count"),
        "skipped_count": _int_value(summary, "skipped_count"),
        "failed_count": _int_value(summary, "failed_count"),
        "cached_count": _int_value(summary, "cached_count"),
        "duration_seconds": _float_value(summary, "duration_seconds"),
        "failed_scenarios": failed_scenarios,
        "failure_artifact_retry_count": _int_value(summary, "failure_artifact_retry_count"),
        "failure_artifact_retry_passed_count": _int_value(summary, "failure_artifact_retry_passed_count"),
        "failure_bundles": [
            bundle
            for scenario_bundles in failure_bundles.values()
            for bundle in scenario_bundles
        ],
        "failure_samples": failure_samples[:FAILURE_SAMPLE_LIMIT],
        "screenshot_count": int(screenshot_count or 0),
        "trend": {
            "schema": str(trend_report.get("schema", "") or ""),
            "success": bool(trend_report.get("success")),
            "page_count": _int_value(trend_summary, "page_count"),
            "failed_page_count": _int_value(trend_summary, "failed_page_count"),
            "flaky_page_count": _int_value(trend_summary, "flaky_page_count"),
            "slow_page_count": _int_value(trend_summary, "slow_page_count"),
            "parse_error_count": _int_value(trend_summary, "parse_error_count"),
            "budget_violation_count": _int_value(trend_summary, "budget_violation_count"),
            "total_duration_seconds": _float_value(trend_summary, "total_duration_seconds"),
            "mean_page_duration_seconds": _float_value(trend_summary, "mean_page_duration_seconds"),
        },
    }


def _load_shard(root: Path, shard: str, summary_path: Path) -> dict[str, Any]:
    shard_dir = summary_path.parent
    return _load_shard_payload(
        root,
        shard,
        shard_dir=shard_dir,
        summary_path=summary_path,
        trend_path=shard_dir / "trend-report.json",
        exit_code_path=shard_dir / "exit-code.txt",
    )


def _load_shard_from_manifest(
    root: Path,
    shard: str,
    manifest_path: Path,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    shard_dir = manifest_path.parent
    summary_path = (
        _resolve_manifest_path(manifest_path, manifest.get("summary_file"))
        or shard_dir / "summary.json"
    )
    trend_path = (
        _resolve_manifest_path(manifest_path, manifest.get("trend_report_file"))
        or shard_dir / "trend-report.json"
    )
    exit_code_path = (
        _resolve_manifest_path(manifest_path, manifest.get("exit_code_file"))
        or shard_dir / "exit-code.txt"
    )
    failure_manifest_paths = [
        resolved
        for item in manifest.get("failure_bundle_manifests") or []
        if (resolved := _resolve_manifest_path(manifest_path, item)) is not None
    ]
    return _load_shard_payload(
        root,
        shard,
        shard_dir=shard_dir,
        summary_path=summary_path,
        trend_path=trend_path,
        exit_code_path=exit_code_path,
        manifest_path=manifest_path,
        failure_manifest_paths=failure_manifest_paths,
        screenshot_count=_int_value(manifest, "screenshot_count"),
    )


def build_aggregate(root: Path, *, expected_shards: Sequence[str] = DEFAULT_EXPECTED_SHARDS) -> dict[str, Any]:
    root = root.resolve(strict=False)
    manifests = discover_shard_manifests(root)
    discovery_mode = "manifest" if manifests else "summary"
    if manifests:
        discovered = manifests

        def load_discovered_shard(name: str) -> dict[str, Any]:
            manifest_path, manifest = discovered[name]
            return _load_shard_from_manifest(root, name, manifest_path, manifest)

    else:
        discovered = discover_shard_summary_paths(root)

        def load_discovered_shard(name: str) -> dict[str, Any]:
            return _load_shard(root, name, discovered[name])

    shards = [load_discovered_shard(shard) for shard in expected_shards if shard in discovered]
    extra_shards = sorted(set(discovered) - set(expected_shards))
    shards.extend(load_discovered_shard(shard) for shard in extra_shards)
    missing_shards = [shard for shard in expected_shards if shard not in discovered]
    failed_shards = [str(shard["name"]) for shard in shards if shard.get("success") is not True]
    failure_samples = [
        sample
        for shard in shards
        for sample in shard.get("failure_samples", [])
        if isinstance(sample, Mapping)
    ][:FAILURE_SAMPLE_LIMIT]
    trend_failure_keys = (
        "failed_page_count",
        "flaky_page_count",
        "parse_error_count",
        "budget_violation_count",
    )
    trend = {
        "schema": TREND_REPORT_SCHEMA,
        "success": not any(
            _int_value(_mapping(shard.get("trend")), key)
            for shard in shards
            for key in trend_failure_keys
        ),
        "page_count": sum(_int_value(_mapping(shard.get("trend")), "page_count") for shard in shards),
        "failed_page_count": sum(_int_value(_mapping(shard.get("trend")), "failed_page_count") for shard in shards),
        "flaky_page_count": sum(_int_value(_mapping(shard.get("trend")), "flaky_page_count") for shard in shards),
        "slow_page_count": sum(_int_value(_mapping(shard.get("trend")), "slow_page_count") for shard in shards),
        "parse_error_count": sum(_int_value(_mapping(shard.get("trend")), "parse_error_count") for shard in shards),
        "budget_violation_count": sum(
            _int_value(_mapping(shard.get("trend")), "budget_violation_count")
            for shard in shards
        ),
        "total_duration_seconds": sum(
            _float_value(_mapping(shard.get("trend")), "total_duration_seconds")
            for shard in shards
        ),
    }
    trend["mean_page_duration_seconds"] = (
        float(trend["total_duration_seconds"]) / max(1, int(trend["page_count"]))
    )
    success = bool(shards) and not missing_shards and not failed_shards and bool(trend["success"])
    summary = {
        "expected_shard_count": len(expected_shards),
        "shard_count": len(shards),
        "missing_shard_count": len(missing_shards),
        "failed_shard_count": len(failed_shards),
        "scenario_count": sum(_int_value(shard, "scenario_count") for shard in shards),
        "app_count": max([_int_value(shard, "app_count") for shard in shards] or [0]),
        "page_count": sum(_int_value(shard, "page_count") for shard in shards),
        "widget_count": sum(_int_value(shard, "widget_count") for shard in shards),
        "interacted_count": sum(_int_value(shard, "interacted_count") for shard in shards),
        "probed_count": sum(_int_value(shard, "probed_count") for shard in shards),
        "skipped_count": sum(_int_value(shard, "skipped_count") for shard in shards),
        "failed_count": sum(_int_value(shard, "failed_count") for shard in shards),
        "cached_count": sum(_int_value(shard, "cached_count") for shard in shards),
        "failure_artifact_retry_count": sum(_int_value(shard, "failure_artifact_retry_count") for shard in shards),
        "failure_artifact_retry_passed_count": sum(
            _int_value(shard, "failure_artifact_retry_passed_count") for shard in shards
        ),
        "duration_seconds": sum(_float_value(shard, "duration_seconds") for shard in shards),
        "screenshot_count": sum(_int_value(shard, "screenshot_count") for shard in shards),
        "trend": trend,
    }
    return {
        "schema": SCHEMA,
        "generated_at": utc_now_iso(),
        "success": success,
        "root": root.as_posix(),
        "expected_shards": list(expected_shards),
        "missing_shards": missing_shards,
        "failed_shards": failed_shards,
        "extra_shards": extra_shards,
        "summary": summary,
        "discovery": {
            "mode": discovery_mode,
            "manifest_count": len(manifests),
            "shard_count": len(discovered),
        },
        "failed_scenarios": [
            f"{shard['name']}:{scenario}"
            for shard in shards
            for scenario in shard.get("failed_scenarios", [])
        ],
        "failure_samples": failure_samples,
        "shards": shards,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    summary = _mapping(report.get("summary"))
    status = "PASS" if report.get("success") is True else "FAIL"
    lines = [
        "## UI robot matrix aggregate",
        "",
        f"- Status: `{status}`",
        f"- Shards: `{summary.get('shard_count', 0)}/{summary.get('expected_shard_count', 0)}`",
        f"- Pages: `{summary.get('page_count', 0)}`",
        f"- Widgets: `{summary.get('widget_count', 0)}`",
        f"- Failed: `{summary.get('failed_count', 0)}`",
        f"- Cached: `{summary.get('cached_count', 0)}`",
        f"- Artifact retries: `{summary.get('failure_artifact_retry_count', 0)}`",
        "",
        "| Shard | Status | Scenarios | Pages | Widgets | Failed | Cached | Retries | Exit | Trend |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for shard in report.get("shards", []) or []:
        if not isinstance(shard, Mapping):
            continue
        trend = _mapping(shard.get("trend"))
        trend_status = "PASS" if trend.get("success") is True else "FAIL"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(shard.get("name", "")),
                    "PASS" if shard.get("success") is True else "FAIL",
                    str(shard.get("scenario_count", 0)),
                    str(shard.get("page_count", 0)),
                    str(shard.get("widget_count", 0)),
                    str(shard.get("failed_count", 0)),
                    str(shard.get("cached_count", 0)),
                    str(shard.get("failure_artifact_retry_count", 0)),
                    str(shard.get("exit_code", "")),
                    trend_status,
                ]
            )
            + " |"
        )
    missing = report.get("missing_shards") or []
    if missing:
        lines.extend(["", "### Missing Shards", *[f"- `{shard}`" for shard in missing]])
    samples = report.get("failure_samples") or []
    lines.append("")
    lines.append("### Failure Samples")
    if samples:
        for sample in samples[:FAILURE_SAMPLE_LIMIT]:
            if not isinstance(sample, Mapping):
                continue
            lines.append(
                "- "
                f"`{sample.get('shard', '')}` "
                f"`{sample.get('scenario', '')}` "
                f"`{sample.get('app', '')}` "
                f"`{sample.get('page', '')}` "
                f"`{sample.get('kind', '')}` "
                f"`{sample.get('label', '')}`: "
                f"{sample.get('detail', '')}"
            )
            if sample.get("failure_bundle"):
                lines.append(f"  Bundle: `{sample.get('failure_bundle')}`")
            if sample.get("failure_replay_command"):
                lines.append(f"  Replay: `{sample.get('failure_replay_command')}`")
            retry = _mapping(sample.get("failure_artifact_retry"))
            if retry:
                lines.append(f"  Artifact retry: `{sample.get('failure_artifact_retry_status', '')}`")
                if retry.get("trace_dir"):
                    lines.append(f"  Trace: `{retry.get('trace_dir')}`")
                if retry.get("har_dir"):
                    lines.append(f"  HAR: `{retry.get('har_dir')}`")
                if retry.get("video_dir"):
                    lines.append(f"  Video: `{retry.get('video_dir')}`")
    else:
        lines.append("No failure samples recorded.")
    return "\n".join(lines) + "\n"


def _parse_expected_shards(value: str) -> tuple[str, ...]:
    shards = tuple(item.strip() for item in value.split(",") if item.strip())
    return shards or DEFAULT_EXPECTED_SHARDS


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT / "test-results" / "ui-robot-matrix-artifacts",
    )
    parser.add_argument("--expected-shards", default=",".join(DEFAULT_EXPECTED_SHARDS))
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "test-results" / "ui-robot-matrix-aggregate" / "aggregate.json",
    )
    parser.add_argument("--summary-markdown", type=Path)
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--write-shard-manifest", action="store_true")
    parser.add_argument("--result-dir", type=Path)
    parser.add_argument("--screenshot-dir", type=Path)
    parser.add_argument("--shard")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    json_kwargs = {
        "sort_keys": True,
        "separators": ((",", ":") if args.compact else None),
        "indent": (None if args.compact else 2),
    }
    if args.write_shard_manifest:
        if args.result_dir is None or args.screenshot_dir is None or not args.shard:
            raise SystemExit("--write-shard-manifest requires --result-dir, --screenshot-dir, and --shard")
        manifest = write_shard_manifest(
            result_dir=args.result_dir,
            screenshot_dir=args.screenshot_dir,
            shard=str(args.shard),
        )
        print(json.dumps(manifest, **json_kwargs))
        return 0

    report = build_aggregate(args.root, expected_shards=_parse_expected_shards(args.expected_shards))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, **json_kwargs) + "\n",
        encoding="utf-8",
    )
    if args.summary_markdown:
        args.summary_markdown.parent.mkdir(parents=True, exist_ok=True)
        args.summary_markdown.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, **json_kwargs))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
