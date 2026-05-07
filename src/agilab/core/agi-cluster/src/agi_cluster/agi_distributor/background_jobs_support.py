import os
import shlex
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping, Protocol, Sequence, cast

_NORMALIZE_CWD_EXCEPTIONS = (OSError, RuntimeError, TypeError)
_SHELL_METACHARS = frozenset(";&|<>\n\r`$")


class _ProcessLike(Protocol):
    def poll(self) -> int | None:
        ...


class BackgroundProcessJob:
    """Minimal job record for detached subprocess launches."""

    def __init__(self, process: _ProcessLike):
        self.process = process
        self.result = process
        self.num: int | None = None


class BackgroundProcessManager:
    """Host-neutral replacement for IPython BackgroundJobManager."""

    def __init__(self) -> None:
        self._current_job_id = 0
        self.all: dict[int, BackgroundProcessJob] = {}
        self.running: list[BackgroundProcessJob] = []
        self.completed: list[BackgroundProcessJob] = []
        self.dead: list[BackgroundProcessJob] = []

    @staticmethod
    def _normalize_cwd(cwd: str | Path | None) -> str | None:
        if cwd in (None, ""):
            return None
        try:
            candidate = Path(cast(str | Path, cwd)).expanduser()
        except _NORMALIZE_CWD_EXCEPTIONS:
            return None
        return str(candidate) if candidate.is_dir() else None

    def _refresh(self) -> None:
        active: list[BackgroundProcessJob] = []
        for job in self.running:
            status = job.process.poll()
            if status is None:
                active.append(job)
            elif status == 0:
                self.completed.append(job)
            else:
                self.dead.append(job)
        self.running = active

    @staticmethod
    def _command_argv(cmd: str | Sequence[str]) -> list[str]:
        if isinstance(cmd, str):
            if any(char in cmd for char in _SHELL_METACHARS):
                raise ValueError(f"Shell metacharacters are not allowed in background command: {cmd!r}")
            argv = shlex.split(cmd, posix=os.name != "nt")
        else:
            argv = [str(part) for part in cmd]
        if not argv:
            raise ValueError("Background command must not be empty")
        return argv

    def new(
        self,
        cmd: str | Sequence[str],
        cwd: str | Path | None = None,
        *,
        env: Mapping[str, str] | None = None,
    ) -> BackgroundProcessJob:
        process_env = os.environ.copy()
        if env:
            process_env.update({str(key): str(value) for key, value in env.items() if value is not None})
        proc = cast(
            _ProcessLike,
            subprocess.Popen(
                self._command_argv(cmd),
                shell=False,
                cwd=self._normalize_cwd(cwd),
                start_new_session=True,
                env=process_env,
            ),
        )
        job = BackgroundProcessJob(proc)
        job.num = self._current_job_id
        self._current_job_id += 1
        self.running.append(job)
        self.all[job.num] = job
        return job

    def result(self, num: int) -> _ProcessLike | None:
        self._refresh()
        job = self.all.get(num)
        if job is None:
            return None
        if job in self.dead:
            return None
        return job.result

    def flush(self) -> None:
        self._refresh()
        for job in self.completed + self.dead:
            if job.num is not None:
                self.all.pop(job.num, None)
        self.completed.clear()
        self.dead.clear()


def background_env_from_prefixes(
    *prefixes: str,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Translate simple shell-style env prefixes into a subprocess env mapping."""
    process_env = dict(base_env or os.environ)
    for prefix in prefixes:
        for segment in str(prefix or "").split(";"):
            segment = segment.strip()
            if not segment:
                continue
            if segment.startswith("export "):
                segment = segment[len("export "):].strip()
            for token in shlex.split(segment, posix=os.name != "nt"):
                if "=" not in token:
                    continue
                key, value = token.split("=", 1)
                if not key.isidentifier():
                    continue
                process_env[key] = os.path.expandvars(os.path.expanduser(value))
    return process_env


bg = SimpleNamespace(BackgroundJobManager=BackgroundProcessManager)
