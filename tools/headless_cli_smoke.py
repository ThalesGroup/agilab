"""Headless AGILAB CLI smoke checks.

The default source-mode check blocks Streamlit imports and verifies that the
public headless command surface remains importable. Package mode creates an
isolated virtual environment, installs a package spec or wheel, and checks the
console scripts without installing UI extras.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import venv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence


HEADLESS_MODULES = (
    "agilab",
    "agilab.lab_run",
    "agilab.first_proof_cli",
    "agilab.adoption_report",
    "agilab.bridge_cli",
    "agilab_mcp.server",
)
HELP_COMMANDS = (
    ("agilab", "--help"),
    ("agilab", "first-proof", "--help"),
    ("agilab", "adoption-report", "--help"),
    ("agilab-mcp", "serve", "--once"),
)


@dataclass(frozen=True)
class SmokeResult:
    label: str
    command: list[str]
    returncode: int
    stdout_tail: str
    stderr_tail: str

    @property
    def passed(self) -> bool:
        return self.returncode == 0


def _tail(text: str, *, limit: int = 1200) -> str:
    return text[-limit:]


def _run(
    command: Sequence[str],
    *,
    label: str,
    timeout: float,
    env: dict[str, str] | None = None,
) -> SmokeResult:
    completed = subprocess.run(
        list(command),
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
        env=env,
    )
    return SmokeResult(
        label=label,
        command=list(command),
        returncode=completed.returncode,
        stdout_tail=_tail(completed.stdout),
        stderr_tail=_tail(completed.stderr),
    )


def streamlit_blocked_probe_script() -> str:
    modules = ", ".join(repr(module) for module in HEADLESS_MODULES)
    return textwrap.dedent(
        f"""
        import builtins
        import contextlib
        import importlib
        import io

        real_import = builtins.__import__

        def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "streamlit" or name.startswith("streamlit."):
                raise ModuleNotFoundError("blocked streamlit", name="streamlit")
            return real_import(name, globals, locals, fromlist, level)

        builtins.__import__ = blocked_import

        for module_name in ({modules},):
            importlib.import_module(module_name)

        from agilab import lab_run

        lab_run._guard_against_uvx_in_source_tree = lambda: None

        for argv in (
            ["--help"],
            ["first-proof", "--help"],
            ["adoption-report", "--help"],
        ):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                try:
                    code = lab_run.main(list(argv))
                except SystemExit as exc:
                    code = exc.code
            if code not in (0, None):
                raise SystemExit(f"help path failed for {{argv}}: {{code}}")

        print("headless source import/help smoke: ok")
        """
    ).strip()


def package_import_probe_script() -> str:
    modules = ", ".join(repr(module) for module in HEADLESS_MODULES)
    return textwrap.dedent(
        f"""
        import importlib
        import importlib.util

        if importlib.util.find_spec("streamlit") is not None:
            raise SystemExit("streamlit should not be installed in the minimal package smoke")

        for module_name in ({modules},):
            importlib.import_module(module_name)

        print("headless package import smoke: ok")
        """
    ).strip()


def run_source_smoke(*, python: str, timeout: float) -> list[SmokeResult]:
    return [
        _run(
            [python, "-c", streamlit_blocked_probe_script()],
            label="source blocked-streamlit import/help",
            timeout=timeout,
        )
    ]


def _venv_paths(venv_dir: Path) -> tuple[Path, Path]:
    if os.name == "nt":
        scripts_dir = venv_dir / "Scripts"
        return scripts_dir / "python.exe", scripts_dir
    scripts_dir = venv_dir / "bin"
    return scripts_dir / "python", scripts_dir


def _create_package_venv(
    venv_dir: Path, *, timeout: float, env: dict[str, str]
) -> tuple[Path, Path, list[SmokeResult], bool]:
    uv = shutil.which("uv")
    if uv:
        create_result = _run(
            [uv, "venv", "--python", sys.executable, str(venv_dir)],
            label="create uv venv",
            timeout=timeout,
            env=env,
        )
        python, scripts_dir = _venv_paths(venv_dir)
        return python, scripts_dir, [create_result], True

    venv.EnvBuilder(with_pip=True).create(venv_dir)
    python, scripts_dir = _venv_paths(venv_dir)
    return python, scripts_dir, [], False


def run_package_smoke(*, package_spec: str, timeout: float) -> list[SmokeResult]:
    with tempfile.TemporaryDirectory(prefix="agilab-headless-smoke-") as tmp:
        venv_dir = Path(tmp) / "venv"
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.pop("VIRTUAL_ENV", None)
        python, scripts_dir, results, created_with_uv = _create_package_venv(
            venv_dir, timeout=timeout, env=env
        )
        if created_with_uv:
            uv = shutil.which("uv")
            assert uv is not None
            results.append(
                _run(
                    [uv, "pip", "install", "--python", str(python), package_spec],
                    label=f"install {package_spec}",
                    timeout=timeout,
                    env=env,
                )
            )
        else:
            results.extend(
                (
                    _run(
                        [str(python), "-m", "pip", "install", "--upgrade", "pip"],
                        label="upgrade pip",
                        timeout=timeout,
                        env=env,
                    ),
                    _run(
                        [str(python), "-m", "pip", "install", package_spec],
                        label=f"install {package_spec}",
                        timeout=timeout,
                        env=env,
                    ),
                )
            )
        results.append(
            _run(
                [str(python), "-c", package_import_probe_script()],
                label="package no-streamlit import",
                timeout=timeout,
                env=env,
            )
        )
        results.extend(
            _run(
                [str(scripts_dir / command[0]), *command[1:]],
                label=" ".join(command),
                timeout=timeout,
                env=env,
            )
            for command in HELP_COMMANDS
        )
        return results


def _emit_results(results: Sequence[SmokeResult], *, json_output: bool) -> None:
    payload = {
        "status": "pass" if all(result.passed for result in results) else "fail",
        "results": [asdict(result) | {"passed": result.passed} for result in results],
    }
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"{status} {result.label}: {' '.join(result.command)}")
        if not result.passed:
            if result.stdout_tail:
                print(result.stdout_tail)
            if result.stderr_tail:
                print(result.stderr_tail, file=sys.stderr)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify AGILAB headless CLI imports and command help paths."
    )
    parser.add_argument(
        "--package-spec",
        help="Install this package spec or wheel into a temporary venv before checking console scripts.",
    )
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.package_spec:
        results = run_package_smoke(package_spec=args.package_spec, timeout=args.timeout)
    else:
        results = run_source_smoke(python=args.python, timeout=args.timeout)
    _emit_results(results, json_output=args.json)
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
