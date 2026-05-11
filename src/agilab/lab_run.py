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
import sys
import tomllib
from importlib import metadata as importlib_metadata
from pathlib import Path

UI_EXTRA_HINT = "Install the UI profile with `python -m pip install 'agilab[ui]'` or install `agi-gui`."
_PUBLIC_BIND_GUARD_PATH = Path(__file__).resolve().parent / "ui_public_bind_guard.py"
_PUBLIC_BIND_GUARD_SPEC = importlib.util.spec_from_file_location(
    "agilab_ui_public_bind_guard_local",
    _PUBLIC_BIND_GUARD_PATH,
)
if _PUBLIC_BIND_GUARD_SPEC is None or _PUBLIC_BIND_GUARD_SPEC.loader is None:
    raise ModuleNotFoundError(f"Unable to load ui_public_bind_guard.py from {_PUBLIC_BIND_GUARD_PATH}")
_PUBLIC_BIND_GUARD_MODULE = importlib.util.module_from_spec(_PUBLIC_BIND_GUARD_SPEC)
_PUBLIC_BIND_GUARD_SPEC.loader.exec_module(_PUBLIC_BIND_GUARD_MODULE)
PublicBindPolicyError = _PUBLIC_BIND_GUARD_MODULE.PublicBindPolicyError
enforce_public_bind_policy = _PUBLIC_BIND_GUARD_MODULE.enforce_public_bind_policy


def _detect_repo_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "agilab").is_dir():
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
        project = tomllib.loads(pyproject_path.read_text(encoding="utf-8")).get("project", {})
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


def _run_security_check(argv: list[str]) -> int:
    from agilab import security_check

    return security_check.main(argv)


def _missing_ui_dependencies() -> list[str]:
    missing: list[str] = []
    for module_name, distribution_name in (
        ("streamlit", "streamlit"),
        ("agi_gui", "agi-gui"),
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
    if raw_argv[:1] == ["dry-run"]:
        return _run_first_proof(["--dry-run", *raw_argv[1:]])
    if raw_argv[:1] in (["security-check"], ["security_check"]):
        return _run_security_check(raw_argv[1:])

    parser = argparse.ArgumentParser(
        description="Run AGILAB application with custom options."
    )
    parser.add_argument(
        "--apps-path", type=str, help="Where you store your apps (default is ./)",
                        default=None
    )
    parser.add_argument(
        "-V", "--version",
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
    target_script = str(Path(__file__).parent /"main_page.py")

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

    sys.argv = new_argv
    stcli = _load_streamlit_cli()
    return stcli.main()

if __name__ == "__main__":
    raise SystemExit(main())
