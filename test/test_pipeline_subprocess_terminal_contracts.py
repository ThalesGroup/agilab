"""Real subprocess regressions for workflow failure and deadline propagation."""

from pathlib import Path
import re
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from agilab.pipeline.pipeline_runtime_execution_support import stream_run_command


def _run(
    tmp_path: Path, source: str, *, timeout=None, push=None, launch=subprocess.Popen
):
    return stream_run_command(
        SimpleNamespace(apps_path=None),
        "terminal-contract",
        [sys.executable, "-c", source],
        tmp_path,
        push_run_log=push or (lambda *_args: None),
        ansi_escape_re=re.compile(r"\x1b\[[0-9;]*m"),
        jump_exception_cls=RuntimeError,
        timeout=timeout,
        popen_factory=launch,
    )


@pytest.mark.parametrize(
    "prefix,expected", [("", ""), ("print('before failure'); ", "before failure")]
)
def test_real_nonzero_exit_propagates_with_or_without_stdout(
    tmp_path, prefix, expected
):
    with pytest.raises(subprocess.CalledProcessError) as failure:
        _run(tmp_path, prefix + "import sys; sys.exit(9)")
    assert failure.value.returncode == 9
    assert failure.value.output == expected


@pytest.mark.parametrize(
    "prefix",
    ["", "print('begin', flush=True); ", "print('partial', end='', flush=True); "],
)
def test_deadline_covers_a_pipe_that_remains_open(tmp_path, prefix):
    processes = []
    messages = []

    def launch(*args, **kwargs):
        child = subprocess.Popen(*args, **kwargs)
        processes.append(child)
        return child

    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        _run(
            tmp_path,
            "import time; " + prefix + "time.sleep(5)",
            timeout=0.1,
            push=lambda _page, message, _placeholder: messages.append(message),
            launch=launch,
        )

    assert time.monotonic() - started < 2
    assert processes[0].poll() is not None, "The owned child must be reaped"
    assert any("timed out" in message for message in messages)


def test_log_failure_stops_owned_child_and_preserves_original_exception(tmp_path):
    processes = []

    def launch(*args, **kwargs):
        child = subprocess.Popen(*args, **kwargs)
        processes.append(child)
        return child

    def failed_log(*_args):
        raise ValueError("log sink unavailable")

    with pytest.raises(ValueError, match="log sink unavailable"):
        _run(
            tmp_path,
            "import time; print('begin', flush=True); time.sleep(5)",
            push=failed_log,
            launch=launch,
        )

    assert processes[0].poll() is not None


def test_success_streams_output_and_returns_only_after_zero_exit(tmp_path):
    messages = []
    output = _run(
        tmp_path,
        "print('success')",
        push=lambda _page, message, _placeholder: messages.append(message),
    )
    assert output == "success"
    assert messages == ["success"]


def test_timeout_logging_failure_preserves_deadline_and_reaps_child(tmp_path):
    processes = []

    def launch(*args, **kwargs):
        child = subprocess.Popen(*args, **kwargs)
        processes.append(child)
        return child

    def failed_log(*_args):
        raise RuntimeError("log sink unavailable")

    with pytest.raises(subprocess.TimeoutExpired) as failure:
        _run(
            tmp_path,
            "import time; time.sleep(5)",
            timeout=0.1,
            push=failed_log,
            launch=launch,
        )

    assert processes[0].poll() is not None
    assert any("failure logging failed" in note for note in failure.value.__notes__)
