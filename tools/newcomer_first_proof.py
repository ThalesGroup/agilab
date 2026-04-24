#!/usr/bin/env python3
"""Run a newcomer-oriented AGILAB proof smoke with an explicit pass/fail verdict."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import textwrap
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ACTIVE_APP = REPO_ROOT / "src/agilab/apps/builtin/flight_project"
DEFAULT_MAX_SECONDS = 10 * 60
UV_RUN_PYTHON = (
    "uv",
    "--preview-features",
    "extra-build-dependencies",
    "run",
    "python",
)
IGNORED_OUTPUT_PATTERNS = (
    "missing ScriptRunContext! This warning can be ignored when running in bare mode.",
)


@dataclass(frozen=True)
class ProofCommand:
    label: str
    description: str
    argv: tuple[str, ...]
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProofStepResult:
    label: str
    description: str
    argv: list[str]
    returncode: int
    duration_seconds: float
    stdout: str
    env: dict[str, str]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the recommended AGILAB newcomer proof smoke for the built-in "
            "flight_project and print an explicit pass/fail verdict."
        )
    )
    parser.add_argument(
        "--active-app",
        default=str(DEFAULT_ACTIVE_APP),
        help="Path to the app project to validate. Defaults to the built-in flight_project.",
    )
    parser.add_argument(
        "--with-install",
        action="store_true",
        help=(
            "Also run src/agilab/apps/install.py for the selected app and verify that "
            "the seeded AGI_*.py helpers exist under ~/log/execute/<app>/."
        ),
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print the commands that would run without executing them.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=float(DEFAULT_MAX_SECONDS),
        help=(
            "KPI target for total first-proof runtime in seconds "
            f"(default: {DEFAULT_MAX_SECONDS})."
        ),
    )
    return parser


def resolve_active_app(path_value: str) -> Path:
    active_app = Path(path_value).expanduser().resolve()
    if not active_app.exists():
        raise FileNotFoundError(f"Active app path not found: {active_app}")
    if not active_app.is_dir():
        raise NotADirectoryError(f"Active app path is not a directory: {active_app}")
    pyproject = active_app / "pyproject.toml"
    if not pyproject.exists():
        raise FileNotFoundError(f"Missing pyproject.toml in app directory: {pyproject}")
    return active_app


def _preinit_smoke_command() -> ProofCommand:
    return ProofCommand(
        label="preinit smoke",
        description="Check that agi_env static helpers import and run before full initialisation.",
        argv=(*UV_RUN_PYTHON, str(REPO_ROOT / "tools" / "smoke_preinit.py")),
    )


def _ui_smoke_code(active_app: Path) -> str:
    about_page = REPO_ROOT / "src/agilab/About_agilab.py"
    orchestrate_page = REPO_ROOT / "src/agilab/pages/2_▶️ ORCHESTRATE.py"
    apps_path = active_app.parent
    return textwrap.dedent(
        f"""
        import sys
        from pathlib import Path
        from streamlit.testing.v1 import AppTest

        about_page = Path({str(about_page)!r})
        orchestrate_page = Path({str(orchestrate_page)!r})
        active_app = Path({str(active_app)!r})
        apps_path = Path({str(apps_path)!r})

        sys.argv = [about_page.name, "--active-app", str(active_app), "--apps-path", str(apps_path)]
        about = AppTest.from_file(str(about_page), default_timeout=90)
        about.run(timeout=90)
        about_errors = list(about.exception)
        if about_errors:
            raise AssertionError(f"About page exceptions: {{about_errors}}")

        if "env" not in about.session_state:
            raise AssertionError("About page did not initialise AgiEnv in session_state.")

        env = about.session_state["env"]
        orchestrate = AppTest.from_file(str(orchestrate_page), default_timeout=90)
        orchestrate.session_state["env"] = env
        orchestrate.session_state["app_settings"] = {{"args": {{}}, "cluster": {{}}}}
        orchestrate.run(timeout=90)
        orchestrate_errors = list(orchestrate.exception)
        if orchestrate_errors:
            raise AssertionError(f"ORCHESTRATE page exceptions: {{orchestrate_errors}}")

        print("newcomer-ui-smoke: OK")
        """
    ).strip()


def _ui_smoke_command(active_app: Path) -> ProofCommand:
    return ProofCommand(
        label="source ui smoke",
        description="Boot the About and ORCHESTRATE pages against the selected active app.",
        argv=(*UV_RUN_PYTHON, "-c", _ui_smoke_code(active_app)),
        env={
            "AGILAB_DISABLE_BACKGROUND_SERVICES": "1",
            "OPENAI_API_KEY": "sk-test-newcomer-proof-000000000000",
            "PYTHONUNBUFFERED": "1",
        },
    )


def _install_command(active_app: Path) -> ProofCommand:
    return ProofCommand(
        label="flight install smoke",
        description="Run the built-in app installer so newcomer helper snippets are seeded.",
        argv=(
            *UV_RUN_PYTHON,
            str(REPO_ROOT / "src/agilab/apps/install.py"),
            str(active_app),
            "--verbose",
            "1",
        ),
        env={
            "AGILAB_DISABLE_BACKGROUND_SERVICES": "1",
            "OPENAI_API_KEY": "sk-test-newcomer-proof-000000000000",
            "PYTHONUNBUFFERED": "1",
        },
    )


def _seeded_script_check_code(app_slug: str) -> str:
    required = [
        "AGI_install_flight.py",
        "AGI_run_flight.py",
    ]
    return textwrap.dedent(
        f"""
        from pathlib import Path

        execute_dir = Path.home() / "log" / "execute" / {app_slug!r}
        required = {required!r}
        missing = [name for name in required if not (execute_dir / name).exists()]
        if missing:
            raise SystemExit(
                "Missing seeded newcomer helper scripts under "
                f"{{execute_dir}}: {{', '.join(missing)}}"
            )
        print(f"seeded-scripts: OK in {{execute_dir}}")
        """
    ).strip()


def _seeded_script_command(active_app: Path) -> ProofCommand:
    app_slug = active_app.name.replace("_project", "")
    return ProofCommand(
        label="seeded script check",
        description="Verify that install.py seeded the AGI_*.py newcomer helper scripts.",
        argv=(*UV_RUN_PYTHON, "-c", _seeded_script_check_code(app_slug)),
    )


def build_proof_commands(active_app: Path, *, with_install: bool) -> list[ProofCommand]:
    commands = [
        _preinit_smoke_command(),
        _ui_smoke_command(active_app),
    ]
    if with_install:
        commands.extend([
            _install_command(active_app),
            _seeded_script_command(active_app),
        ])
    return commands


def run_command(
    command: ProofCommand,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> ProofStepResult:
    env = os.environ.copy()
    env.update(command.env)
    start = time.perf_counter()
    proc = runner(
        list(command.argv),
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    duration = time.perf_counter() - start
    stdout = proc.stdout
    if stdout:
        stdout = "\n".join(
            line
            for line in stdout.splitlines()
            if not any(pattern in line for pattern in IGNORED_OUTPUT_PATTERNS)
        ).strip()
    return ProofStepResult(
        label=command.label,
        description=command.description,
        argv=list(command.argv),
        returncode=int(proc.returncode),
        duration_seconds=duration,
        stdout=stdout,
        env=command.env,
    )


def run_proof(
    commands: Sequence[ProofCommand],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[ProofStepResult]:
    results: list[ProofStepResult] = []
    for command in commands:
        result = run_command(command, runner=runner)
        results.append(result)
        if result.returncode != 0:
            break
    return results


def summarize_kpi(
    *,
    command_count: int,
    results: Sequence[ProofStepResult],
    max_seconds: float,
) -> dict[str, object]:
    total_seconds = sum(result.duration_seconds for result in results)
    failed_step = next((result.label for result in results if result.returncode != 0), None)
    success = len(results) == command_count and failed_step is None
    return {
        "success": success,
        "passed_steps": sum(1 for result in results if result.returncode == 0),
        "expected_steps": command_count,
        "failed_step": failed_step,
        "total_duration_seconds": total_seconds,
        "target_seconds": max_seconds,
        "within_target": success and total_seconds <= max_seconds,
    }


def render_human(
    *,
    active_app: Path,
    with_install: bool,
    commands: Sequence[ProofCommand],
    results: Sequence[ProofStepResult] | None = None,
    print_only: bool = False,
    max_seconds: float = float(DEFAULT_MAX_SECONDS),
) -> str:
    lines = [
        "AGILAB newcomer first-proof smoke",
        f"active app: {active_app}",
    ]
    if print_only:
        lines.append("mode: print-only")
        lines.append(f"kpi target: <= {max_seconds:.2f}s")
        for command in commands:
            lines.append(f"- {command.label}: {command.description}")
            lines.append(f"  $ {' '.join(shlex.quote(part) for part in command.argv)}")
        return "\n".join(lines)

    results = list(results or [])
    summary = summarize_kpi(command_count=len(commands), results=results, max_seconds=max_seconds)
    success = bool(summary["success"])
    verdict = "PASS" if success else "FAIL"
    lines.append(f"verdict: {verdict}")
    lines.append(
        "kpi: "
        f"total={summary['total_duration_seconds']:.2f}s "
        f"target<={summary['target_seconds']:.2f}s "
        f"within_target={'yes' if summary['within_target'] else 'no'}"
    )
    lines.append(
        "scope: preinit import smoke + About/ORCHESTRATE page boot"
        + (" + install/seeding" if with_install else "")
    )
    for result in results:
        status = "OK" if result.returncode == 0 else f"FAIL ({result.returncode})"
        lines.append(f"- {result.label}: {status} in {result.duration_seconds:.2f}s")
    if success:
        lines.append("next:")
        lines.append(
            "  uv --preview-features extra-build-dependencies run streamlit run src/agilab/About_agilab.py"
        )
        lines.append("  then follow PROJECT -> ORCHESTRATE -> PIPELINE -> ANALYSIS with flight_project")
    else:
        lines.append("recovery:")
        lines.append("  inspect the failing step output above")
        lines.append("  if install is missing, run ./install.sh --install-apps --test-apps")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.max_seconds <= 0:
        parser.error("--max-seconds must be greater than 0")

    active_app = resolve_active_app(args.active_app)
    commands = build_proof_commands(active_app, with_install=args.with_install)

    if args.print_only:
        if args.json:
            print(
                json.dumps(
                    {
                        "active_app": str(active_app),
                        "with_install": args.with_install,
                        "kpi_target_seconds": args.max_seconds,
                        "commands": [
                            {
                                "label": command.label,
                                "description": command.description,
                                "argv": list(command.argv),
                                "env": command.env,
                            }
                            for command in commands
                        ],
                    },
                    indent=2,
                )
            )
        else:
            print(
                render_human(
                    active_app=active_app,
                    with_install=args.with_install,
                    commands=commands,
                    print_only=True,
                    max_seconds=args.max_seconds,
                )
            )
        return 0

    results = run_proof(commands)
    summary = summarize_kpi(command_count=len(commands), results=results, max_seconds=args.max_seconds)
    success = bool(summary["success"])
    if args.json:
        print(
            json.dumps(
                {
                    "active_app": str(active_app),
                    "with_install": args.with_install,
                    **summary,
                    "results": [asdict(result) for result in results],
                },
                indent=2,
            )
        )
    else:
        print(
            render_human(
                active_app=active_app,
                with_install=args.with_install,
                commands=commands,
                results=results,
                max_seconds=args.max_seconds,
            )
        )
        for result in results:
            if result.stdout.strip():
                print(f"\n[{result.label} output]\n{result.stdout.rstrip()}\n")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
