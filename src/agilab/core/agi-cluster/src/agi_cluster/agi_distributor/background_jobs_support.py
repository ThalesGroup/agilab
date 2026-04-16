import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Protocol, cast

_NORMALIZE_CWD_EXCEPTIONS = (OSError, RuntimeError, TypeError)


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

    def new(self, cmd: str, cwd: str | Path | None = None) -> BackgroundProcessJob:
        proc = cast(
            _ProcessLike,
            subprocess.Popen(
                cmd,
                shell=True,
                cwd=self._normalize_cwd(cwd),
                start_new_session=True,
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


bg = SimpleNamespace(BackgroundJobManager=BackgroundProcessManager)
