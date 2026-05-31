# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
# 3. Neither the name of Jean-Pierre Morard nor the names of its contributors, or THALES SIX GTS France SAS, may be used to endorse or promote products derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import argparse
import importlib.util
import os
import subprocess
import sys
import tomllib
import webbrowser
from importlib import metadata as importlib_metadata
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

try:  # Prefer package import when AGILAB is importable as a normal package.
    from agilab.import_guard import import_agilab_module
except ModuleNotFoundError:
    from import_guard import import_agilab_module

_PACKAGE_DIR = Path(__file__).resolve().parent
_STREAMLIT_THEME_ENV_MODULE = import_agilab_module(
    "agilab.streamlit_theme_env",
    current_file=__file__,
    fallback_path=_PACKAGE_DIR / "streamlit_theme_env.py",
    fallback_name="agilab_streamlit_theme_env_local",
)
apply_streamlit_theme_environment = (
    _STREAMLIT_THEME_ENV_MODULE.apply_streamlit_theme_environment
)
packaged_streamlit_config_path = (
    _STREAMLIT_THEME_ENV_MODULE.packaged_streamlit_config_path
)

UI_EXTRA_HINT = "Install the UI profile with `python -m pip install 'agilab[ui]'`."
PYTORCH_PLAYGROUND_HF_SPACE = "jpmorard/agilab"
PYTORCH_PLAYGROUND_APP_NAME = "pytorch_playground_project"
_PUBLIC_BIND_GUARD_MODULE = import_agilab_module(
    "agilab.ui_public_bind_guard",
    current_file=__file__,
    fallback_path=_PACKAGE_DIR / "ui_public_bind_guard.py",
    fallback_name="agilab_ui_public_bind_guard_local",
)
PublicBindPolicyError = _PUBLIC_BIND_GUARD_MODULE.PublicBindPolicyError
enforce_public_bind_policy = _PUBLIC_BIND_GUARD_MODULE.enforce_public_bind_policy
_APP_SURFACE_MODULE = import_agilab_module(
    "agilab.app_surface",
    current_file=__file__,
    fallback_path=_PACKAGE_DIR / "app_surface.py",
    fallback_name="agilab_app_surface_local",
)


def _streamlit_config_path() -> Path:
    return packaged_streamlit_config_path(__file__)


def _ensure_streamlit_config_file(environ=os.environ) -> None:
    apply_streamlit_theme_environment(_streamlit_config_path(), environ=environ)


def _detect_repo_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (
            candidate / "src" / "agilab"
        ).is_dir():
            return candidate
    return None


def _running_from_uvx() -> bool:
    """Detect uvx or other uv tool environments that should not touch the source tree."""
    # `uv run` sets this; honour it so developers keep their standard workflow.
    if os.environ.get("UV_RUN_RECURSION_DEPTH"):
        return False

    prefix = Path(sys.prefix).resolve()
    uv_roots = [
        Path.home() / ".cache" / "uv",
        Path.home() / ".local" / "share" / "uv",
    ]
    return any(root == prefix or root in prefix.parents for root in uv_roots)


def _guard_against_uvx_in_source_tree() -> None:
    repo_root = _detect_repo_root(Path.cwd())
    if repo_root and _running_from_uvx():
        message = (
            "agilab: running inside the source checkout via `uvx` is not supported.\n"
            f"Current checkout: {repo_root}\n"
            "Use `uv run agilab` or the generated run-config wrappers instead."
        )
        raise SystemExit(message)


def _resolve_apps_path(cli_value: str | None) -> str | None:
    """Return the CLI provided apps dir, or the repo apps dir when running from source."""
    if cli_value:
        return cli_value

    repo_root = _detect_repo_root(Path(__file__).resolve().parent)
    if not repo_root:
        return None

    candidate = repo_root / "src" / "agilab" / "apps"
    return str(candidate) if candidate.is_dir() else None


def _read_version_from_pyproject(repo_root: Path) -> str | None:
    pyproject_path = repo_root / "pyproject.toml"
    if not pyproject_path.is_file():
        return None

    try:
        project = tomllib.loads(pyproject_path.read_text(encoding="utf-8")).get(
            "project", {}
        )
    except Exception:
        return None

    version = str(project.get("version") or "").strip()
    return version or None


def _detect_cli_version() -> str:
    repo_root = _detect_repo_root(Path(__file__).resolve().parent)
    if repo_root:
        version = _read_version_from_pyproject(repo_root)
        if version:
            return version

    try:
        return importlib_metadata.version("agilab")
    except importlib_metadata.PackageNotFoundError:
        return ""


def _run_doctor(argv: list[str]) -> int:
    from agilab import cluster_flight_validation

    return cluster_flight_validation.main(argv)


def _run_first_proof(argv: list[str]) -> int:
    from agilab import first_proof_cli

    return first_proof_cli.main(argv)


def _run_agent_run(argv: list[str]) -> int:
    from agilab import agent_run

    return agent_run.main(argv)


def _run_security_check(argv: list[str]) -> int:
    from agilab import security_check

    return security_check.main(argv)


def _run_adoption_report(argv: list[str]) -> int:
    from agilab import adoption_report

    return adoption_report.main(argv)


def _run_storyboard(argv: list[str]) -> int:
    from agilab import run_storyboard

    return run_storyboard.main(argv)


def _run_promotion_dossier(argv: list[str]) -> int:
    from agilab import promotion_dossier

    return promotion_dossier.main(argv)


def _run_evidence_contract(argv: list[str]) -> int:
    from agilab import evidence_contract

    return evidence_contract.main(argv)


def _run_workflow(argv: list[str]) -> int:
    from agilab import workflow_validation

    return workflow_validation.main(argv)


def _run_env(argv: list[str]) -> int:
    if argv[:1] == ["footprint"]:
        from agilab import env_footprint

        return env_footprint.main(argv[1:])

    raise SystemExit("agilab env: supported commands: footprint")


def _run_app(argv: list[str]) -> int:
    if argv[:1] == ["surface"]:
        return _run_app_surface(argv[1:])

    from agilab import pypi_app_packages

    return pypi_app_packages.main(argv)


def _run_kubernetes_job(argv: list[str]) -> int:
    from agilab import kubernetes_job

    return kubernetes_job.main(argv)


def _run_bridge(argv: list[str]) -> int:
    from agilab import bridge_cli

    return bridge_cli.main(argv)


def _pytorch_playground_project_root() -> Path:
    try:
        from agi_app_pytorch_playground import project_root
    except ModuleNotFoundError:
        project_root = None

    if project_root is not None:
        candidate = Path(project_root())
        if candidate.exists():
            return candidate

    source_candidate = _PACKAGE_DIR / "apps" / "builtin" / PYTORCH_PLAYGROUND_APP_NAME
    if source_candidate.exists():
        return source_candidate

    raise SystemExit(
        "agilab pytorch-playground: app package not found. "
        "Install the UI/apps profile with `python -m pip install 'agilab[ui]'` "
        "on Python >= 3.12, or install `agi-app-pytorch-playground`."
    )


def _pytorch_playground_script_path(project_root: Path) -> Path:
    script = project_root / "src" / "pytorch_playground" / "playground_ui.py"
    if not script.is_file():
        raise SystemExit(f"agilab pytorch-playground: Streamlit surface not found: {script}")
    return script


def _validate_streamlit_host(host: str | None) -> str:
    if not host:
        return enforce_public_bind_policy()
    env = os.environ.copy()
    env["AGILAB_UI_HOST"] = host
    return enforce_public_bind_policy(env)


def _url_with_active_app_query(url: str, app_name: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.setdefault("active_app", app_name)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _url_with_pytorch_playground_query(url: str) -> str:
    return _url_with_active_app_query(url, PYTORCH_PLAYGROUND_APP_NAME)


def _hf_runtime_url(space_id: str) -> str:
    if space_id.startswith(("http://", "https://")):
        return _url_with_pytorch_playground_query(space_id)
    return _url_with_pytorch_playground_query(_hf_space_runtime_url(space_id))


def _hf_space_runtime_url(space_id: str) -> str:
    if space_id.startswith(("http://", "https://")):
        return space_id
    if "/" not in space_id:
        raise SystemExit("--hf-space must look like <owner>/<space>.")
    owner, name = space_id.split("/", 1)
    return f"https://{owner.lower().replace('_', '-')}-{name.lower().replace('_', '-')}.hf.space/"


def _pytorch_playground_hf_url(hf_url: str | None, hf_space: str | None) -> str:
    explicit = hf_url or os.environ.get("AGILAB_PYTORCH_PLAYGROUND_HF_URL")
    if explicit:
        return _url_with_pytorch_playground_query(explicit)
    space = hf_space or os.environ.get("AGILAB_HF_SPACE") or PYTORCH_PLAYGROUND_HF_SPACE
    return _hf_runtime_url(space)


def _pytorch_playground_streamlit_command(
    *,
    project_root: Path,
    script_path: Path,
    host: str,
    port: int,
    headless: bool,
    extra_args: list[str],
) -> list[str]:
    command = [
        "uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "--project",
        str(project_root),
        "streamlit",
        "run",
        "--server.address",
        host,
        "--server.port",
        str(port),
    ]
    if headless:
        command.extend(["--server.headless", "true"])
    command.append(str(script_path))
    if extra_args:
        command.append("--")
        command.extend(extra_args)
    return command


def _resolve_app_surface_project_root(project: str) -> Path:
    candidate = Path(project).expanduser()
    if candidate.exists():
        return candidate.resolve()

    repo_root = _detect_repo_root(_PACKAGE_DIR)
    if repo_root is not None:
        for root in (
            repo_root / "src" / "agilab" / "apps" / "builtin",
            repo_root / "src" / "agilab" / "apps",
        ):
            path = root / project
            if path.exists():
                return path.resolve()

    try:
        from agilab import pypi_app_packages
    except Exception:
        pypi_app_packages = None

    if pypi_app_packages is not None:
        for app in pypi_app_packages.list_installed_pypi_apps():
            if app.provider == project or Path(app.project_root).name == project:
                return Path(app.project_root).expanduser().resolve()

    raise SystemExit(f"agilab app surface: project not found: {project}")


def _app_surface_streamlit_command(
    *,
    project_root: Path,
    entrypoint: Path,
    host: str,
    port: int,
    headless: bool,
    extra_args: list[str],
) -> list[str]:
    command = [
        "uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "--project",
        str(project_root),
        "streamlit",
        "run",
        "--server.address",
        host,
        "--server.port",
        str(port),
    ]
    if headless:
        command.extend(["--server.headless", "true"])
    command.extend([str(entrypoint), "--", "--active-app", str(project_root)])
    command.extend(extra_args)
    return command


def _run_app_surface(argv: list[str], *, runner=subprocess.call) -> int:
    parser = argparse.ArgumentParser(
        prog="agilab app surface",
        description="Launch an app-owned UI surface without coupling apps to one web framework.",
    )
    parser.add_argument("project", help="App project name or path.")
    parser.add_argument(
        "--ui",
        default=None,
        help="Surface name or backend. Examples: streamlit, hf, nicegui.",
    )
    parser.add_argument("--list", action="store_true", help="List declared surfaces.")
    parser.add_argument("--json", action="store_true", help="Emit JSON for --list.")
    parser.add_argument(
        "--host",
        default=None,
        help="Local UI host. Streamlit uses AGILAB's guarded localhost bind by default.",
    )
    parser.add_argument("--port", type=int, default=8501, help="Local UI port.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open external URLs.")
    parser.add_argument("--hf-url", default=None, help="Explicit hosted backend URL.")
    parser.add_argument("--hf-space", default=None, help="Hosted Space ID, for example owner/agilab.")
    args, extra_args = parser.parse_known_args(argv)
    if extra_args[:1] == ["--"]:
        extra_args = extra_args[1:]

    project_root = _resolve_app_surface_project_root(args.project)
    specs = _APP_SURFACE_MODULE.app_surface_specs(project_root)
    if args.list:
        payload = [spec.as_dict() for spec in specs.values()]
        if args.json:
            import json

            print(json.dumps({"project": project_root.name, "surfaces": payload}, indent=2))
        else:
            for spec in payload:
                default = " default" if spec.get("default") else ""
                print(f"{spec['name']}\t{spec['backend']}{default}\t{spec['title']}")
        return 0
    if not specs:
        raise SystemExit(f"agilab app surface: no app surface declared in {project_root}")

    selected = _APP_SURFACE_MODULE.select_app_surface_spec(project_root, name=args.ui)
    if selected is None:
        available = ", ".join(sorted(specs)) or "<none>"
        raise SystemExit(
            f"agilab app surface: unknown --ui {args.ui!r}; available: {available}"
        )

    if selected.backend in {"hf", "url"}:
        url = (
            args.hf_url
            or (_hf_space_runtime_url(args.hf_space) if args.hf_space else "")
            or selected.url
        )
        if not url:
            raise SystemExit(f"agilab app surface: surface {selected.name!r} has no URL.")
        url = _url_with_active_app_query(url, project_root.name)
        print(url)
        if not args.no_browser:
            webbrowser.open(url)
        return 0

    if selected.backend != "streamlit":
        raise SystemExit(
            f"agilab app surface: backend {selected.backend!r} is declared but "
            "does not have a built-in launcher yet."
        )

    try:
        host = _validate_streamlit_host(args.host)
    except PublicBindPolicyError as exc:
        raise SystemExit(f"agilab app surface: {exc}") from exc
    entrypoint = _APP_SURFACE_MODULE.resolve_app_surface_entrypoint(
        project_root, selected.entrypoint
    )
    if entrypoint is None:
        raise SystemExit(
            f"agilab app surface: Streamlit entrypoint not found for {selected.name!r}."
        )
    _ensure_streamlit_config_file()
    command = _app_surface_streamlit_command(
        project_root=project_root,
        entrypoint=entrypoint,
        host=host,
        port=args.port,
        headless=args.no_browser,
        extra_args=extra_args,
    )
    return int(runner(command))


def _run_pytorch_playground(argv: list[str], *, runner=subprocess.call) -> int:
    parser = argparse.ArgumentParser(
        prog="agilab pytorch-playground",
        description="Launch the standalone PyTorch Playground locally or open its Hugging Face Space backend.",
    )
    parser.add_argument(
        "--backend",
        choices=("local", "hf"),
        default=os.environ.get("AGILAB_PYTORCH_PLAYGROUND_BACKEND", "local"),
        help="Launch locally through the app uv environment, or open the Hugging Face Space backend.",
    )
    parser.add_argument("--host", default=None, help="Local Streamlit host. Defaults to AGILAB's guarded localhost bind.")
    parser.add_argument("--port", type=int, default=8501, help="Local Streamlit port.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser for local or HF launch.")
    parser.add_argument("--hf-url", default=None, help="Explicit Hugging Face runtime URL.")
    parser.add_argument("--hf-space", default=None, help="Hugging Face Space ID, for example owner/agilab.")
    args, extra_args = parser.parse_known_args(argv)
    if extra_args[:1] == ["--"]:
        extra_args = extra_args[1:]

    if args.backend == "hf":
        url = _pytorch_playground_hf_url(args.hf_url, args.hf_space)
        print(url)
        if not args.no_browser:
            webbrowser.open(url)
        return 0

    try:
        host = _validate_streamlit_host(args.host)
    except PublicBindPolicyError as exc:
        raise SystemExit(f"agilab pytorch-playground: {exc}") from exc

    project_root = _pytorch_playground_project_root()
    script_path = _pytorch_playground_script_path(project_root)
    _ensure_streamlit_config_file()
    command = _pytorch_playground_streamlit_command(
        project_root=project_root,
        script_path=script_path,
        host=host,
        port=args.port,
        headless=args.no_browser,
        extra_args=extra_args,
    )
    return int(runner(command))


def _missing_ui_dependencies() -> list[str]:
    missing: list[str] = []
    for module_name, distribution_name in (
        ("streamlit", "streamlit"),
        ("agi_gui", "agi-gui"),
        ("agilab.apps", "agi-apps"),
    ):
        if importlib.util.find_spec(module_name) is None:
            missing.append(distribution_name)
    return missing


def _load_streamlit_cli():
    missing = _missing_ui_dependencies()
    if missing:
        raise SystemExit(
            "agilab: the Streamlit UI dependencies are not installed. "
            f"Missing: {', '.join(missing)}. {UI_EXTRA_HINT}"
        )
    try:
        import streamlit.web.cli as stcli
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "agilab: unable to import Streamlit UI runtime. "
            f"{UI_EXTRA_HINT}\nOriginal error: {exc}"
        ) from exc
    return stcli


def main(argv: list[str] | None = None) -> int:
    _guard_against_uvx_in_source_tree()
    raw_argv = list(sys.argv[1:] if argv is None else argv)

    if raw_argv[:1] == ["doctor"]:
        return _run_doctor(raw_argv[1:])
    if raw_argv[:1] in (["first-proof"], ["first_proof"]):
        return _run_first_proof(raw_argv[1:])
    if raw_argv[:1] in (["agent-run"], ["agent_run"]):
        return _run_agent_run(raw_argv[1:])
    if raw_argv[:1] == ["dry-run"]:
        return _run_first_proof(["--dry-run", *raw_argv[1:]])
    if raw_argv[:1] in (["security-check"], ["security_check"]):
        return _run_security_check(raw_argv[1:])
    if raw_argv[:1] in (["adoption-report"], ["adoption_report"]):
        return _run_adoption_report(raw_argv[1:])
    if raw_argv[:1] in (["story"], ["storyboard"], ["run-story"], ["run_story"]):
        return _run_storyboard(raw_argv[1:])
    if raw_argv[:1] in (
        ["dossier"],
        ["promotion-dossier"],
        ["promotion_dossier"],
    ):
        return _run_promotion_dossier(raw_argv[1:])
    if raw_argv[:1] in (
        ["prove"],
        ["verify"],
        ["sign"],
        ["replay"],
        ["export-lineage"],
        ["export_lineage"],
        ["export-traces"],
        ["export_traces"],
        ["policy-check"],
        ["policy_check"],
        ["cards"],
        ["metadata-store"],
        ["metadata_store"],
    ):
        command = raw_argv[0].replace("_", "-")
        return _run_evidence_contract([command, *raw_argv[1:]])
    if raw_argv[:1] == ["workflow"]:
        return _run_workflow(raw_argv[1:])
    if raw_argv[:1] == ["env"]:
        return _run_env(raw_argv[1:])
    if raw_argv[:1] == ["app"]:
        return _run_app(raw_argv[1:])
    if raw_argv[:1] in (
        ["kubernetes-job"],
        ["kubernetes_job"],
        ["k8s-job"],
        ["k8s_job"],
    ):
        return _run_kubernetes_job(raw_argv[1:])
    if raw_argv[:1] in (["export"], ["run"], ["init"], ["import"], ["mcp"]):
        return _run_bridge(raw_argv)
    if raw_argv[:1] in (["pytorch-playground"], ["pytorch_playground"]):
        return _run_pytorch_playground(raw_argv[1:])

    parser = argparse.ArgumentParser(
        description="Run AGILAB application with custom options."
    )
    parser.add_argument(
        "--apps-path",
        type=str,
        help="Where you store your apps (default is ./)",
        default=None,
    )
    parser.add_argument(
        "-V",
        "--version",
        action="store_true",
        help="Show the AGILAB version and exit.",
    )

    # Parse known arguments; extra arguments are captured in `unknown`
    args, unknown = parser.parse_known_args(raw_argv)

    if args.version:
        version = _detect_cli_version()
        print(f"agilab {version}" if version else "agilab version unavailable")
        return 0

    try:
        streamlit_host = enforce_public_bind_policy()
    except PublicBindPolicyError as exc:
        raise SystemExit(f"agilab: {exc}") from exc

    # Determine the target script (adjust path if necessary)
    target_script = str(Path(__file__).parent / "main_page.py")

    # Build the base argument list for Streamlit.
    new_argv = ["streamlit", "run", "--server.address", streamlit_host, target_script]

    # Collect custom arguments (only pass what is provided).
    custom_args = []

    resolved_apps_path = _resolve_apps_path(args.apps_path)

    if resolved_apps_path:
        custom_args.extend(["--apps-path", resolved_apps_path])

    if unknown:
        custom_args.extend(unknown)

    # Only add the double dash and custom arguments if there are any.
    if custom_args:
        new_argv.append("--")
        new_argv.extend(custom_args)

    _ensure_streamlit_config_file()
    sys.argv = new_argv
    stcli = _load_streamlit_cli()
    return stcli.main()


if __name__ == "__main__":
    raise SystemExit(main())
