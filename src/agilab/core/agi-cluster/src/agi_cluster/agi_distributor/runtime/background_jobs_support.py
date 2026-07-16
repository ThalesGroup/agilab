import os
import secrets
import shlex
import subprocess
import time
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Mapping, Protocol, Sequence, cast

_NORMALIZE_CWD_EXCEPTIONS = (OSError, RuntimeError, TypeError)
_SHELL_METACHARS = frozenset(";&|<>\n\r`$")
BACKGROUND_JOB_TOKEN_ENV = "AGILAB_BACKGROUND_JOB_TOKEN"


class _ProcessLike(Protocol):
    def poll(self) -> int | None:
        ...


class BackgroundProcessJob:
    """Minimal job record for detached subprocess launches."""

    def __init__(
        self,
        process: _ProcessLike,
        *,
        ownership_token: str | None = None,
        process_group_id: int | None = None,
        ownership_started_at: float | None = None,
    ) -> None:
        self.process = process
        self.result = process
        self.num: int | None = None
        self.ownership_token = ownership_token
        self.process_group_id = process_group_id
        self.ownership_started_at = ownership_started_at


class BackgroundProcessManager:
    """Host-neutral replacement for IPython BackgroundJobManager."""

    def __init__(self) -> None:
        self._current_job_id = 0
        self.all: dict[int, BackgroundProcessJob] = {}
        self.running: list[BackgroundProcessJob] = []
        self.completed: list[BackgroundProcessJob] = []
        self.dead: list[BackgroundProcessJob] = []
        # Keep launch ownership independently from transient execution state.
        # A wrapper may exit while a descendant in its process group survives.
        self.owned: list[BackgroundProcessJob] = []

    @staticmethod
    def _normalize_cwd(cwd: str | Path | None) -> str | None:
        if cwd in (None, ""):
            return None
        try:
            candidate = Path(cast(str | Path, cwd)).expanduser()  # ty: ignore[redundant-cast]
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
        ownership_token = secrets.token_hex(16)
        ownership_started_at = time.time()
        process_env[BACKGROUND_JOB_TOKEN_ENV] = ownership_token
        process_group_options: dict[str, object]
        if os.name == "nt":
            process_group_options = {
                "creationflags": int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            }
        else:
            process_group_options = {"start_new_session": True}
        proc = cast(
            _ProcessLike,
            subprocess.Popen(
                self._command_argv(cmd),
                shell=False,
                cwd=self._normalize_cwd(cwd),
                env=process_env,
                **process_group_options,
            ),
        )
        process_group_id = None
        if os.name != "nt":
            process_pid = getattr(proc, "pid", None)
            if isinstance(process_pid, int) and process_pid > 0:
                process_group_id = process_pid
        job = BackgroundProcessJob(
            proc,
            ownership_token=ownership_token,
            process_group_id=process_group_id,
            ownership_started_at=ownership_started_at,
        )
        job.num = self._current_job_id
        self._current_job_id += 1
        self.running.append(job)
        self.owned.append(job)
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

    def _expand_value(key: str, value: str) -> str:
        if key != "PATH":
            return os.path.expandvars(os.path.expanduser(value))
        expanded_parts: list[str] = []
        for raw_part in str(value).split(":"):
            part = raw_part.strip()
            if not part:
                continue
            if part in {"$PATH", "${PATH}"}:
                expanded_parts.extend(
                    item for item in process_env.get("PATH", "").split(os.pathsep) if item
                )
                continue
            if part.startswith("$HOME/"):
                home = process_env.get("HOME") or os.environ.get("HOME") or str(Path.home())
                suffix = part[len("$HOME/") :]
                expanded_parts.append(str(Path(home) / Path(*PurePosixPath(suffix).parts)))
                continue
            expanded_parts.append(os.path.expandvars(os.path.expanduser(part)))
        return os.pathsep.join(expanded_parts)

    for prefix in prefixes:
        for segment in str(prefix or "").split(";"):
            segment = segment.strip()
            if not segment:
                continue
            if segment.startswith("export "):
                segment = segment[len("export "):].strip()
            for token in shlex.split(segment, posix=True):
                if "=" not in token:
                    continue
                key, value = token.split("=", 1)
                if not key.isidentifier():
                    continue
                process_env[key] = _expand_value(key, value)
    return process_env


bg = SimpleNamespace(BackgroundJobManager=BackgroundProcessManager)
