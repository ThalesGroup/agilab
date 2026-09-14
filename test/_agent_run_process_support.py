"""Importable spawn target independent of pytest's collected package name."""

from pathlib import Path
import sys


def agent_run_process(output_dir: str, start, results) -> None:
    source = str(Path(__file__).resolve().parents[1] / "src")
    if source not in sys.path:
        sys.path.insert(0, source)
    from agilab.agent_runtime.agent_run import trace_agent_run

    start.wait(timeout=10)
    try:
        result = trace_agent_run(
            [sys.executable, "-c", "import time; time.sleep(0.2)"],
            agent="codex",
            label="Concurrent claim",
            cwd=Path(__file__).resolve().parents[1],
            output_dir=Path(output_dir),
            run_id="same-run",
            permission_level="standard",
        )
    except BaseException as exc:
        results.put(("error", type(exc).__name__, str(exc)))
    else:
        results.put(("ok", result.returncode, ""))
