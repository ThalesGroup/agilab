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
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
# INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
# IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY,
# OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
# OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import sys
import os
import asyncio
from pathlib import Path
import argparse
import errno
import getpass
import shutil

core_root = Path(__file__).parents[1]
node_src = str(core_root / 'core/node/src')
env_src = core_root / 'core/agi-env/src'
sys.path.insert(0, node_src)
if env_src.exists():
    sys.path.insert(0, str(env_src))
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv

# Take the first argument from the command line as the module name
if len(sys.argv) > 1:
    project = Path(sys.argv[1])
    project_name = project.name or str(project)
    module = project_name.replace("_project", "").replace('-', '_')
else:
    raise ValueError("Please provide the module name as the first argument.")

module = module.strip().strip("/")
print('install module:', module)


def _seed_example_scripts(app_slug: str) -> None:
    """Copy AGI_* example scripts to ~/log/execute/<app_slug> if missing."""

    if not app_slug:
        return

    repo_root = Path(__file__).resolve().parents[3]
    examples_dir = repo_root / "src" / "agilab" / "examples" / app_slug
    if not examples_dir.exists():
        return

    execute_dir = Path.home() / "log" / "execute" / app_slug
    execute_dir.mkdir(parents=True, exist_ok=True)

    for source in sorted(examples_dir.glob("AGI_*.py")):
        destination = execute_dir / source.name
        if destination.exists():
            continue
        try:
            shutil.copy2(source, destination)
            print(f"[INFO] Seeded {destination} from examples.")
        except OSError as exc:
            print(f"[WARN] Unable to copy {source} to {destination}: {exc}")


def _seed_lab_steps(app_slug: str) -> None:
    """Copy lab_steps*.toml into ~/export/<app_slug> if missing."""

    if not app_slug:
        return

    repo_root = Path(__file__).resolve().parents[3]
    app_dir = repo_root / "src" / "agilab" / "apps" / f"{app_slug}_project"
    if not app_dir.exists():
        return

    export_root = Path(os.environ.get("AGI_EXPORT_DIR", Path.home() / "export")).expanduser()
    target_dir = export_root / app_slug
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"[WARN] Unable to create export dir {target_dir}: {exc}")
        return

    for source in sorted(app_dir.glob("lab_steps*.toml")):
        destination = target_dir / source.name
        if destination.exists():
            continue
        try:
            shutil.copy2(source, destination)
            print(f"[INFO] Seeded {destination} from {source}.")
        except OSError as exc:
            print(f"[WARN] Unable to copy {source} to {destination}: {exc}")

def _seed_app_settings(app_slug: str) -> None:
    """Copy app_settings.toml into ~/export/<app_slug> if missing."""

    if not app_slug:
        return

    repo_root = Path(__file__).resolve().parents[3]
    app_dir = repo_root / "src" / "agilab" / "apps" / f"{app_slug}_project" / "src"
    source = app_dir / "app_settings.toml"
    if not source.exists():
        return

    export_root = Path(os.environ.get("AGI_EXPORT_DIR", Path.home() / "export")).expanduser()
    target_dir = export_root / app_slug
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"[WARN] Unable to create export dir {target_dir}: {exc}")
        return

    destination = target_dir / "app_settings.toml"
    if destination.exists():
        return
    try:
        shutil.copy2(source, destination)
        print(f"[INFO] Seeded {destination} from {source}.")
    except OSError as exc:
        print(f"[WARN] Unable to copy {source} to {destination}: {exc}")


_seed_example_scripts(module)
_seed_lab_steps(module)
_seed_app_settings(module)


def resolve_share_mount() -> Path:
    """Return the absolute path that AGI_SHARE_DIR should resolve to."""

    share_dir_raw = os.environ.get("AGI_SHARE_DIR")
    share_dir = Path(share_dir_raw) if share_dir_raw else Path("clustershare")
    home_root = Path.home() / "MyApp" if getpass.getuser().startswith("T0") else Path.home()
    share_dir_expanded = share_dir.expanduser()
    if share_dir_expanded.is_absolute():
        return share_dir_expanded
    return (home_root / share_dir_expanded).expanduser()


def ensure_data_storage(env: AgiEnv) -> None:
    """Guarantee the app data directory is available before invoking AGI installers."""

    if env.is_worker_env:
        return
    if not env.app_data_rel:
        raise RuntimeError("App data path is not configured on environment.")
    app_data_path = Path(env.app_data_rel).expanduser()
    share_base = env.share_root_path()
    if app_data_path.is_absolute():
        data_root = app_data_path.resolve(strict=False)
    else:
        data_root = (share_base / app_data_path).resolve(strict=False)
    share_hint = env.agi_share_dir
    share_hint_str = str(Path(share_hint).expanduser()) if share_hint else str(share_base)
    try:
        data_root.mkdir(parents=True, exist_ok=True)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Required data directory {data_root} is unavailable. "
            f"Verify AGI_SHARE_DIR ({share_hint_str}) is mounted before running install."
        ) from exc
    except OSError as exc:
        if exc.errno in {
            errno.ENOENT,
            errno.EHOSTDOWN,
            errno.ESTALE,
            errno.ENOTCONN,
            errno.EIO,
        }:
            raise RuntimeError(
                f"Unable to reach data directory {data_root} ({exc.strerror or exc}). "
                f"Verify AGI_SHARE_DIR ({share_hint_str}) is mounted before running install."
            ) from exc
        raise


async def main():
    """
    Main asynchronous function to resolve paths in pyproject.toml and install a module using AGI.
    """
    try:
        parser = argparse.ArgumentParser(
            description="Run AGILAB application with custom options."
        )

        parser.add_argument(
            "active_app",
            type=str,
            help="Path to the app project (e.g. src/agilab/apps/builtin/flight_project)",
        )

        parser.add_argument(
            "--verbose", type=int, default=1, help="Verbosity level (1-3 default: 1)"
        )

        args, unknown = parser.parse_known_args()

        app_path = Path(args.active_app).expanduser()
        try:
            app_env = AgiEnv(
                apps_path=app_path.parent,
                app=app_path.name,
                verbose=args.verbose,
            )
        except RuntimeError as err:
            share_error_tokens = (
                "Required data directory",
                "Unable to reach data directory",
            )
            if any(token in str(err) for token in share_error_tokens):
                resolved_share = resolve_share_mount()
                share_label = os.environ.get("AGI_SHARE_DIR", "clustershare")
                print(
                    "[ERROR] AGI_SHARE_DIR '%s' is not mounted (expected path: %s). "
                    "Mount the share before running install."
                    % (share_label, resolved_share),
                    file=sys.stderr,
                )
                return 2
            raise
    except Exception as e:
        raise Exception("Failed to resolve env and core path in toml") from e

    try:
        ensure_data_storage(app_env)
    except RuntimeError as err:
        print(f"[ERROR] {err}", file=sys.stderr)
        return 1

    await AGI.install(
        env=app_env,
        scheduler="127.0.0.1",
        verbose=args.verbose,
        modes_enabled=AGI.DASK_MODE | AGI.CYTHON_MODE
    )

    local_user = getpass.getuser()
    ssh_user = (app_env.user or "").strip()
    if ssh_user and ssh_user != local_user:
        repo_root = Path(__file__).resolve().parents[3]
        agi_core_dist = repo_root / "src/agilab/core/agi-core/dist"
        install_hint = f"sudo uv add {agi_core_dist}/*.whl"
        print(
            f"[INFO] Current user '{local_user}' differs from cluster SSH user '{ssh_user}'. "
            "Ask the 'agi' login to run:\n"
            "  uv init --bare --no-workspace\n"
            f"  {install_hint}"
        )
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
