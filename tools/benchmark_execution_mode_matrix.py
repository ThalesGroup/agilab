from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import shlex
import statistics
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from benchmark_execution_playground import APPS, APPS_PATH, _load_classes


MODE_NAMES = {
    0: "python",
    1: "pool of process",
    2: "cython",
    3: "pool and cython",
    4: "dask",
    5: "dask and pool",
    6: "dask and cython",
    7: "dask and pool and cython",
    8: "rapids",
    9: "rapids and pool",
    10: "rapids and cython",
    11: "rapids and pool and cython",
    12: "rapids and dask",
    13: "rapids and dask and pool",
    14: "rapids and dask and cython",
    15: "rapids and dask and pool and cython",
}
LOCAL_ONLY_MODES = tuple(range(0, 4)) + tuple(range(8, 12))
CLUSTER_MODES = tuple(range(4, 8)) + tuple(range(12, 16))


@dataclass(frozen=True)
class NodeInfo:
    label: str
    hostname: str
    os_name: str
    has_nvidia_smi: bool


def _parse_runtime(run_output: Any) -> tuple[str, float]:
    if not isinstance(run_output, str):
        raise TypeError(f"Expected a timing string, got {type(run_output)!r}")
    parts = run_output.strip().split()
    if len(parts) < 2:
        raise ValueError(f"Unexpected AGILAB timing output: {run_output!r}")
    return parts[0], float(parts[1])


def _run_shell(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return proc.stdout.strip()


def _probe_local_node() -> NodeInfo:
    hostname = _run_shell(["hostname"])
    os_name = _run_shell(["uname", "-sm"])
    has_nvidia_smi = subprocess.run(
        ["zsh", "-lc", "command -v nvidia-smi >/dev/null 2>&1"],
        check=False,
    ).returncode == 0
    return NodeInfo(
        label="local-macos-node",
        hostname=hostname,
        os_name=os_name,
        has_nvidia_smi=has_nvidia_smi,
    )


def _probe_remote_node(host: str) -> NodeInfo:
    cmd = (
        "printf '%s\\n' \"$(hostname)\" \"$(uname -sm)\";"
        " if command -v nvidia-smi >/dev/null 2>&1; then echo yes; else echo no; fi"
    )
    output = _run_shell(
        ["ssh", "-o", "BatchMode=yes", f"agi@{host}", cmd]
    ).splitlines()
    if len(output) < 3:
        raise RuntimeError(f"Unexpected remote probe output from {host!r}: {output!r}")
    hostname, os_name, has_gpu = output[:3]
    return NodeInfo(
        label="remote-macos-node",
        hostname=hostname.strip(),
        os_name=os_name.strip(),
        has_nvidia_smi=(has_gpu.strip() == "yes"),
    )


def _sync_dataset_to_remote(data_in: Path, remote_host: str) -> None:
    parent_cmd = f"mkdir -p {shlex.quote(str(data_in.parent))}"
    subprocess.run(
        ["ssh", "-o", "BatchMode=yes", f"agi@{remote_host}", parent_cmd],
        check=True,
    )
    subprocess.run(
        ["rsync", "-az", "--delete", f"{data_in}/", f"{remote_host}:{data_in}/"],
        check=True,
    )


def _prepare_output_root(local_output_root: Path, remote_host: str | None) -> None:
    if local_output_root.exists():
        subprocess.run(["rm", "-rf", str(local_output_root)], check=True)
    local_output_root.mkdir(parents=True, exist_ok=True)
    if remote_host:
        remote_cmd = (
            f"rm -rf {shlex.quote(str(local_output_root))}"
            f" && mkdir -p {shlex.quote(str(local_output_root))}"
        )
        subprocess.run(
            ["ssh", "-o", "BatchMode=yes", f"agi@{remote_host}", remote_cmd],
            check=True,
        )


def _mode_note(mode: int, local_node: NodeInfo, remote_node: NodeInfo | None) -> str:
    if mode < 8:
        if mode in CLUSTER_MODES:
            return "1 local macOS worker + 1 remote macOS worker over SSH."
        return "Local-only execution path."

    gpu_nodes = [node.label for node in (local_node, remote_node) if node and node.has_nvidia_smi]
    if gpu_nodes:
        return "RAPIDS bit requested and NVIDIA tooling detected."
    if mode in CLUSTER_MODES:
        return (
            "RAPIDS bit requested, but neither macOS node exposes NVIDIA tooling; "
            "this remains a CPU-only run over the 2-node SSH/Dask topology."
        )
    return (
        "RAPIDS bit requested, but the local macOS node exposes no NVIDIA tooling; "
        "this remains a CPU-only local run."
    )


def _topology_label(mode: int) -> str:
    if mode in CLUSTER_MODES:
        return "2-node cluster (1 local + 1 remote macOS worker)"
    return "local only"


def _reset_agi_dask_state() -> None:
    """Avoid leaking a disconnected Dask client between benchmark phases."""
    AGI._dask_client = None
    AGI._dask_workers = []
    AGI._service_workers = []


async def _build_args(
    app_name: str,
    rows_per_file: int,
    compute_passes: int,
    n_partitions: int,
) -> tuple[AgiEnv, dict[str, Any], dict[str, Any]]:
    env = AgiEnv(apps_path=APPS_PATH, app=app_name, verbose=0)
    manager_cls, _, config = _load_classes(env, app_name)
    manager = manager_cls.from_toml(
        env,
        settings_path=env.app_settings_file,
        rows_per_file=rows_per_file,
        compute_passes=compute_passes,
        n_partitions=n_partitions,
        nfile=n_partitions,
        reset_target=True,
    )
    args = manager.args.model_dump(mode="json")
    output_root = env.resolve_share_path(
        Path("execution_playground") / "mode_matrix" / app_name / "results"
    )
    args["data_out"] = str(output_root)
    return env, args, config


async def _install_for_matrix(
    env: AgiEnv,
    scheduler_host: str,
    workers: dict[str, int],
    args: dict[str, Any],
) -> None:
    _reset_agi_dask_state()
    await AGI.install(
        env=env,
        scheduler=scheduler_host,
        workers=workers,
        modes_enabled=15,
        verbose=0,
        **args,
    )


async def _run_mode_samples(
    env: AgiEnv,
    args: dict[str, Any],
    mode: int,
    repeats: int,
    scheduler_host: str,
    cluster_workers: dict[str, int],
    remote_host: str | None,
    local_output_root: Path,
) -> dict[str, Any]:
    samples: list[float] = []
    mode_codes: list[str] = []
    cluster_mode = mode in CLUSTER_MODES
    rapids_enabled = mode >= 8

    for _ in range(repeats):
        if not cluster_mode:
            _reset_agi_dask_state()
        _prepare_output_root(local_output_root, remote_host if cluster_mode else None)
        if cluster_mode:
            run_output = await AGI.run(
                env=env,
                scheduler=scheduler_host,
                workers=cluster_workers,
                mode=mode,
                rapids_enabled=rapids_enabled,
                **args,
            )
        else:
            run_output = await AGI.run(
                env=env,
                mode=mode,
                rapids_enabled=rapids_enabled,
                **args,
            )
        mode_code, seconds = _parse_runtime(run_output)
        mode_codes.append(mode_code)
        samples.append(seconds)

    return {
        "mode_code": statistics.mode(mode_codes),
        "samples_seconds": samples,
        "median_seconds": statistics.median(samples),
        "min_seconds": min(samples),
        "max_seconds": max(samples),
    }


async def run_mode_matrix(
    remote_host: str,
    scheduler_host: str,
    rows_per_file: int,
    compute_passes: int,
    n_partitions: int,
    repeats: int,
) -> dict[str, Any]:
    local_node = _probe_local_node()
    remote_node = _probe_remote_node(remote_host)
    cluster_workers = {"127.0.0.1": 1, remote_host: 1}

    results: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "rows_per_file": rows_per_file,
            "compute_passes": compute_passes,
            "n_partitions": n_partitions,
            "repeats": repeats,
            "scheduler_host": local_node.label,
            "remote_worker_host": remote_node.label,
            "topology": "1 local macOS scheduler/worker + 1 remote macOS worker over SSH",
            "nodes": {
                "local": {
                    "label": local_node.label,
                    "hostname": local_node.hostname,
                    "os": local_node.os_name,
                    "nvidia_smi": local_node.has_nvidia_smi,
                },
                "remote": {
                    "label": remote_node.label,
                    "hostname": remote_node.hostname,
                    "os": remote_node.os_name,
                    "nvidia_smi": remote_node.has_nvidia_smi,
                },
            },
        },
        "apps": {},
    }

    for app_name in APPS:
        env, args, config = await _build_args(
            app_name=app_name,
            rows_per_file=rows_per_file,
            compute_passes=compute_passes,
            n_partitions=n_partitions,
        )
        data_in = Path(str(args["data_in"]))
        output_root = Path(str(args["data_out"]))
        _sync_dataset_to_remote(data_in, remote_host)
        _prepare_output_root(output_root, remote_host)
        await _install_for_matrix(env, scheduler_host, cluster_workers, args)

        app_results: dict[str, Any] = {
            "engine": config["engine"],
            "execution_model": config["execution_model"],
            "modes": {},
        }
        for mode in range(16):
            sample_result = await _run_mode_samples(
                env=env,
                args=args,
                mode=mode,
                repeats=repeats,
                scheduler_host=scheduler_host,
                cluster_workers=cluster_workers,
                remote_host=remote_host,
                local_output_root=output_root,
            )
            app_results["modes"][str(mode)] = {
                "label": MODE_NAMES[mode],
                "topology": _topology_label(mode),
                "rapids_requested": mode >= 8,
                "gpu_accelerated": bool(mode >= 8 and local_node.has_nvidia_smi and remote_node.has_nvidia_smi),
                "note": _mode_note(mode, local_node, remote_node),
                **sample_result,
            }
        results["apps"][app_name] = app_results

    return results


def _rows_for_csv(results: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for app_name, app_data in results["apps"].items():
        for mode_str, mode_data in app_data["modes"].items():
            rows.append(
                {
                    "app": app_name,
                    "engine": app_data["engine"],
                    "execution_model": app_data["execution_model"],
                    "mode": int(mode_str),
                    "label": mode_data["label"],
                    "mode_code": mode_data["mode_code"],
                    "topology": mode_data["topology"],
                    "median_seconds": f"{mode_data['median_seconds']:.3f}",
                    "min_seconds": f"{mode_data['min_seconds']:.3f}",
                    "max_seconds": f"{mode_data['max_seconds']:.3f}",
                    "rapids_requested": str(mode_data["rapids_requested"]).lower(),
                    "gpu_accelerated": str(mode_data["gpu_accelerated"]).lower(),
                    "note": mode_data["note"],
                }
            )
    return rows


def _markdown_table(results: dict[str, Any], app_name: str) -> str:
    app = results["apps"][app_name]
    lines = [
        "| Mode | Label | Code | Topology | Median (s) | Note |",
        "| ---: | --- | --- | --- | ---: | --- |",
    ]
    for mode in range(16):
        data = app["modes"][str(mode)]
        lines.append(
            "| {mode} | {label} | `{mode_code}` | {topology} | {seconds:.3f} | {note} |".format(
                mode=mode,
                label=data["label"],
                mode_code=data["mode_code"],
                topology=data["topology"],
                seconds=data["median_seconds"],
                note=data["note"],
            )
        )
    return "\n".join(lines)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "app",
                "engine",
                "execution_model",
                "mode",
                "label",
                "mode_code",
                "topology",
                "median_seconds",
                "min_seconds",
                "max_seconds",
                "rapids_requested",
                "gpu_accelerated",
                "note",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_per_app_summary_csvs(output_dir: Path, results: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for app_name, app_data in results["apps"].items():
        path = output_dir / f"{app_name}_mode_matrix.csv"
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["mode", "label", "topology", "median_seconds"],
            )
            writer.writeheader()
            for mode in range(16):
                mode_data = app_data["modes"][str(mode)]
                writer.writerow(
                    {
                        "mode": mode,
                        "label": mode_data["label"],
                        "topology": mode_data["topology"],
                        "median_seconds": f"{mode_data['median_seconds']:.3f}",
                    }
                )


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark the 16 AGILAB execution modes on a 2-node macOS setup.")
    parser.add_argument("--remote-host", required=True, help="SSH host for the second Mac worker, e.g. 192.168.3.99")
    parser.add_argument("--scheduler-host", required=True, help="Reachable IP of the local scheduler, e.g. 192.168.3.98")
    parser.add_argument("--rows-per-file", type=int, default=100_000)
    parser.add_argument("--compute-passes", type=int, default=32)
    parser.add_argument("--n-partitions", type=int, default=16)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument(
        "--json-out",
        type=Path,
        default=Path("docs/source/data/execution_mode_matrix_benchmark.json"),
    )
    parser.add_argument(
        "--csv-out",
        type=Path,
        default=Path("docs/source/data/execution_mode_matrix_benchmark.csv"),
    )
    parser.add_argument(
        "--markdown-out-dir",
        type=Path,
        default=Path("artifacts/execution_mode_matrix"),
    )
    parser.add_argument(
        "--per-app-csv-dir",
        type=Path,
        default=Path("docs/source/data"),
    )
    args = parser.parse_args()

    results = asyncio.run(
        run_mode_matrix(
            remote_host=args.remote_host,
            scheduler_host=args.scheduler_host,
            rows_per_file=args.rows_per_file,
            compute_passes=args.compute_passes,
            n_partitions=args.n_partitions,
            repeats=args.repeats,
        )
    )

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    _write_csv(args.csv_out, _rows_for_csv(results))
    _write_per_app_summary_csvs(args.per_app_csv_dir, results)

    args.markdown_out_dir.mkdir(parents=True, exist_ok=True)
    for app_name in APPS:
        (args.markdown_out_dir / f"{app_name}.md").write_text(
            _markdown_table(results, app_name) + "\n",
            encoding="utf-8",
        )

    print(f"Wrote {args.json_out}")
    print(f"Wrote {args.csv_out}")
    for app_name in APPS:
        print(f"Wrote {args.per_app_csv_dir / f'{app_name}_mode_matrix.csv'}")
    for app_name in APPS:
        print(f"Wrote {args.markdown_out_dir / f'{app_name}.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
