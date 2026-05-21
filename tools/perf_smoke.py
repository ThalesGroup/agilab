#!/usr/bin/env python3
"""Run small repeatable AGILAB performance smoke benchmarks."""

from __future__ import annotations

import argparse
import json
import shlex
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class PerfScenario:
    name: str
    description: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class PerfSample:
    iteration: int
    wall_seconds: float
    returncode: int


@dataclass(frozen=True)
class PerfResult:
    scenario: str
    description: str
    command: list[str]
    repeats: int
    warmups: int
    samples: list[PerfSample]
    failures: int
    median_seconds: float | None
    mean_seconds: float | None
    min_seconds: float | None
    max_seconds: float | None
    stdev_seconds: float | None


def _repo_python_paths(extra_paths: Sequence[Path] = ()) -> list[str]:
    base = [
        REPO_ROOT / "src",
        REPO_ROOT / "src/agilab/core/agi-env/src",
        REPO_ROOT / "src/agilab/core/agi-node/src",
        REPO_ROOT / "src/agilab/core/agi-cluster/src",
        REPO_ROOT / "src/agilab/core/agi-core/src",
    ]
    ordered: list[str] = []
    seen: set[str] = set()
    for path in [*base, *extra_paths]:
        text = str(path.resolve())
        if text not in seen:
            ordered.append(text)
            seen.add(text)
    return ordered


def _import_command(module_name: str, *, extra_paths: Sequence[Path] = ()) -> tuple[str, ...]:
    paths_literal = repr(_repo_python_paths(extra_paths))
    code = (
        "import importlib, sys; "
        f"paths = {paths_literal}; "
        "[sys.path.insert(0, p) for p in reversed(paths) if p not in sys.path]; "
        f"importlib.import_module({module_name!r})"
    )
    return (sys.executable, "-c", code)


def scenario_catalog() -> dict[str, PerfScenario]:
    maps_network_src = REPO_ROOT / "src/agilab/apps-pages/view_maps_network/src"
    maps_3d_src = REPO_ROOT / "src/agilab/apps-pages/view_maps_3d/src"
    return {
        "orchestrate-execute-import": PerfScenario(
            name="orchestrate-execute-import",
            description="Top-level GUI execution controller import startup.",
            command=_import_command("agilab.orchestrate_execute"),
        ),
        "pipeline-ai-import": PerfScenario(
            name="pipeline-ai-import",
            description="Top-level AI pipeline controller import startup.",
            command=_import_command("agilab.pipeline_ai"),
        ),
        "runtime-distribution-import": PerfScenario(
            name="runtime-distribution-import",
            description="Shared cluster runtime distribution support import startup.",
            command=_import_command(
                "agi_cluster.agi_distributor.runtime_distribution_support"
            ),
        ),
        "base-worker-import": PerfScenario(
            name="base-worker-import",
            description="Shared base worker dispatcher import startup.",
            command=_import_command("agi_node.agi_dispatcher.base_worker"),
        ),
        "agi-page-network-map-import": PerfScenario(
            name="agi-page-network-map-import",
            description="Heavy network page package import startup.",
            command=_import_command(
                "view_maps_network.view_maps_network",
                extra_paths=[maps_network_src],
            ),
        ),
        "agi-page-geospatial-3d-import": PerfScenario(
            name="agi-page-geospatial-3d-import",
            description="Heavy 3D maps page package import startup.",
            command=_import_command(
                "view_maps_3d.view_maps_3d",
                extra_paths=[maps_3d_src],
            ),
        ),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run small repeatable AGILAB perf smoke scenarios and report wall-clock timings. "
            "Useful for comparing startup-sensitive imports and lightweight command paths "
            "before/after maintainability refactors."
        )
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="List built-in scenarios and exit.",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=sorted(scenario_catalog()),
        help="Built-in scenario(s) to run. Defaults to all built-in scenarios.",
    )
    parser.add_argument(
        "--command",
        action="append",
        help=(
            "Explicit command to benchmark instead of built-in scenarios. "
            "Pass it as a single shell-style string, for example: "
            '--command "python -V"'
        ),
    )
    parser.add_argument("--repeats", type=int, default=3, help="Measured repetitions per scenario.")
    parser.add_argument("--warmups", type=int, default=1, help="Warmup runs per scenario.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )
    return parser


def _measure_once(
    command: Sequence[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    time_fn: Callable[[], float] = time.perf_counter,
    cwd: Path = REPO_ROOT,
) -> tuple[float, int]:
    start = time_fn()
    proc = runner(
        list(command),
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    wall = time_fn() - start
    return wall, int(proc.returncode)


def run_scenario(
    scenario: PerfScenario,
    *,
    repeats: int,
    warmups: int,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    time_fn: Callable[[], float] = time.perf_counter,
    cwd: Path = REPO_ROOT,
) -> PerfResult:
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    if warmups < 0:
        raise ValueError("warmups must be >= 0")

    measured: list[PerfSample] = []
    failures = 0
    for idx in range(warmups + repeats):
        wall, returncode = _measure_once(
            scenario.command,
            runner=runner,
            time_fn=time_fn,
            cwd=cwd,
        )
        if idx >= warmups:
            measured.append(
                PerfSample(
                    iteration=idx - warmups + 1,
                    wall_seconds=wall,
                    returncode=returncode,
                )
            )
            if returncode != 0:
                failures += 1

    wall_values = [sample.wall_seconds for sample in measured]
    stdev = statistics.stdev(wall_values) if len(wall_values) > 1 else 0.0
    return PerfResult(
        scenario=scenario.name,
        description=scenario.description,
        command=list(scenario.command),
        repeats=repeats,
        warmups=warmups,
        samples=measured,
        failures=failures,
        median_seconds=statistics.median(wall_values) if wall_values else None,
        mean_seconds=statistics.mean(wall_values) if wall_values else None,
        min_seconds=min(wall_values) if wall_values else None,
        max_seconds=max(wall_values) if wall_values else None,
        stdev_seconds=stdev if wall_values else None,
    )


def _custom_command_scenario(command: Sequence[str]) -> PerfScenario:
    if not command:
        raise ValueError("--command requires at least one token")
    return PerfScenario(
        name="custom-command",
        description="User-supplied command benchmark.",
        command=tuple(command),
    )


def _resolve_scenarios(args: argparse.Namespace) -> list[PerfScenario]:
    catalog = scenario_catalog()
    if args.command:
        if len(args.command) != 1:
            raise ValueError("use exactly one --command value")
        return [_custom_command_scenario(shlex.split(args.command[0]))]
    selected = args.scenario or list(catalog)
    return [catalog[name] for name in selected]


def _render_human(results: Sequence[PerfResult]) -> str:
    lines: list[str] = []
    for result in results:
        status = "FAILED" if result.failures else "OK"
        lines.append(f"{result.scenario}: {status}")
        lines.append(f"  description: {result.description}")
        lines.append(f"  command: {shlex.join(result.command)}")
        lines.append(
            "  stats: "
            f"median={result.median_seconds:.4f}s "
            f"mean={result.mean_seconds:.4f}s "
            f"min={result.min_seconds:.4f}s "
            f"max={result.max_seconds:.4f}s "
            f"stdev={result.stdev_seconds:.4f}s "
            f"failures={result.failures}/{len(result.samples)}"
        )
        lines.append(
            "  samples: "
            + ", ".join(
                f"{sample.iteration}:{sample.wall_seconds:.4f}s(rc={sample.returncode})"
                for sample in result.samples
            )
        )
    return "\n".join(lines)


def _results_to_json(results: Sequence[PerfResult]) -> str:
    payload = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "repo_root": str(REPO_ROOT),
        "results": [
            {
                **asdict(result),
                "samples": [asdict(sample) for sample in result.samples],
            }
            for result in results
        ],
    }
    return json.dumps(payload, indent=2)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    catalog = scenario_catalog()

    if args.list_scenarios:
        for name, scenario in catalog.items():
            print(f"{name}: {scenario.description}")
        return 0

    try:
        scenarios = _resolve_scenarios(args)
    except ValueError as exc:
        parser.exit(2, f"perf_smoke: {exc}\n")

    results = [
        run_scenario(
            scenario,
            repeats=args.repeats,
            warmups=args.warmups,
        )
        for scenario in scenarios
    ]

    if args.json:
        print(_results_to_json(results))
    else:
        print(_render_human(results))

    return 1 if any(result.failures for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
