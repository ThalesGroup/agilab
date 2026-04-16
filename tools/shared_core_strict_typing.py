from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = {
    "agi_env": REPO_ROOT / "src/agilab/core/agi-env/src",
    "agi_node": REPO_ROOT / "src/agilab/core/agi-node/src",
    "agi_cluster": REPO_ROOT / "src/agilab/core/agi-cluster/src",
}
PROFILES = {
    "support-first": [
        "agi_cluster.agi_distributor.background_jobs_support",
        "agi_node.agi_dispatcher.base_worker_path_support",
        "agi_node.agi_dispatcher.base_worker_execution_support",
        "agi_node.agi_dispatcher.base_worker_runtime_support",
        "agi_node.agi_dispatcher.base_worker_service_support",
        "agi_cluster.agi_distributor.cleanup_support",
        "agi_cluster.agi_distributor.deployment_build_support",
        "agi_cluster.agi_distributor.deployment_local_support",
        "agi_cluster.agi_distributor.deployment_orchestration_support",
        "agi_cluster.agi_distributor.deployment_prepare_support",
        "agi_cluster.agi_distributor.deployment_remote_support",
        "agi_cluster.agi_distributor.entrypoint_support",
        "agi_cluster.agi_distributor.runtime_misc_support",
        "agi_cluster.agi_distributor.runtime_distribution_support",
        "agi_cluster.agi_distributor.scheduler_io_support",
        "agi_cluster.agi_distributor.service_runtime_support",
        "agi_cluster.agi_distributor.service_state_support",
        "agi_cluster.agi_distributor.transport_support",
        "agi_cluster.agi_distributor.uv_source_support",
    ],
}


def _module_root_name(module_name: str) -> str:
    return module_name.split(".", 1)[0]


def resolve_modules(profile: str, extra_modules: Sequence[str]) -> list[str]:
    modules = list(PROFILES[profile])
    for module_name in extra_modules:
        if module_name not in modules:
            modules.append(module_name)
    return modules


def build_mypy_env(
    modules: Sequence[str],
    *,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = dict(base_env or os.environ)
    roots: list[str] = []
    for module_name in modules:
        root_name = _module_root_name(module_name)
        source_root = SOURCE_ROOTS[root_name]
        source_root_str = str(source_root)
        if source_root_str not in roots:
            roots.append(source_root_str)

    existing = env.get("MYPYPATH", "")
    if existing:
        for entry in existing.split(os.pathsep):
            if entry and entry not in roots:
                roots.append(entry)
    env["MYPYPATH"] = os.pathsep.join(roots)
    return env


def build_mypy_command(
    modules: Sequence[str],
    *,
    python_executable: str | None = None,
) -> list[str]:
    command = [python_executable or sys.executable, "-m", "mypy", "--strict"]
    for module_name in modules:
        command.extend(["-m", module_name])
    return command


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the curated shared-core strict mypy slice.",
    )
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES.keys()),
        default="support-first",
        help="Named module profile to run.",
    )
    parser.add_argument(
        "--module",
        action="append",
        default=[],
        dest="modules",
        help="Additional module to include in the check.",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print the resolved command and environment without running mypy.",
    )
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="List available profiles and exit.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.list_profiles:
        for profile_name, modules in sorted(PROFILES.items()):
            print(f"{profile_name}:")
            for module_name in modules:
                print(f"  - {module_name}")
        return 0

    modules = resolve_modules(args.profile, args.modules)
    env = build_mypy_env(modules)
    command = build_mypy_command(modules)

    if args.print_only:
        print(f"MYPYPATH={env['MYPYPATH']}")
        print(shlex.join(command))
        return 0

    if importlib.util.find_spec("mypy") is None:
        raise RuntimeError(
            "mypy is not available in this environment. Run via "
            "`uv --preview-features extra-build-dependencies run --with mypy python tools/shared_core_strict_typing.py ...`."
        )

    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
