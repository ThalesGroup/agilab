"""Packaged first-proof command for AGILAB adoption."""

from __future__ import annotations

import argparse
from importlib import metadata as importlib_metadata
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from agilab import run_manifest


PACKAGE_ROOT = Path(__file__).resolve().parent
FIRST_PROOF_PROJECT = "flight_telemetry_project"
FIRST_PROOF_APP_DISTRIBUTION = "agi-app-flight-telemetry"
FIRST_PROOF_PATH_ID = "source-checkout-first-proof"
DEFAULT_MAX_SECONDS = 10 * 60
IGNORED_OUTPUT_PATTERNS = (
    "missing ScriptRunContext! This warning can be ignored when running in bare mode.",
)
RUNTIME_DISTRIBUTIONS = (
    "agilab",
    "agi-core",
    "agi-env",
    "agi-node",
    "agi-cluster",
    "agi-gui",
    "agi-apps",
    "agi-pages",
    "agi-app-mission-decision",
    FIRST_PROOF_APP_DISTRIBUTION,
    "agi-app-weather-forecast",
    "agi-app-uav-relay-queue",
)
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
DIAGNOSTIC_TAIL_LINES = 20


@dataclass(frozen=True)
class ProofCommand:
    label: str
    description: str
    argv: tuple[str, ...]
    env: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 180.0


@dataclass(frozen=True)
class ProofStepResult:
    label: str
    description: str
    argv: list[str]
    returncode: int
    duration_seconds: float
    stdout: str
    env: dict[str, str]


def _detect_repo_root(start: Path = PACKAGE_ROOT) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "agilab").is_dir():
            return candidate
    return None


def _runtime_root() -> Path:
    return _detect_repo_root() or PACKAGE_ROOT


def _agilab_package_marker_root() -> Path:
    repo_root = _detect_repo_root()
    if repo_root is not None:
        source_package = repo_root / "src" / "agilab"
        if source_package.is_dir():
            return source_package.resolve()
    return PACKAGE_ROOT.resolve()


def _agilab_path_marker() -> Path:
    return Path.home() / ".local" / "share" / "agilab" / ".agilab-path"


def _distribution_version(distribution: str) -> str | None:
    try:
        return importlib_metadata.version(distribution)
    except importlib_metadata.PackageNotFoundError:
        return None


def runtime_identity() -> dict[str, object]:
    """Return the installed runtime that this proof actually validates."""
    launcher = shutil.which("agilab")
    return {
        "python_executable": sys.executable,
        "package_root": str(PACKAGE_ROOT),
        "runtime_root": str(_runtime_root()),
        "launcher_path": launcher,
        "distributions": {
            distribution: _distribution_version(distribution)
            for distribution in RUNTIME_DISTRIBUTIONS
        },
    }


def write_agilab_path_marker() -> Path:
    marker_path = _agilab_path_marker()
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(f"{_agilab_package_marker_root()}\n", encoding="utf-8")
    return marker_path


def _resolve_installed_first_proof_project() -> Path | None:
    """Return the PyPI app-payload project when it is installed."""

    try:
        from agi_env.app_provider_registry import resolve_installed_app_project
    except Exception:
        return None

    try:
        project = resolve_installed_app_project(FIRST_PROOF_PROJECT)
    except Exception:
        return None
    if project is None:
        return None

    try:
        candidate = Path(project).expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    return candidate if (candidate / "pyproject.toml").is_file() else None


def default_active_app() -> Path:
    candidates: list[Path] = []
    repo_root = _detect_repo_root()
    if repo_root is not None:
        candidates.append(repo_root / "src" / "agilab" / "apps" / "builtin" / FIRST_PROOF_PROJECT)
    candidates.append(PACKAGE_ROOT / "apps" / "builtin" / FIRST_PROOF_PROJECT)
    installed_project = _resolve_installed_first_proof_project()
    if installed_project is not None:
        candidates.append(installed_project)
    for candidate in candidates:
        if (candidate / "pyproject.toml").is_file():
            return candidate.resolve()
    return candidates[-1].resolve()


def default_core_smoke_target() -> Path:
    """Return an existing path for core-only dry-run evidence."""

    return _runtime_root().resolve()


def resolve_active_app(path_value: str | None) -> Path:
    active_app = Path(path_value).expanduser().resolve() if path_value else default_active_app()
    if not active_app.exists():
        if path_value is None:
            raise FileNotFoundError(
                "Default first-proof app not found: "
                f"{active_app}. Install the public app payload with "
                f"`python -m pip install {FIRST_PROOF_APP_DISTRIBUTION}` "
                'or `python -m pip install "agilab[examples]"`, then rerun this command. '
                "Alternatively pass --active-app /path/to/<app>_project."
            )
        raise FileNotFoundError(f"Active app path not found: {active_app}")
    if not active_app.is_dir():
        raise NotADirectoryError(f"Active app path is not a directory: {active_app}")
    pyproject = active_app / "pyproject.toml"
    if not pyproject.exists():
        raise FileNotFoundError(f"Missing pyproject.toml in app directory: {pyproject}")
    return active_app


def default_output_dir(active_app: Path) -> Path:
    log_root = Path(os.environ.get("AGILAB_LOG_ABS", str(Path.home() / "log"))).expanduser()
    app_slug = active_app.name.replace("_project", "")
    return log_root / "execute" / app_slug


def default_manifest_path(active_app: Path) -> Path:
    return run_manifest.run_manifest_path(default_output_dir(active_app))


def resolve_manifest_path(active_app: Path, manifest_out: str | None) -> Path:
    if manifest_out:
        return Path(manifest_out).expanduser()
    return default_manifest_path(active_app)


def _apps_path_for_active_app(active_app: Path) -> Path:
    if active_app.parent.name == "builtin":
        return active_app.parent
    return active_app.parent


def _preinit_smoke_code(active_app: Path) -> str:
    return textwrap.dedent(
        f"""
        from pathlib import Path
        import importlib.metadata as md

        import agilab
        import agi_env
        import agi_node
        import agi_cluster
        from agi_cluster.agi_distributor import AGI, RunRequest, StageRequest

        active_app = Path({str(active_app)!r})
        if not (active_app / "pyproject.toml").is_file():
            raise SystemExit(f"missing active app pyproject: {{active_app}}")

        print("agilab", md.version("agilab"))
        print("agi-node", md.version("agi-node"))
        print("agi-cluster-api", AGI.__name__, RunRequest.__name__, StageRequest.__name__)
        print("active-app", active_app)
        """
    ).strip()


def _preinit_smoke_command(active_app: Path) -> ProofCommand:
    return ProofCommand(
        label="package preinit smoke",
        description="Import AGILAB packages and verify the active app path.",
        argv=(sys.executable, "-c", _preinit_smoke_code(active_app)),
    )


def _core_smoke_code() -> str:
    return textwrap.dedent(
        """
        import importlib.metadata as md

        import agilab
        import agi_env
        import agi_node
        import agi_cluster
        from agi_cluster.agi_distributor import AGI, RunRequest, StageRequest

        print("agilab", md.version("agilab"))
        print("agi-node", md.version("agi-node"))
        print("agi-cluster-api", AGI.__name__, RunRequest.__name__, StageRequest.__name__)
        print("core-smoke", "ok")
        """
    ).strip()


def _core_smoke_command() -> ProofCommand:
    return ProofCommand(
        label="package preinit smoke",
        description="Import AGILAB core packages without requiring packaged app or page assets.",
        argv=(sys.executable, "-c", _core_smoke_code()),
    )


def _ui_smoke_code(active_app: Path) -> str:
    about_page = PACKAGE_ROOT / "main_page.py"
    orchestrate_page = PACKAGE_ROOT / "pages" / "2_ORCHESTRATE.py"
    apps_path = _apps_path_for_active_app(active_app)
    return textwrap.dedent(
        f"""
        import sys
        from pathlib import Path
        from streamlit.testing.v1 import AppTest

        about_page = Path({str(about_page)!r})
        orchestrate_page = Path({str(orchestrate_page)!r})
        active_app = Path({str(active_app)!r})
        apps_path = Path({str(apps_path)!r})

        if not about_page.is_file():
            raise AssertionError(f"Main page not found: {{about_page}}")
        if not orchestrate_page.is_file():
            raise AssertionError(f"ORCHESTRATE page not found: {{orchestrate_page}}")

        sys.argv = [about_page.name, "--active-app", str(active_app), "--apps-path", str(apps_path)]
        about = AppTest.from_file(str(about_page), default_timeout=90)
        about.run(timeout=90)
        about_errors = list(about.exception)
        if about_errors:
            raise AssertionError(f"Main page exceptions: {{about_errors}}")

        if "env" not in about.session_state:
            raise AssertionError("Main page did not initialise AgiEnv in session_state.")

        env = about.session_state["env"]
        orchestrate = AppTest.from_file(str(orchestrate_page), default_timeout=90)
        orchestrate.session_state["env"] = env
        orchestrate.session_state["app_settings"] = {{"args": {{}}, "cluster": {{}}}}
        orchestrate.run(timeout=90)
        orchestrate_errors = list(orchestrate.exception)
        if orchestrate_errors:
            raise AssertionError(f"ORCHESTRATE page exceptions: {{orchestrate_errors}}")

        print("agilab-first-proof-ui-smoke: OK")
        """
    ).strip()


def _ui_smoke_command(active_app: Path) -> ProofCommand:
    return ProofCommand(
        label="package ui smoke",
        description="Boot the packaged main page and ORCHESTRATE page against the active app.",
        argv=(sys.executable, "-c", _ui_smoke_code(active_app)),
        env={
            "AGILAB_DISABLE_BACKGROUND_SERVICES": "1",
            "OPENAI_API_KEY": "sk-test-first-proof-000000000000",
            "PYTHONUNBUFFERED": "1",
        },
        timeout_seconds=240.0,
    )


def _install_command(active_app: Path) -> ProofCommand:
    install_script = PACKAGE_ROOT / "apps" / "install.py"
    return ProofCommand(
        label="flight install smoke",
        description="Run the packaged app installer so AGI_*.py helper snippets are seeded.",
        argv=(sys.executable, str(install_script), str(active_app), "--verbose", "1"),
        env={
            "AGILAB_DISABLE_BACKGROUND_SERVICES": "1",
            "OPENAI_API_KEY": "sk-test-first-proof-000000000000",
            "PYTHONUNBUFFERED": "1",
        },
        timeout_seconds=240.0,
    )


def _seeded_script_check_code(active_app: Path) -> str:
    app_slug = active_app.name.replace("_project", "")
    required = ["AGI_install_flight_telemetry.py", "AGI_run_flight_telemetry.py"]
    return textwrap.dedent(
        f"""
        from pathlib import Path

        execute_dir = Path.home() / "log" / "execute" / {app_slug!r}
        required = {required!r}
        missing = [name for name in required if not (execute_dir / name).exists()]
        if missing:
            raise SystemExit(
                "Missing seeded first-proof helper scripts under "
                f"{{execute_dir}}: {{', '.join(missing)}}"
            )
        print(f"seeded-scripts: OK in {{execute_dir}}")
        """
    ).strip()


def _seeded_script_command(active_app: Path) -> ProofCommand:
    return ProofCommand(
        label="seeded script check",
        description="Verify that the installer seeded the first-proof helper scripts.",
        argv=(sys.executable, "-c", _seeded_script_check_code(active_app)),
    )


def build_proof_commands(active_app: Path, *, with_install: bool, with_ui: bool = False) -> list[ProofCommand]:
    commands = [_preinit_smoke_command(active_app)]
    if with_ui:
        commands.append(_ui_smoke_command(active_app))
    if with_install:
        commands.extend([_install_command(active_app), _seeded_script_command(active_app)])
    return commands


def run_command(
    command: ProofCommand,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> ProofStepResult:
    env = os.environ.copy()
    env.update(command.env)
    start = time.perf_counter()
    try:
        proc = runner(
            list(command.argv),
            cwd=str(Path.cwd()),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=command.timeout_seconds,
            check=False,
        )
        returncode = int(proc.returncode)
        stdout = proc.stdout or ""
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        output = exc.stdout or ""
        stdout = output if isinstance(output, str) else output.decode("utf-8", "replace")
        stdout = (stdout + f"\nTimed out after {command.timeout_seconds:.0f}s").strip()
    duration = time.perf_counter() - start
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
        returncode=returncode,
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


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def _display_argv(argv: Sequence[str]) -> list[str]:
    display = list(argv)
    for index, value in enumerate(display[:-1]):
        if value == "-c":
            display[index + 1] = "<inline first-proof smoke>"
            break
    return display


def _step_payload(result: ProofStepResult) -> dict[str, object]:
    payload: dict[str, object] = {
        "label": result.label,
        "description": result.description,
        "status": "pass" if result.returncode == 0 else "fail",
        "returncode": result.returncode,
        "duration_seconds": result.duration_seconds,
        "command": _display_argv(result.argv),
        "env_overrides_count": len(result.env),
    }
    if result.returncode != 0 and result.stdout.strip():
        lines = _strip_ansi(result.stdout).splitlines()
        payload["diagnostic_tail"] = lines[-DIAGNOSTIC_TAIL_LINES:]
    return payload


def _command_payload(command: ProofCommand) -> dict[str, object]:
    return {
        "label": command.label,
        "description": command.description,
        "command": _display_argv(command.argv),
        "env_overrides_count": len(command.env),
        "timeout_seconds": command.timeout_seconds,
    }


def _manifest_summary_payload(manifest: run_manifest.RunManifest, manifest_path: Path) -> dict[str, object]:
    return {
        "path": str(manifest_path),
        "run_id": manifest.run_id,
        "path_id": manifest.path_id,
        "label": manifest.label,
        "status": manifest.status,
        "duration_seconds": manifest.timing.duration_seconds,
        "target_seconds": manifest.timing.target_seconds,
        "artifact_count": len(manifest.artifacts),
        "validation_statuses": {
            validation.label: validation.status
            for validation in manifest.validations
        },
    }


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


def _collect_existing_artifacts(output_dir: Path, manifest_path: Path) -> list[run_manifest.RunManifestArtifact]:
    artifacts = [
        run_manifest.RunManifestArtifact(
            name="run_manifest",
            path=str(manifest_path.expanduser()),
            kind="manifest",
            exists=True,
        )
    ]
    if not output_dir.exists():
        return artifacts
    for child in sorted(output_dir.iterdir(), key=lambda item: item.name):
        if child.name.startswith(".") or child == manifest_path:
            continue
        if child.is_file() and child.suffix == ".py" and child.name.startswith("AGI_"):
            continue
        artifacts.append(run_manifest.RunManifestArtifact.from_path(child))
    return artifacts


def _executed_argv(
    *,
    active_app: Path,
    dry_run: bool,
    with_install: bool,
    with_ui: bool,
    max_seconds: float,
    manifest_path: Path,
) -> tuple[str, ...]:
    argv: tuple[str, ...] = ("agilab", "first-proof", "--json")
    if dry_run:
        argv = (*argv, "--dry-run")
    default_target = default_core_smoke_target() if dry_run else default_active_app()
    if active_app.resolve() != default_target.resolve():
        argv = (*argv, "--active-app", str(active_app))
    if with_install:
        argv = (*argv, "--with-install")
    if with_ui:
        argv = (*argv, "--with-ui")
    if max_seconds != float(DEFAULT_MAX_SECONDS):
        argv = (*argv, "--max-seconds", str(max_seconds))
    if manifest_path.expanduser() != default_manifest_path(active_app).expanduser():
        argv = (*argv, "--manifest-out", str(manifest_path.expanduser()))
    return argv


def build_run_manifest(
    *,
    active_app: Path,
    dry_run: bool,
    with_install: bool,
    with_ui: bool,
    commands: Sequence[ProofCommand],
    results: Sequence[ProofStepResult],
    summary: dict[str, object],
    max_seconds: float,
    manifest_path: Path,
) -> run_manifest.RunManifest:
    failed_step = summary.get("failed_step")
    identity = runtime_identity()
    recommended_project = dry_run or active_app.name == FIRST_PROOF_PROJECT
    validations = [
        run_manifest.RunManifestValidation(
            label="proof_steps",
            status="pass" if bool(summary.get("success")) else "fail",
            summary=(
                "all first-proof steps passed"
                if bool(summary.get("success"))
                else f"proof stopped at {failed_step or 'an incomplete step'}"
            ),
            details={
                "passed_steps": summary.get("passed_steps"),
                "expected_steps": summary.get("expected_steps"),
                "command_labels": [command.label for command in commands],
                "result_labels": [result.label for result in results],
                "runtime_identity": identity,
            },
        ),
        run_manifest.RunManifestValidation(
            label="target_seconds",
            status="pass" if bool(summary.get("within_target")) else "fail",
            summary=(
                f"proof completed within {max_seconds:.2f}s target"
                if bool(summary.get("within_target"))
                else f"proof exceeded or did not complete within {max_seconds:.2f}s target"
            ),
            details={
                "total_duration_seconds": summary.get("total_duration_seconds"),
                "target_seconds": max_seconds,
            },
        ),
        run_manifest.RunManifestValidation(
            label="recommended_project",
            status="pass" if recommended_project else "fail",
            summary=(
                "core-only dry-run does not require a public app payload"
                if dry_run
                else (
                    "active app is the recommended public flight_telemetry_project"
                    if recommended_project
                    else f"active app is {active_app.name}; recommended public app is {FIRST_PROOF_PROJECT}"
                )
            ),
            details={"active_app": str(active_app), "app_name": active_app.name, "dry_run": dry_run},
        ),
    ]
    status = "pass" if all(validation.status == "pass" for validation in validations) else "fail"
    output_dir = manifest_path.expanduser().parent
    return run_manifest.build_run_manifest(
        path_id=FIRST_PROOF_PATH_ID,
        label="AGILAB first-proof",
        status=status,
        command=run_manifest.RunManifestCommand(
            label="agilab first-proof",
            argv=_executed_argv(
                active_app=active_app,
                dry_run=dry_run,
                with_install=with_install,
                with_ui=with_ui,
                max_seconds=max_seconds,
                manifest_path=manifest_path,
            ),
            cwd=str(Path.cwd()),
            env_overrides={
                "AGILAB_DISABLE_BACKGROUND_SERVICES": "1",
            },
        ),
        environment=run_manifest.RunManifestEnvironment.from_paths(
            repo_root=_runtime_root(),
            active_app=active_app,
        ),
        timing=run_manifest.RunManifestTiming(
            started_at=run_manifest.utc_now(),
            finished_at=run_manifest.utc_now(),
            duration_seconds=float(summary.get("total_duration_seconds", 0.0)),
            target_seconds=max_seconds,
        ),
        artifacts=_collect_existing_artifacts(output_dir, manifest_path),
        validations=validations,
    )


def render_human(
    *,
    active_app: Path,
    dry_run: bool = False,
    with_install: bool,
    with_ui: bool,
    commands: Sequence[ProofCommand],
    results: Sequence[ProofStepResult] | None = None,
    print_only: bool = False,
    max_seconds: float = float(DEFAULT_MAX_SECONDS),
) -> str:
    lines = [
        "AGILAB first proof",
    ]
    if dry_run and active_app.resolve() == default_core_smoke_target().resolve():
        lines.append("active app: not required (core smoke only)")
    else:
        lines.append(f"active app: {active_app}")
    identity = runtime_identity()
    distributions = dict(identity.get("distributions", {}))
    agilab_version = distributions.get("agilab") or "unknown"
    lines.append(f"agilab version: {agilab_version}")
    lines.append(f"python: {identity.get('python_executable')}")
    if identity.get("launcher_path"):
        lines.append(f"launcher: {identity.get('launcher_path')}")
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
    lines.append(f"verdict: {'PASS' if success else 'FAIL'}")
    lines.append(
        "kpi: "
        f"total={summary['total_duration_seconds']:.2f}s "
        f"target<={summary['target_seconds']:.2f}s "
        f"within_target={'yes' if summary['within_target'] else 'no'}"
    )
    if dry_run:
        lines.append("mode: dry-run (core smoke only)")
    lines.append(
        "scope: package/core API smoke"
        + (" + main/ORCHESTRATE page boot" if with_ui else "")
        + (" + install/seeding" if with_install else "")
    )
    for result in results:
        status = "OK" if result.returncode == 0 else f"FAIL ({result.returncode})"
        lines.append(f"- {result.label}: {status} in {result.duration_seconds:.2f}s")
    if success:
        lines.append("next:")
        lines.append("  run `agilab`")
        lines.append("  then follow PROJECT -> ORCHESTRATE -> ANALYSIS with flight_telemetry_project")
    else:
        lines.append("recovery:")
        lines.append("  inspect the failing step output above")
        lines.append(
            "  rerun with `agilab first-proof --json` when you need a support bundle input"
        )
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the fastest AGILAB first-proof smoke and write run_manifest.json."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run only lightweight checks (no install or UI execution).",
    )
    parser.add_argument(
        "--active-app",
        default=None,
        help="Path to the app project to validate. Defaults to the packaged built-in flight_telemetry_project.",
    )
    parser.add_argument(
        "--with-install",
        action="store_true",
        help="Also run the packaged app installer and verify seeded AGI_*.py helper scripts.",
    )
    parser.add_argument(
        "--with-ui",
        action="store_true",
        help="Also boot the packaged main page and ORCHESTRATE page. Requires the `agilab[ui]` install profile.",
    )
    parser.add_argument("--print-only", action="store_true", help="Print commands without executing them.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=float(DEFAULT_MAX_SECONDS),
        help=f"KPI target for total first-proof runtime in seconds (default: {DEFAULT_MAX_SECONDS}).",
    )
    parser.add_argument(
        "--manifest-out",
        default=None,
        help="Path for run_manifest.json. Defaults to ~/log/execute/<app>/run_manifest.json.",
    )
    parser.add_argument("--no-manifest", action="store_true", help="Do not write run_manifest.json.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.max_seconds <= 0:
        parser.error("--max-seconds must be greater than 0")
    if args.dry_run and (args.with_install or args.with_ui):
        parser.error("--dry-run cannot be combined with --with-install or --with-ui")

    with_install = False if args.dry_run else args.with_install
    with_ui = False if args.dry_run else args.with_ui

    core_only_dry_run = args.dry_run and args.active_app is None
    active_app = default_core_smoke_target() if core_only_dry_run else resolve_active_app(args.active_app)
    commands = [_core_smoke_command()] if core_only_dry_run else build_proof_commands(
        active_app,
        with_install=with_install,
        with_ui=with_ui,
    )
    manifest_path = resolve_manifest_path(active_app, args.manifest_out)

    if args.print_only:
        identity = runtime_identity()
        if args.json:
            print(
                json.dumps(
                    {
                        "active_app": str(active_app),
                        "with_install": with_install,
                        "with_ui": with_ui,
                        "dry_run": args.dry_run,
                        "kpi_target_seconds": args.max_seconds,
                        "agilab_version": dict(identity.get("distributions", {})).get("agilab"),
                        "runtime_identity": identity,
                        "run_manifest_path": str(manifest_path),
                        "run_manifest_filename": run_manifest.RUN_MANIFEST_FILENAME,
                        "commands": [_command_payload(command) for command in commands],
                    },
                    indent=2,
                )
            )
        else:
            print(
                render_human(
                    active_app=active_app,
                    dry_run=args.dry_run,
                    with_install=with_install,
                    with_ui=with_ui,
                    commands=commands,
                    print_only=True,
                    max_seconds=args.max_seconds,
                )
            )
        return 0

    results = run_proof(commands)
    summary = summarize_kpi(command_count=len(commands), results=results, max_seconds=args.max_seconds)
    success = bool(summary["success"])
    marker_path = write_agilab_path_marker() if success else None
    manifest = None
    if not args.no_manifest:
        manifest = build_run_manifest(
            active_app=active_app,
            dry_run=args.dry_run,
            with_install=with_install,
            with_ui=with_ui,
            commands=commands,
            results=results,
            summary=summary,
            max_seconds=args.max_seconds,
            manifest_path=manifest_path,
        )
        run_manifest.write_run_manifest(manifest, manifest_path)

    if args.json:
        identity = runtime_identity()
        payload = {
            "active_app": str(active_app),
            "with_install": with_install,
            "with_ui": with_ui,
            "dry_run": args.dry_run,
            "agilab_version": dict(identity.get("distributions", {})).get("agilab"),
            "runtime_identity": identity,
            **summary,
            "steps": [_step_payload(result) for result in results],
        }
        if manifest is not None:
            payload["run_manifest_path"] = str(manifest_path)
            payload["run_manifest_summary"] = _manifest_summary_payload(manifest, manifest_path)
        if marker_path is not None:
            payload["agilab_path_marker"] = str(marker_path)
        print(json.dumps(payload, indent=2))
    else:
        print(
            render_human(
                active_app=active_app,
                dry_run=args.dry_run,
                with_install=with_install,
                with_ui=with_ui,
                commands=commands,
                results=results,
                max_seconds=args.max_seconds,
            )
        )
        if manifest is not None:
            print(f"\nrun manifest: {manifest_path}")
        for result in results:
            if result.stdout.strip():
                print(f"\n[{result.label} output]\n{result.stdout.rstrip()}\n")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
