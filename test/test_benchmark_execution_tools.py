from __future__ import annotations

from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import benchmark_execution_mode_matrix as matrix
from tools import benchmark_execution_pandas_cython_kernel as cython_kernel
from tools import benchmark_execution_playground as playground


def test_benchmark_playground_apps_path_is_absolute() -> None:
    expected = (
        Path(__file__).resolve().parents[1] / "src/agilab/apps/builtin"
    ).resolve()
    assert playground.APPS_PATH == expected
    assert playground.APPS_PATH.is_absolute()


def test_cython_kernel_benchmark_uses_execution_pandas_worker_source() -> None:
    assert cython_kernel.WORKER_SOURCE.is_file()
    assert cython_kernel.WORKER_SOURCE.name == "execution_pandas_worker.py"
    assert cython_kernel.KERNEL_NAME == "_typed_numeric_score_kernel"


def test_cython_kernel_benchmark_csv_rows_report_speedup() -> None:
    results = {
        "environment": {"rows": 100},
        "runtimes": {
            "python": {
                "median_seconds": 2.0,
                "min_seconds": 2.0,
                "max_seconds": 2.0,
                "checksum": 1.0,
            },
            "cython": {
                "median_seconds": 0.5,
                "min_seconds": 0.5,
                "max_seconds": 0.5,
                "checksum": 1.0,
            },
        },
        "speedup_vs_python": 4.0,
    }

    rows = cython_kernel._rows_for_csv(results)

    assert rows[0]["runtime"] == "python"
    assert rows[0]["speedup_vs_python"] == "1.00"
    assert rows[1]["runtime"] == "cython"
    assert rows[1]["speedup_vs_python"] == "4.00"
    assert rows[1]["rows_per_second"] == "200"


def test_ssh_target_defaults_to_agi_and_preserves_explicit_user() -> None:
    assert matrix._ssh_target("192.168.20.130") == "agi@192.168.20.130"
    assert matrix._ssh_target("bench@192.168.20.130") == "bench@192.168.20.130"


def test_sync_dataset_to_remote_reuses_consistent_ssh_target(
    tmp_path, monkeypatch
) -> None:
    calls: list[list[str]] = []

    def _fake_run(cmd, check=False, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(matrix.subprocess, "run", _fake_run)

    data_in = tmp_path / "dataset"
    data_in.mkdir()
    matrix._sync_dataset_to_remote(data_in, "192.168.20.130")

    assert calls == [
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "agi@192.168.20.130",
            f"mkdir -p {data_in.parent}",
        ],
        [
            "rsync",
            "-az",
            "--delete",
            f"{data_in}/",
            f"agi@192.168.20.130:{data_in}/",
        ],
    ]


def test_gpu_accelerated_respects_local_and_cluster_topologies() -> None:
    local_gpu = matrix.NodeInfo("local", "l", "macOS", True)
    local_cpu = matrix.NodeInfo("local", "l", "macOS", False)
    remote_gpu = matrix.NodeInfo("remote", "r", "macOS", True)
    remote_cpu = matrix.NodeInfo("remote", "r", "macOS", False)

    assert matrix._gpu_accelerated(8, local_gpu, remote_cpu) is True
    assert matrix._gpu_accelerated(8, local_cpu, remote_gpu) is False
    assert matrix._gpu_accelerated(12, local_gpu, remote_cpu) is True
    assert matrix._gpu_accelerated(12, local_cpu, remote_gpu) is True
    assert matrix._gpu_accelerated(12, local_cpu, remote_cpu) is False
