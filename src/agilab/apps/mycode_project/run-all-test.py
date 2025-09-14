#!/usr/bin/env python3
"""
Run manager/worker test suites. Coverage is DISABLED by default.
Enable it with --with-cov (then XML + optional badge will be produced).
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def which(exe: str) -> str | None:
    return shutil.which(exe)


def discover_tests(root: Path) -> tuple[list[str], list[str]]:
    """
    Look for tests named like test*manager.py in manager_root,
    and test*worker.py in worker_root (skip any .venv paths).
    """
    managers = sorted(
        str(p) for p in root.rglob("test*manager.py")
        if p.is_file() and ".venv" not in p.parts
    )
    workers = sorted(
        str(p) for p in root.rglob("test*worker.py")
        if p.is_file() and ".venv" not in p.parts
    )
    return workers, managers


def pick_badge_dir(repo_root: Path) -> Path:
    # Try <repo_root>/../../../../docs/html, else <repo_root>/badges
    try:
        badges_root = repo_root.parents[3] / "docs" / "html"
    except IndexError:
        badges_root = repo_root / "badges"
    badges_root.mkdir(parents=True, exist_ok=True)
    return badges_root


def run(cmd: list[str], cwd: Path, env: dict | None = None) -> None:
    print("Running:", " ".join(cmd))
    try:
        subprocess.run(cmd, cwd=str(cwd), check=True, env=env)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] command failed with exit code {e.returncode}")
        sys.exit(e.returncode)


def build_pytest_cmd(
    use_uv: bool,
    project: str | None,
    repo_root: Path,
    cov_pkgs: list[str],
    local_badge_dir: Path | None,
    extra_pytest_args: list[str],
    tests: list[str],
) -> list[str]:
    cov_enabled = bool(cov_pkgs)
    cov_args = [f"--cov={pkg}" for pkg in cov_pkgs] if cov_enabled else []

    if use_uv:
        base = ["uv", "run", "--preview-features", "python-upgrade"]
        if project:
            base += ["--project", project]
        base += ["-m", "pytest"]
    else:
        base = [sys.executable, "-m", "pytest"]

    cmd = [
        *base,
        "--rootdir", str(repo_root),
        "--import-mode=importlib",
        *cov_args,
    ]

    if cov_enabled:
        # text report per run; we combine + emit XML at the end
        cmd += ["--cov-report=term"]

    if local_badge_dir is not None and cov_enabled:
        # Only meaningful if coverage is on and plugin is installed
        cmd += ["--local-badge-output-dir", str(local_badge_dir)]

    cmd += extra_pytest_args
    cmd += tests
    return cmd


def combine_and_emit_xml(use_uv: bool, cwd: Path) -> None:
    base = ["uv", "run", "-m"] if use_uv else [sys.executable, "-m"]
    run([*base, "coverage", "combine"], cwd=cwd)
    run([*base, "coverage", "xml", "-o", "coverage.xml"], cwd=cwd)


def try_make_badge(use_uv: bool, badges_root: Path, cwd: Path) -> None:
    """
    Prefer genbadge (nice SVG), fall back to coverage-badge.
    If neither is installed, skip quietly.
    """
    base = ["uv", "run"] if use_uv else []

    # genbadge
    genbadge_cmd = [*base, "genbadge", "coverage", "-i", "coverage.xml", "-o", str(badges_root / "coverage.svg")]
    try:
        run(genbadge_cmd, cwd=cwd)
        print(f"Badge written to {badges_root / 'coverage.svg'} (genbadge).")
        return
    except SystemExit:
        pass  # try fallback

    # coverage-badge
    covbadge_cmd = [*base, "coverage-badge", "-o", str(badges_root / "coverage.svg"), "-f"]
    try:
        run(covbadge_cmd, cwd=cwd)
        print(f"Badge written to {badges_root / 'coverage.svg'} (coverage-badge).")
    except SystemExit:
        print("Note: genbadge/coverage-badge not available; skipped badge generation.")


def main() -> None:
    script_dir = Path(__file__).parent
    repo_root = script_dir.absolute()  # manager project root (this repo)
    badges_root = pick_badge_dir(repo_root)

    # Heuristic: corresponding worker checkout under ~/wenv/<name with project→worker>
    worker_repo_name = repo_root.name.replace("project", "worker")
    worker_root = Path.home() / "wenv" / worker_repo_name
    if not worker_root.exists():
        # If it doesn't exist, just point at repo_root so rglob() is harmless
        worker_root = repo_root

    workers, managers = discover_tests(repo_root)
    default_cov_pkg = "agilab.apps." + repo_root.name  # e.g., agilab.apps.sat_trajectory_project

    parser = argparse.ArgumentParser(description="Run manager/worker tests. Coverage is disabled by default.")
    parser.add_argument("--managers-project", default=None, help="uv --project path for manager tests")
    parser.add_argument("--workers-project", default=None, help="uv --project path for worker tests")

    parser.add_argument("--with-cov", action="store_true", help="Enable coverage (disabled by default)")
    parser.add_argument(
        "--cov",
        nargs="*",
        default=[default_cov_pkg],
        help="Coverage packages for manager tests (only used with --with-cov)",
    )
    parser.add_argument(
        "--worker-cov",
        nargs="*",
        default=[default_cov_pkg],
        help="Coverage packages for worker tests (only used with --with-cov)",
    )

    parser.add_argument("--no-badges", action="store_true", help="Disable per-run badge plugin and final badge gen")
    parser.add_argument("--pytest-args", nargs=argparse.REMAINDER, default=[], help="Extra args passed to pytest")
    args = parser.parse_args()

    if not workers and not managers:
        print("No test files found.")
        sys.exit(1)

    uv_available = which("uv") is not None
    use_uv = uv_available  # prefer uv if present

    # Coverage mode
    cov_enabled = args.with_cov
    if not cov_enabled:
        args.cov = []
        args.worker_cov = []

    # Separate envs to separate coverage outputs if enabled
    env_mgr = os.environ.copy()
    env_wrk = os.environ.copy()
    if cov_enabled:
        env_mgr["COVERAGE_FILE"] = str(repo_root / ".coverage.managers")
        env_wrk["COVERAGE_FILE"] = str(repo_root / ".coverage.workers")

    # Run manager tests
    if managers:
        pytest_cmd_mgr = build_pytest_cmd(
            use_uv=use_uv,
            project=args.managers_project,
            repo_root=repo_root,
            cov_pkgs=args.cov,
            local_badge_dir=None if (args.no_badges or not cov_enabled) else badges_root,
            extra_pytest_args=args.pytest_args,
            tests=managers,
        )
        run(pytest_cmd_mgr, repo_root, env=env_mgr if cov_enabled else None)
    else:
        print("No manager tests discovered; skipping manager phase.")

    # Run worker tests
    if workers:
        pytest_cmd_wrk = build_pytest_cmd(
            use_uv=use_uv,
            project=args.workers_project,
            repo_root=worker_root,  # rootdir should match worker tree
            cov_pkgs=args.worker_cov,
            local_badge_dir=None if (args.no_badges or not cov_enabled) else badges_root,
            extra_pytest_args=args.pytest_args,
            tests=workers,
        )
        run(pytest_cmd_wrk, worker_root, env=env_wrk if cov_enabled else None)
    else:
        print("No worker tests discovered; skipping worker phase.")

    # Combine + emit XML + badge only when coverage is enabled
    if cov_enabled:
        combine_and_emit_xml(use_uv=use_uv, cwd=repo_root)
        if not args.no_badges:
            try_make_badge(use_uv=use_uv, badges_root=badges_root, cwd=repo_root)

    print("✅ All done.")
    sys.exit(0)


if __name__ == "__main__":
    main()

