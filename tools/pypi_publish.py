#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
agilab local publisher for TestPyPI using ~/.pypirc.

Highlights
- Builds with uv (wheels and/or sdists). No pep517 shim.
- Per-package versions for published AGI components, bundles, and payload packages.
  Real PyPI never auto-bumps to .postN; choose an explicit new version instead.
  TestPyPI may auto-bump for retries.
- Robust pyproject.toml editing with tomlkit (preserves formatting, trailing newline).
- TestPyPI twine auth from ~/.pypirc; CLI --username/--password are ONLY for cleanup/purge.
- Optional purge/cleanup (web login flow) before/after using pypi-cleanup.
- Optional exact release deletion using pypi-cleanup --version-regex.
- Optional yank previous versions on PyPI.
- Optional git tag (date-based), GitHub Release, and commit of version bumps.

Typical:
  uv run tools/pypi_publish.py --repo testpypi
  # Real PyPI publication must use .github/workflows/pypi-publish.yaml
  # with PyPI Trusted Publishing / OIDC.

Notes
- Local twine upload to real PyPI is disabled by default so published files show
  Trusted Publishing / OIDC provenance. Set AGILAB_ALLOW_LOCAL_PYPI_TWINE=1 only
  for documented break-glass maintenance.
- Cleanup/purge uses PyPI web login and needs real account USER/PASS (not token).
"""

from __future__ import annotations

import argparse
import configparser
import contextlib
import glob
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from email.parser import Parser
from typing import Dict, List, Tuple
from html.parser import HTMLParser

try:
    from package_split_contract import (
        APP_PACKAGE_NAMES,
        ASSET_PACKAGE_NAMES,
        CORE_PACKAGE_NAMES,
        EXACT_INTERNAL_DEPENDENCY_PACKAGE_NAMES,
        LIBRARY_PACKAGE_CONTRACTS,
        PAGE_PACKAGE_NAMES,
        UMBRELLA_PACKAGE_CONTRACT,
        WHEEL_ONLY_PACKAGE_NAMES,
        package_by_name,
    )
except ModuleNotFoundError:  # pragma: no cover - used when imported as tools.pypi_publish
    from tools.package_split_contract import (
        APP_PACKAGE_NAMES,
        ASSET_PACKAGE_NAMES,
        CORE_PACKAGE_NAMES,
        EXACT_INTERNAL_DEPENDENCY_PACKAGE_NAMES,
        LIBRARY_PACKAGE_CONTRACTS,
        PAGE_PACKAGE_NAMES,
        UMBRELLA_PACKAGE_CONTRACT,
        WHEEL_ONLY_PACKAGE_NAMES,
        package_by_name,
    )

# third-party bootstrap (install if missing)
def _ensure_pkgs():
    need = []
    try:
        import tomlkit  # type: ignore
    except Exception:
        need.append("tomlkit")
    try:
        import packaging  # type: ignore
    except Exception:
        need.append("packaging")
    if need:
        subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", *need], check=True)

_ensure_pkgs()
from tomlkit import parse as toml_parse, dumps as toml_dumps  # type: ignore
from packaging.markers import default_environment  # type: ignore
from packaging.requirements import InvalidRequirement, Requirement  # type: ignore
from packaging.version import Version, InvalidVersion  # type: ignore

# upload-state flags (set by twine_upload)
UPLOAD_COLLISION_DETECTED: bool = False
UPLOAD_SUCCESS_COUNT: int = 0
UPLOAD_SKIPPED_EXISTING_COUNT: int = 0
ALLOW_LOCAL_PYPI_TWINE_ENV = "AGILAB_ALLOW_LOCAL_PYPI_TWINE"


# ---------- CLI ----------
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Publish agilab wheels/sdists to (Test)PyPI using ~/.pypirc")

    # Destination
    ap.add_argument("--repo", choices=["testpypi", "pypi"], required=True, help="Target repo section in ~/.pypirc")

    # Build selection
    ap.add_argument("--dist", choices=["wheel", "sdist", "both"], default="both", help="What to build with uv (default: both)")

    # Behavior
    ap.add_argument("--skip-existing", action="store_true", default=True, help="Twine skip-existing (default on)")
    ap.add_argument("--retries", type=int, default=1, help="Twine upload retries (default: 1)")
    ap.add_argument("--dry-run", action="store_true", help="Plan only; print decisions and exit before build/upload")
    ap.add_argument(
        "--packages",
        nargs="+",
        choices=ALL_PACKAGE_NAMES,
        help="Limit build/upload to the specified packages (default: all)"
    )
    ap.add_argument("--verbose", action="store_true", help="Verbose logging for cleanup")

    # Version control
    ap.add_argument(
        "--version",
        help=(
            "Explicit version 'X.Y.Z[.postN]'. If omitted, base=UTC YYYY.MM.DD. "
            "Real PyPI refuses automatic .postN bumps when that version is already used."
        ),
    )

    # Cleanup / purge (web login)
    ap.add_argument("--purge-before", action="store_true", help="Run cleanup before upload (leave most recent only)")
    ap.add_argument("--purge-after", action="store_true", help="Run cleanup after upload (leave most recent only)")
    ap.add_argument("--cleanup-only", action="store_true", help="Only cleanup; no build/upload")
    ap.add_argument("--days", type=int, default=None, help="Cleanup: only delete releases in the last N days")
    ap.add_argument("--delete-project", action="store_true", help="Cleanup: pass --delete-project (dangerous)")
    # IMPORTANT: The following two are ONLY for cleanup/purge (not for twine)
    ap.add_argument("--username", help="Cleanup/Purge web-login username (NOT used for twine)")
    ap.add_argument("--password", help="Cleanup/Purge web-login password (NOT used for twine)")
    ap.add_argument("--cleanup-timeout", type=int, default=60, help="Cleanup timeout seconds (0 disables)")
    ap.add_argument("--skip-cleanup", action="store_true", help="Disable cleanup entirely")
    ap.add_argument(
        "--delete-pypi-release",
        action="append",
        default=[],
        metavar="VERSION",
        help=(
            "Cleanup: delete exactly VERSION from the selected PyPI packages using pypi-cleanup. "
            "Repeatable; requires web-login cleanup credentials."
        ),
    )
    ap.add_argument(
        "--delete-former-pypi-release",
        dest="delete_pypi_release",
        action="append",
        metavar="VERSION",
        help="Alias for --delete-pypi-release.",
    )

    # Yank
    ap.add_argument("--yank-previous", action="store_true", help="On PyPI, yank versions older than the chosen version")

    # Git
    ap.add_argument("--git-tag", action="store_true", help="Create & push date tag (vYYYY.MM.DD[-N]) on PyPI")
    ap.add_argument("--git-commit-version", action="store_true", help="git add/commit pyproject version bumps")
    ap.add_argument("--git-reset-on-failure", action="store_true", help="On failure, git checkout -- pyproject files")
    ap.add_argument(
        "--delete-former-github-release",
        action="store_true",
        help=(
            "After creating the current GitHub Release, delete the previous GitHub Release entry. "
            "The underlying git tag and PyPI files are kept."
        ),
    )

    # Docs
    ap.add_argument(
        "--gen-docs",
        action="store_true",
        help="Regenerate docs and sync the docs repository after publishing",
    )
    ap.add_argument(
        "--skip-release-preflight",
        dest="release_preflight",
        action="store_false",
        help="Skip the local release preflight before publishing (not allowed for real PyPI releases).",
    )

    # Preflight
    ap.add_argument("--no-pypirc-check", dest="pypirc_check", action="store_false", help="Skip ~/.pypirc preflight")

    if "--usage" in sys.argv:
        ap.print_help()
        sys.exit(0)

    return ap.parse_args()


@dataclass
class Cfg:
    repo: str
    dist: str
    skip_existing: bool
    retries: int
    dry_run: bool
    verbose: bool
    version: str | None
    purge_before: bool
    purge_after: bool
    cleanup_only: bool
    clean_days: int | None
    clean_delete_project: bool
    cleanup_user: str | None
    cleanup_pass: str | None
    cleanup_timeout: int
    skip_cleanup: bool
    yank_previous: bool
    git_tag: bool
    git_commit_version: bool
    git_reset_on_failure: bool
    pypirc_check: bool
    packages: list[str] | None
    gen_docs: bool
    release_preflight: bool = True
    delete_former_github_release: bool = False
    delete_pypi_releases: list[str] | None = None


def make_cfg(args: argparse.Namespace) -> Cfg:
    return Cfg(
        repo=args.repo,
        dist=args.dist,
        skip_existing=bool(args.skip_existing),
        retries=int(args.retries),
        dry_run=bool(args.dry_run),
        verbose=bool(args.verbose),
        version=args.version.strip().lstrip("v") if args.version else None,
        purge_before=bool(args.purge_before),
        purge_after=bool(args.purge_after),
        cleanup_only=bool(args.cleanup_only),
        clean_days=args.days,
        clean_delete_project=bool(args.delete_project),
        cleanup_user=args.username,
        cleanup_pass=args.password,
        cleanup_timeout=max(0, int(args.cleanup_timeout or 0)),
        skip_cleanup=bool(args.skip_cleanup),
        yank_previous=bool(args.yank_previous),
        git_tag=bool(args.git_tag),
        git_commit_version=bool(args.git_commit_version),
        git_reset_on_failure=bool(args.git_reset_on_failure),
        delete_former_github_release=bool(getattr(args, "delete_former_github_release", False)),
        pypirc_check=bool(getattr(args, "pypirc_check", True)),
        packages=list(args.packages) if getattr(args, "packages", None) else None,
        gen_docs=bool(getattr(args, "gen_docs", False)),
        release_preflight=bool(getattr(args, "release_preflight", True)),
        delete_pypi_releases=list(getattr(args, "delete_pypi_release", []) or []),
    )


# ---------- Repo layout (agilab) ----------
REPO_ROOT = pathlib.Path.cwd().resolve()

def _package_entry(package_name: str) -> Tuple[str, pathlib.Path, pathlib.Path]:
    package = package_by_name(package_name)
    project_dir = REPO_ROOT if package.project == "." else REPO_ROOT / package.project
    return package.name, REPO_ROOT / package.pyproject, project_dir


CORE: List[Tuple[str, pathlib.Path, pathlib.Path]] = [_package_entry(name) for name in CORE_PACKAGE_NAMES]
def page_libs() -> List[Tuple[str, pathlib.Path, pathlib.Path]]:
    return [entry for entry in (_package_entry(name) for name in PAGE_PACKAGE_NAMES) if entry[1].exists()]


def app_libs() -> List[Tuple[str, pathlib.Path, pathlib.Path]]:
    return [entry for entry in (_package_entry(name) for name in APP_PACKAGE_NAMES) if entry[1].exists()]


def publishable_libs() -> List[Tuple[str, pathlib.Path, pathlib.Path]]:
    libs: List[Tuple[str, pathlib.Path, pathlib.Path]] = []
    inserted_page_libs = False
    inserted_app_libs = False
    for entry in CORE:
        libs.append(entry)
        if entry[0] == "agi-env":
            libs.extend(page_libs())
            inserted_page_libs = True
        if entry[0] == "agi-core":
            libs.extend(app_libs())
            inserted_app_libs = True
    if not inserted_page_libs:
        libs.extend(page_libs())
    if not inserted_app_libs:
        libs.extend(app_libs())
    return libs


UMBRELLA = _package_entry(UMBRELLA_PACKAGE_CONTRACT.name)
ALL_PACKAGE_NAMES = [name for name, *_ in publishable_libs()] + [UMBRELLA[0]]
WHEEL_ONLY_PACKAGES = set(WHEEL_ONLY_PACKAGE_NAMES)

APPS_REPO_ENV_KEYS: tuple[str, ...] = ("APPS_REPOSITORY",)
DEFAULT_APPS_REPO_DIRNAME = "agilab-apps"
APPS_REPO_REMOTE_ENV = "APPS_REPOSITORY_REMOTE"
DOCS_REPO_ENV_KEYS: tuple[str, ...] = ("DOCS_REPOSITORY",)
DEFAULT_DOCS_REPO_DIRNAME = "thales_agilab"
DOCS_REPO_REMOTE_ENV = "DOCS_REPOSITORY_REMOTE"
DOCS_REPO_RELEASE_PATH_PREFIXES: tuple[str, ...] = ("docs/source/",)
GITHUB_RELEASES_URL = "https://github.com/ThalesGroup/agilab/releases"
GITHUB_REPO = "ThalesGroup/agilab"
COVERAGE_WORKFLOW = "coverage.yml"
PUBLIC_RELEASE_METADATA_PATHS: tuple[str, ...] = (
    "CHANGELOG.md",
    "docs/.docs_source_mirror_stamp.json",
    "docs/source/index.rst",
    "docs/source/data/release_proof.toml",
    "docs/source/release-proof.rst",
    "test/test_public_demo_links.py",
)
GITHUB_RELEASE_URL_RE = re.compile(
    r"https://github\.com/ThalesGroup/agilab/releases/tag/v[0-9A-Za-z._-]+"
)

PYPI_JSON = {
    "testpypi": "https://test.pypi.org/pypi/{name}/json",
    "pypi":     "https://pypi.org/pypi/{name}/json",
}
PYPI_SIMPLE = {
    "testpypi": "https://test.pypi.org/simple/{name}/",
    "pypi":     "https://pypi.org/simple/{name}/",
}

BADGE_PATTERN = re.compile(
    r"\[!\[PyPI version\]\(https://img\.shields\.io/[^)]+\)\]\(https://pypi\.org/project/[^)]+\)"
)


def builtin_app_pyprojects() -> List[pathlib.Path]:
    base = REPO_ROOT / "src/agilab" / "apps" / "builtin"
    if not base.exists():
        return []
    candidates = {
        path
        for pattern in ("*_project/pyproject.toml", "*_project/src/*_worker/pyproject.toml")
        for path in base.glob(pattern)
        if path.is_file()
    }
    return sorted(candidates)


def sync_builtin_app_versions(new_version: str, pins: Dict[str, str] | None = None) -> List[pathlib.Path]:
    updated: List[pathlib.Path] = []
    for pyproject_path in builtin_app_pyprojects():
        set_version_in_pyproject(pyproject_path, new_version)
        if pins:
            pin_internal_deps(pyproject_path, pins, operator=">=")
        rel = pyproject_path.relative_to(REPO_ROOT)
        print(f"[version] builtin app {rel}: {new_version}")
        updated.append(pyproject_path)
    return updated



# ---------- Utils ----------
def run(cmd: List[str], cwd: pathlib.Path | None = None, env: dict | None = None, timeout: int | None = None):
    print("+", " ".join(map(str, cmd)))
    merged = os.environ.copy()
    if env:
        merged.update(env)
    subprocess.run(cmd, cwd=str(cwd or REPO_ROOT), check=True, text=True, env=merged, timeout=timeout)


def assert_pypirc_has(repo_name: str):
    p = pathlib.Path.home() / ".pypirc"
    if not p.exists():
        sys.exit(f"ERROR: {p} not found. Create it with a [{repo_name}] section.")
    cfg = configparser.RawConfigParser()
    cfg.read(p)
    if not cfg.has_section(repo_name):
        sys.exit(f"ERROR: {p} missing section [{repo_name}]. Add it to use --repo {repo_name}.")


def read_cleanup_creds_from_pypirc(repo_name: str) -> tuple[str | None, str | None]:
    p = pathlib.Path.home() / ".pypirc"
    if not p.exists():
        return None, None
    cfg = configparser.RawConfigParser()
    cfg.read(p)
    section = f"{repo_name}_cleanup"
    if not cfg.has_section(section):
        return None, None
    username = (cfg.get(section, "username", fallback="") or "").strip() or None
    password = (cfg.get(section, "password", fallback="") or "").strip() or None
    return username, password


def cleanup_host(repo_name: str) -> str:
    return "https://test.pypi.org/" if repo_name == "testpypi" else "https://pypi.org/"


def cleanup_credentials(cfg: Cfg, *, required: bool = False) -> tuple[str, str] | None:
    pypirc_user, pypirc_pass = read_cleanup_creds_from_pypirc(cfg.repo)

    # precedence: CLI > env > ~/.pypirc cleanup section
    cleanup_user = (
        (cfg.cleanup_user or "").strip()
        or (os.environ.get("PYPI_USERNAME") or "").strip()
        or pypirc_user
        or ""
    )
    cleanup_pass = (
        (cfg.cleanup_pass or "").strip()
        or (os.environ.get("PYPI_CLEANUP_PASSWORD") or "").strip()
        or (os.environ.get("PYPI_PASSWORD") or "").strip()
        or pypirc_pass
        or ""
    )

    if not cleanup_user or not cleanup_pass:
        message = "cleanup web-login credentials via CLI, env, or ~/.pypirc are required; tokens won't work here."
        if required:
            raise SystemExit(f"ERROR: {message}")
        print(f"[cleanup] Skipping: requires {message}")
        return None
    if cleanup_user == "__token__" or str(cleanup_pass).startswith("pypi-"):
        message = "cleanup needs real account credentials, not an API token."
        if required:
            raise SystemExit(f"ERROR: {message}")
        print(f"[cleanup] Skipping: {message}")
        return None
    return cleanup_user, cleanup_pass


def exact_release_regex(version: str) -> str:
    try:
        normalized = str(Version(version.strip().lstrip("v")))
    except InvalidVersion as exc:
        raise SystemExit(f"ERROR: Invalid --delete-pypi-release version: {version!r}") from exc
    return f"^{re.escape(normalized)}$"


def load_doc(p: pathlib.Path):
    return toml_parse(p.read_text(encoding="utf-8"))


def save_doc(p: pathlib.Path, doc):
    out = toml_dumps(doc)
    # Keep trailing newline if original had it (nice for diffs)
    raw = p.read_text(encoding="utf-8") if p.exists() else ""
    if raw.endswith("\n") and not out.endswith("\n"):
        out += "\n"
    p.write_text(out, encoding="utf-8")


_name_pat = re.compile(r'^[A-Za-z0-9_.-]+')
def clean_name(name: str) -> str:
    m = _name_pat.match(str(name))
    return m.group(0) if m else str(name)


def sanitize_project_names(paths: List[pathlib.Path]):
    for p in paths:
        if not p.exists():
            continue
        doc = load_doc(p)
        proj = doc.get("project") or {}
        raw = str(proj.get("name", ""))
        cleaned = clean_name(raw)
        if raw and raw != cleaned:
            proj["name"] = cleaned
            doc["project"] = proj
            save_doc(p, doc)
            print(f"[fix] {p.relative_to(REPO_ROOT)}: '{raw}' -> '{cleaned}'")


# ---------- Version work ----------
def fetch_url_text(url: str, *, timeout: int = 10) -> str:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read().decode("utf-8", "ignore")
    except Exception as urllib_exc:
        curl = shutil.which("curl")
        if not curl:
            raise RuntimeError(f"{url}: {urllib_exc}") from urllib_exc
        try:
            proc = subprocess.run(
                [curl, "-fsSL", "--max-time", str(timeout), url],
                check=True,
                text=True,
                capture_output=True,
            )
            return proc.stdout
        except subprocess.CalledProcessError as curl_exc:
            raise RuntimeError(f"{url}: urllib={urllib_exc}; curl={curl_exc}") from curl_exc


def fetch_url_json(url: str, *, timeout: int = 10) -> dict:
    text = fetch_url_text(url, timeout=timeout)
    data = json.loads(text) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"{url}: expected JSON object")
    return data


class _SimpleVersionParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.versions: set[str] = set()

    def handle_data(self, data: str) -> None:
        self.versions |= set(re.findall(r"\d+\.\d+\.\d+(?:\.post\d+)?", data or ""))


def pypi_releases(name: str, repo_target: str) -> set[str]:
    url = PYPI_JSON[repo_target].format(name=name)
    releases: set[str] = set()

    try:
        data = fetch_url_json(url, timeout=10)
        releases |= set((data.get("releases") or {}).keys())
    except Exception as e:
        print(f"[warn] Could not fetch releases for {name} from {url}: {e}")

    simple_url = PYPI_SIMPLE[repo_target].format(name=name)

    try:
        html = fetch_url_text(simple_url, timeout=10)
        parser = _SimpleVersionParser()
        parser.feed(html)
        releases |= parser.versions
    except Exception as e:
        print(f"[warn] Could not fetch simple index for {name} from {simple_url}: {e}")

    if releases:
        return releases

    # Do NOT silently ignore; this commonly leads to version collisions later.
    return {"0.0.0.post0"}


def require_safe_pypi_release(cfg: Cfg) -> None:
    if cfg.delete_former_github_release and (cfg.repo != "pypi" or not cfg.git_tag):
        raise SystemExit(
            "ERROR: --delete-former-github-release requires --repo pypi --git-tag "
            "because it runs after the new GitHub Release has been created."
        )
    if cfg.repo != "pypi" or cfg.dry_run or cfg.cleanup_only:
        return
    if str(os.environ.get(ALLOW_LOCAL_PYPI_TWINE_ENV, "")).strip().lower() not in {"1", "true", "yes", "on"}:
        raise SystemExit(
            "ERROR: Local twine upload to real PyPI is disabled. "
            "Run the GitHub pypi-publish workflow so PyPI files are uploaded via Trusted Publishing/OIDC. "
            f"Break-glass local upload requires {ALLOW_LOCAL_PYPI_TWINE_ENV}=1 and must be documented."
        )
    missing: list[str] = []
    if not cfg.git_commit_version:
        missing.append("--git-commit-version")
    if not cfg.git_tag:
        missing.append("--git-tag")
    if not cfg.git_reset_on_failure:
        missing.append("--git-reset-on-failure")
    if missing:
        raise SystemExit(
            "ERROR: Real PyPI releases must run with "
            + ", ".join(missing)
            + " so the repo state, tag state, and rollback path stay aligned."
        )
    if not cfg.release_preflight:
        raise SystemExit(
            "ERROR: Real PyPI releases must keep the local release preflight enabled. "
            "Do not use --skip-release-preflight for a real PyPI publish."
        )


def release_preflight_profiles(cfg: Cfg) -> list[str]:
    if cfg.repo != "pypi" or cfg.dry_run or cfg.cleanup_only or not cfg.release_preflight:
        return []
    return [
        "agi-env",
        "agi-core-combined",
        "agi-gui",
        "docs",
        "installer",
        "shared-core-typing",
        "dependency-policy",
        "release-proof",
    ]


RELEASE_PREFLIGHT_COVERAGE_ARTIFACTS = (
    ".coverage",
    ".coverage.agi-env",
    ".coverage.agi-core-combined",
    ".coverage.agi-gui",
    ".coverage.agi-node",
    ".coverage.agi-cluster",
    "coverage-agi-env.xml",
    "coverage-agi-node.xml",
    "coverage-agi-cluster.xml",
    "coverage-agi-gui.xml",
    "coverage-agi-core.xml",
    "coverage-agilab.xml",
)


def clean_release_preflight_coverage_artifacts() -> None:
    """Remove stale local coverage artifacts before release workflow parity."""
    for rel_path in RELEASE_PREFLIGHT_COVERAGE_ARTIFACTS:
        path = REPO_ROOT / rel_path
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except FileNotFoundError:
            pass


def run_release_preflight(cfg: Cfg) -> None:
    profiles = release_preflight_profiles(cfg)
    if not profiles:
        return
    clean_release_preflight_coverage_artifacts()
    cmd = [
        "uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "python",
        "tools/workflow_parity.py",
    ]
    for profile in profiles:
        cmd.extend(["--profile", profile])
    print("[preflight] Running required local release preflight: " + ", ".join(profiles))
    run(cmd, cwd=REPO_ROOT)


def run_release_coverage_badge_refresh() -> None:
    """Refresh coverage badges from the release preflight XML before tagging."""

    print("[preflight] Refreshing release coverage badges from local coverage XML")
    run([sys.executable, "tools/generate_component_coverage_badges.py"], cwd=REPO_ROOT)
    run([sys.executable, "tools/coverage_badge_guard.py"], cwd=REPO_ROOT)


def run_pre_upload_release_guard(
    cfg: Cfg,
    *,
    planned_tag: str | None,
    chosen_version: str,
    version_targets: list[str],
) -> None:
    """Prove release metadata is locally pushable before irreversible upload."""
    if cfg.repo != "pypi" or cfg.dry_run or cfg.cleanup_only:
        return
    if planned_tag is not None:
        update_public_release_references_for_guard(planned_tag, chosen_version, version_targets)
    print(f"[preflight] Running pre-upload release metadata guard for {chosen_version}")
    run_release_preflight(cfg)
    run_release_coverage_badge_refresh()
    run(
        [
            sys.executable,
            "tools/coverage_badge_guard.py",
            "--changed-only",
            "--allow-badge-only",
        ],
        cwd=REPO_ROOT,
    )


def _git_head_sha(repo: pathlib.Path = REPO_ROOT) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo),
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def _gh_json(args: list[str]) -> object:
    if shutil.which("gh") is None:
        raise SystemExit("ERROR: GitHub CLI ('gh') is required for the release coverage prerequisite.")
    result = subprocess.run(
        ["gh", *args],
        cwd=str(REPO_ROOT),
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout or "null")


def list_coverage_workflow_runs_for_head(head_sha: str) -> list[dict[str, object]]:
    payload = _gh_json(
        [
            "run",
            "list",
            "--repo",
            GITHUB_REPO,
            "--workflow",
            COVERAGE_WORKFLOW,
            "--commit",
            head_sha,
            "--limit",
            "5",
            "--json",
            "databaseId,status,conclusion,url,createdAt,headSha",
        ]
    )
    if not isinstance(payload, list):
        raise SystemExit("ERROR: could not read GitHub coverage workflow runs.")
    return [run for run in payload if isinstance(run, dict)]


def trigger_coverage_workflow(branch: str) -> None:
    run(
        [
            "gh",
            "workflow",
            "run",
            COVERAGE_WORKFLOW,
            "--repo",
            GITHUB_REPO,
            "--ref",
            branch,
        ],
        cwd=REPO_ROOT,
    )


def release_coverage_workflow_required(cfg: Cfg) -> bool:
    return cfg.repo == "pypi" and cfg.git_tag and not cfg.dry_run and not cfg.cleanup_only


def run_release_coverage_workflow_prerequisite(
    cfg: Cfg,
    *,
    timeout_seconds: int | None = None,
    poll_seconds: int = 20,
    list_runs_fn=list_coverage_workflow_runs_for_head,
    trigger_fn=trigger_coverage_workflow,
    sleep_fn=time.sleep,
    time_fn=time.monotonic,
) -> None:
    """Require the GitHub coverage workflow to pass for the release commit."""

    if not release_coverage_workflow_required(cfg):
        return

    branch = current_git_branch()
    if branch == "HEAD":
        raise SystemExit("ERROR: release coverage prerequisite requires a named git branch, not detached HEAD.")
    head_sha = _git_head_sha()
    timeout = timeout_seconds
    if timeout is None:
        timeout = int(os.environ.get("AGILAB_RELEASE_COVERAGE_TIMEOUT_SECONDS", "1800"))
    deadline = time_fn() + max(1, timeout)
    triggered = False
    last_state: tuple[str, str] | None = None

    print(f"[preflight] Requiring {COVERAGE_WORKFLOW} success for release commit {head_sha[:12]}")
    while True:
        runs = list_runs_fn(head_sha)
        if runs:
            run_info = runs[0]
            status = str(run_info.get("status") or "")
            conclusion = str(run_info.get("conclusion") or "")
            url = str(run_info.get("url") or "")
            state = (status, conclusion)
            if status == "completed":
                if conclusion == "success":
                    print(f"[preflight] Coverage workflow passed for release commit: {url}")
                    return
                raise SystemExit(
                    f"ERROR: Coverage workflow prerequisite failed for release commit {head_sha[:12]} "
                    f"(conclusion={conclusion}). Fix coverage badges or tests before tagging: {url}"
                )
            if state != last_state:
                print(f"[preflight] Waiting for coverage workflow ({status or 'unknown'}): {url}")
                last_state = state
        elif not triggered:
            print(f"[preflight] No coverage workflow run found for {head_sha[:12]}; triggering {COVERAGE_WORKFLOW}")
            trigger_fn(branch)
            triggered = True
        elif last_state != ("missing", ""):
            print(f"[preflight] Waiting for triggered coverage workflow to appear for {head_sha[:12]}")
            last_state = ("missing", "")

        remaining = deadline - time_fn()
        if remaining <= 0:
            raise SystemExit(
                f"ERROR: Timed out waiting for {COVERAGE_WORKFLOW} to pass for release commit {head_sha[:12]}."
            )
        sleep_fn(min(max(1, poll_seconds), remaining))


EXTERNAL_INSTALL_PLATFORMS: tuple[str, ...] = (
    "x86_64-pc-windows-msvc",
    "x86_64-unknown-linux-gnu",
    "x86_64-apple-darwin",
)

NON_APPLE_SILICON_MARKER_ENVS: dict[str, dict[str, str]] = {
    "windows-x64": {
        "os_name": "nt",
        "platform_machine": "AMD64",
        "platform_system": "Windows",
        "sys_platform": "win32",
    },
    "linux-x64": {
        "os_name": "posix",
        "platform_machine": "x86_64",
        "platform_system": "Linux",
        "sys_platform": "linux",
    },
    "macos-x64": {
        "os_name": "posix",
        "platform_machine": "x86_64",
        "platform_system": "Darwin",
        "sys_platform": "darwin",
    },
}
APPLE_SILICON_ONLY_REQUIREMENTS: set[str] = {"mlx", "mlx-lm"}


def _wheel_files(files: List[str]) -> list[pathlib.Path]:
    return sorted(pathlib.Path(file) for file in files if str(file).endswith(".whl"))


def _wheel_requires_dist(wheel_path: pathlib.Path) -> list[str]:
    with zipfile.ZipFile(wheel_path) as archive:
        metadata_paths = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_paths) != 1:
            raise SystemExit(
                f"ERROR: {wheel_path.name} must contain exactly one dist-info/METADATA file "
                f"for release dependency validation; found {len(metadata_paths)}."
            )
        metadata = Parser().parsestr(archive.read(metadata_paths[0]).decode("utf-8", "replace"))
    return list(metadata.get_all("Requires-Dist") or [])


def _marker_env(overrides: dict[str, str]) -> dict[str, str]:
    env = default_environment()
    env.update(overrides)
    return env


def validate_wheel_external_machine_metadata(files: List[str]) -> None:
    """Catch platform-scoped dependency mistakes before a wheel reaches PyPI."""
    violations: list[str] = []
    for wheel_path in _wheel_files(files):
        for raw_requirement in _wheel_requires_dist(wheel_path):
            try:
                requirement = Requirement(raw_requirement)
            except InvalidRequirement as exc:
                violations.append(f"{wheel_path.name}: invalid Requires-Dist {raw_requirement!r}: {exc}")
                continue
            if requirement.name.lower() not in APPLE_SILICON_ONLY_REQUIREMENTS:
                continue
            for env_name, env_overrides in NON_APPLE_SILICON_MARKER_ENVS.items():
                marker = requirement.marker
                if marker is None or marker.evaluate(_marker_env(env_overrides)):
                    violations.append(
                        f"{wheel_path.name}: {requirement} must be excluded on {env_name}; "
                        "Apple MLX dependencies are only valid on darwin/arm64"
                    )

    if violations:
        raise SystemExit(
            "ERROR: release artifact dependency metadata is not external-machine safe:\n- "
            + "\n- ".join(violations)
        )


def run_pre_upload_external_install_guard(cfg: Cfg, files: List[str]) -> None:
    """Dry-run the built wheels against external install platforms before upload."""
    if cfg.repo != "pypi" or cfg.dry_run or cfg.cleanup_only:
        return
    wheels = _wheel_files(files)
    if not wheels:
        raise SystemExit("ERROR: Real PyPI release requires wheel artifacts for external install matrix validation.")

    validate_wheel_external_machine_metadata(files)

    with tempfile.TemporaryDirectory(prefix="agilab-release-install-matrix-") as tmp_dir:
        tmp_root = pathlib.Path(tmp_dir)
        for platform in EXTERNAL_INSTALL_PLATFORMS:
            target = tmp_root / platform
            print(f"[preflight] External install matrix guard: {platform}")
            run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--dry-run",
                    "--target",
                    str(target),
                    "--python-version",
                    "3.13",
                    "--python-platform",
                    platform,
                    *(str(path) for path in wheels),
                ],
                cwd=REPO_ROOT,
                timeout=300,
            )


def split_base_and_post(ver: str) -> Tuple[str, int | None]:
    m = re.match(r"^(.*?)(?:\.post(\d+))?$", ver)
    if not m:
        return ver, None
    base, postn = m.groups()
    return base, (int(postn) if postn is not None else None)


def normalize_base(v: str) -> str:
    base, _ = split_base_and_post(v)
    return base


def safe_ver(x: str) -> Version:
    try:
        return Version(x)
    except InvalidVersion:
        return Version("0")


def versions_equivalent(left: str, right: str) -> bool:
    try:
        return Version(left) == Version(right)
    except InvalidVersion:
        return left == right


def release_exists(candidate: str, releases: set[str]) -> bool:
    return any(versions_equivalent(candidate, release) for release in releases)


def max_base_across_packages(package_names: List[str], repo_target: str) -> str:
    all_versions = set()
    for n in package_names:
        all_versions |= pypi_releases(n, repo_target)
    if not all_versions:
        return datetime.now(timezone.utc).strftime("%Y.%m.%d")  # seed by date
    bases = {normalize_base(v) for v in all_versions if v}
    return max(bases, key=safe_ver)


def latest_existing_release(package_names: List[str], repo_target: str) -> str | None:
    latest: str | None = None
    for name in package_names:
        releases = {v for v in pypi_releases(name, repo_target) if v and v != "0.0.0.post0"}
        if not releases:
            continue
        candidate = max(releases, key=safe_ver)
        if latest is None or safe_ver(candidate) > safe_ver(latest):
            latest = candidate
    return latest


def next_free_post_for_all(package_names: List[str], repo_target: str, base: str) -> str:
    per_pkg = {n: pypi_releases(n, repo_target) for n in package_names}

    # start beyond current max .post across all pkgs
    k_start = 1
    for releases in per_pkg.values():
        max_post = 0
        release_parts = [split_base_and_post(release) for release in releases]
        if any(post is None and versions_equivalent(release_base, base) for release_base, post in release_parts):
            max_post = 0
        for release_base, post in release_parts:
            if versions_equivalent(release_base, base) and post is not None and post > max_post:
                max_post = post
        k_start = max(k_start, max_post + 1)

    k = k_start
    while True:
        cand = f"{base}.post{k}"
        if all(not release_exists(cand, per_pkg[name]) for name in package_names):
            return cand
        k += 1


def _raise_pypi_auto_post_disabled(version: str, repo_target: str, collisions: Dict[str, List[str]] | None = None) -> None:
    collision_lines = []
    for package, releases in sorted((collisions or {}).items()):
        if releases:
            collision_lines.append(f"{package}: {', '.join(releases)}")
    detail = f" Existing releases: {'; '.join(collision_lines)}." if collision_lines else ""
    raise SystemExit(
        f"ERROR: {repo_target} release version {version} is already used. "
        "Automatic .postN PyPI version bumps are disabled; choose an explicit new release version."
        f"{detail}"
    )


def compute_unified_version(core_names: List[str], repo_target: str, base_version: str | None) -> Tuple[str, Dict[str, List[str]]]:
    collisions: Dict[str, List[str]] = {n: [] for n in core_names}

    if base_version:
        provided = base_version
        provided_base = normalize_base(provided)
        existing_by_pkg = {n: pypi_releases(n, repo_target) for n in core_names}
        provided_in_use = any(
            versions_equivalent(provided, release)
            for rels in existing_by_pkg.values()
            for release in rels
        )
        if not provided_in_use:
            chosen = provided
            base = provided_base
        else:
            base = provided_base
            for name, releases in existing_by_pkg.items():
                collisions[name] = sorted(
                    {release for release in releases if versions_equivalent(provided, release)},
                    key=safe_ver,
                )
            if repo_target == "pypi":
                _raise_pypi_auto_post_disabled(provided, repo_target, collisions)
            chosen = next_free_post_for_all(core_names, repo_target, base)
    else:
        today_base = datetime.now(timezone.utc).strftime("%Y.%m.%d")
        latest = latest_existing_release(core_names, repo_target)
        latest_base = normalize_base(latest) if latest else None
        base = (
            latest_base
            if latest_base is not None and safe_ver(latest_base) > safe_ver(today_base)
            else today_base
        )
        if repo_target == "pypi":
            existing_by_pkg = {n: pypi_releases(n, repo_target) for n in core_names}
            for name, releases in existing_by_pkg.items():
                collisions[name] = sorted(
                    {
                        release
                        for release in releases
                        if versions_equivalent(normalize_base(release), base)
                    },
                    key=safe_ver,
                )
            if any(collisions.values()):
                _raise_pypi_auto_post_disabled(base, repo_target, collisions)
            chosen = base
        else:
            # TestPyPI is often reused during release rehearsals, so keep .postN there.
            chosen = next_free_post_for_all(core_names, repo_target, base)

    latest = latest_existing_release(core_names, repo_target)
    if latest is not None and safe_ver(chosen) < safe_ver(latest):
        raise SystemExit(
            f"ERROR: Computed version {chosen} is lower than existing release "
            f"{latest} on {repo_target}. Choose an explicit --version >= the latest release."
        )

    # report collisions that influenced bump
    for n in core_names:
        rels = pypi_releases(n, repo_target)
        hits: List[str] = []
        for v in rels:
            b, post = split_base_and_post(v)
            if not versions_equivalent(b, base):
                continue
            if post is None or safe_ver(v) < safe_ver(chosen):
                hits.append(v)
        collisions[n] = sorted(set(hits), key=safe_ver)

    return chosen, collisions


def compute_package_versions(
    targets: List[Tuple[str, pathlib.Path, pathlib.Path]],
    repo_target: str,
    explicit_version: str | None,
) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    versions: Dict[str, str] = {}
    collisions: Dict[str, List[str]] = {}
    for name, toml_path, _project_dir in targets:
        if explicit_version is not None:
            chosen, package_collisions = compute_unified_version([name], repo_target, explicit_version)
            versions[name] = chosen
            collisions.update(package_collisions)
            continue

        chosen = get_version_from_pyproject(toml_path)
        versions[name] = chosen
        releases = pypi_releases(name, repo_target)
        hits = sorted(release for release in releases if versions_equivalent(chosen, release))
        if hits:
            collisions[name] = hits
        latest = latest_existing_release([name], repo_target)
        if latest is not None and safe_ver(chosen) < safe_ver(latest):
            raise SystemExit(
                f"ERROR: {name} pyproject version {chosen} is lower than existing release "
                f"{latest} on {repo_target}. Choose a version >= the latest release."
            )
    return versions, collisions


def primary_release_version(package_versions: Dict[str, str]) -> str:
    for package_name in (UMBRELLA[0], "agi-core", "agi-pages", "agi-apps"):
        version = package_versions.get(package_name)
        if version:
            return version
    try:
        return next(iter(package_versions.values()))
    except StopIteration as exc:
        raise SystemExit("ERROR: no packages selected for release") from exc


def pin_internal_deps_for_package(package_name: str, pyproject_path: pathlib.Path, pins: Dict[str, str]) -> bool:
    if package_name not in EXACT_INTERNAL_DEPENDENCY_PACKAGE_NAMES:
        return False
    return pin_internal_deps(pyproject_path, pins)


# ---------- TOML ops ----------
def get_version_from_pyproject(pyproject_path: str | pathlib.Path) -> str:
    p = pathlib.Path(pyproject_path)
    if not p.exists():
        raise RuntimeError(f"pyproject not found: {p}")
    raw = p.read_text(encoding="utf-8")
    doc = toml_parse(raw)
    try:
        return str(doc["project"]["version"])
    except KeyError as exc:
        raise RuntimeError(f"[project].version missing in {p}") from exc


def set_version_in_pyproject(pyproject_path: str | pathlib.Path, new_version: str) -> None:
    """
    Robustly set [project].version using tomlkit (preserves formatting/comments/EOL).
    If missing, insert after 'name' if present, else at top of [project].
    """
    p = pathlib.Path(pyproject_path)
    if not p.exists():
        raise RuntimeError(f"pyproject not found: {p}")

    raw = p.read_text(encoding="utf-8")
    try:
        doc = toml_parse(raw)
    except Exception as e:
        raise RuntimeError(f"Failed to parse TOML in {p}: {e}")

    if "project" not in doc:
        raise RuntimeError(f"[project] section not found in {p}")
    proj = doc["project"]

    if "version" in proj:
        proj["version"] = str(new_version)
    else:
        # Insert after 'name' if exists for nicer ordering
        try:
            keys = list(proj.keys())
            if "name" in proj:
                idx = keys.index("name") + 1
            else:
                idx = 0
            proj.insert(idx, "version", str(new_version))
        except Exception:
            proj["version"] = str(new_version)

    doc["project"] = proj
    save_doc(p, doc)


def pin_internal_deps(pyproject_path: pathlib.Path, pins: Dict[str, str], *, operator: str = "==") -> bool:
    if not pyproject_path.exists():
        return False
    doc = load_doc(pyproject_path)
    proj = doc.get("project") or {}
    changed = False

    def _pin_seq(seq):
        nonlocal changed
        out = []
        for dep in seq:
            s = str(dep)
            parts = s.split(";", 1)
            left, marker = parts[0].strip(), (";" + parts[1] if len(parts) == 2 else "")
            m = re.match(r"^([A-Za-z0-9_.-]+)(\[[^\]]+\])?", left)
            if m:
                pkg, extras = m.group(1), (m.group(2) or "")
                if pkg in pins:
                    s = f"{pkg}{extras}{operator}{pins[pkg]}{marker}"
                    changed = True
            out.append(s)
        return out

    if "dependencies" in proj and proj["dependencies"] is not None:
        proj["dependencies"] = _pin_seq(proj["dependencies"])
    if "optional-dependencies" in proj and proj["optional-dependencies"] is not None:
        for g, arr in list(proj["optional-dependencies"].items()):
            proj["optional-dependencies"][g] = _pin_seq(arr)

    if changed:
        doc["project"] = proj
        save_doc(pyproject_path, doc)
    return changed


# ---------- README badge helpers ----------
def shields_badge(_version: str, package_name: str) -> str:
    return (
        f"[![PyPI version](https://img.shields.io/pypi/v/{package_name}.svg?cacheSeconds=300)]"
        f"(https://pypi.org/project/{package_name}/)"
    )


def static_badge_path(package_name: str) -> pathlib.Path:
    return REPO_ROOT / "badges" / f"pypi-version-{package_name}.svg"


def render_static_badge_svg(version: str) -> str:
    version_text = f"v{version}"
    left_width = 38
    right_width = max(87, int(round(len(version_text) * 6.2 + 15)))
    total_width = left_width + right_width
    value_x = left_width + right_width / 2

    def _fmt(value: float) -> str:
        return str(int(value)) if float(value).is_integer() else f"{value:.1f}"

    return "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20" role="img" aria-label="pypi: {version_text}">',
            '<linearGradient id="b" x2="0" y2="100%">',
            '  <stop offset="0" stop-color="#fff" stop-opacity=".7"/>',
            '  <stop offset=".1" stop-opacity=".1"/>',
            '  <stop offset=".9" stop-opacity=".3"/>',
            '  <stop offset="1" stop-opacity=".5"/>',
            '</linearGradient>',
            '<mask id="a">',
            f'  <rect width="{total_width}" height="20" rx="3" fill="#fff"/>',
            '</mask>',
            '<g mask="url(#a)">',
            f'  <rect width="{left_width}" height="20" fill="#555"/>',
            f'  <rect x="{left_width}" width="{right_width}" height="20" fill="#0a7aca"/>',
            f'  <rect width="{total_width}" height="20" fill="url(#b)"/>',
            '</g>',
            '<g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">',
            '  <text x="19" y="15" fill="#010101" fill-opacity=".3">pypi</text>',
            '  <text x="19" y="14">pypi</text>',
            f'  <text x="{_fmt(value_x)}" y="15" fill="#010101" fill-opacity=".3">{version_text}</text>',
            f'  <text x="{_fmt(value_x)}" y="14">{version_text}</text>',
            '</g>',
            '</svg>',
            '',
        ]
    )


def update_badge(readme_path: pathlib.Path, package_name: str, version: str) -> bool:
    if not readme_path.exists():
        return False
    text = readme_path.read_text(encoding="utf-8")
    replacement = shields_badge(version, package_name)
    if BADGE_PATTERN.search(text):
        new_text = BADGE_PATTERN.sub(replacement, text, count=1)
    else:
        return False
    if new_text == text:
        return False
    readme_path.write_text(new_text, encoding="utf-8")
    rel = readme_path.relative_to(REPO_ROOT)
    print(f"[badge] {rel}: set PyPI badge to {version}")
    return True


def update_static_badge(svg_path: pathlib.Path, version: str) -> bool:
    if not svg_path.exists():
        return False
    rendered = render_static_badge_svg(version)
    current = svg_path.read_text(encoding="utf-8")
    if current == rendered:
        return False
    svg_path.write_text(rendered, encoding="utf-8")
    rel = svg_path.relative_to(REPO_ROOT)
    print(f"[badge] {rel}: set static PyPI badge to {version}")
    return True


def update_selected_badges(selected_core: List[Tuple[str, pathlib.Path, pathlib.Path]], include_umbrella: bool):
    touched = False
    for name, toml_path, project_dir in selected_core:
        readme = project_dir / "README.md"
        if not toml_path.exists():
            continue
        version = get_version_from_pyproject(toml_path)
        touched |= update_badge(readme, name, version)
        touched |= update_static_badge(static_badge_path(name), version)
    if include_umbrella:
        umbrella_toml = UMBRELLA[1]
        if umbrella_toml.exists():
            version = get_version_from_pyproject(umbrella_toml)
            readme = UMBRELLA[2] / "README.md"
            touched |= update_badge(readme, UMBRELLA[0], version)
            touched |= update_static_badge(static_badge_path(UMBRELLA[0]), version)
    return touched


def update_release_badge_for_project(
    package_name: str,
    toml_path: pathlib.Path,
    project_dir: pathlib.Path,
) -> bool:
    if not toml_path.exists():
        return False
    version = get_version_from_pyproject(toml_path)
    return update_badge(project_dir / "README.md", package_name, version) | update_static_badge(
        static_badge_path(package_name),
        version,
    )


def capture_release_file_state(paths: List[str]) -> Dict[pathlib.Path, bytes | None]:
    snapshot: Dict[pathlib.Path, bytes | None] = {}
    for rel_path in paths:
        path = REPO_ROOT / rel_path
        if path.is_file():
            snapshot[path] = path.read_bytes()
        elif path.exists():
            snapshot[path] = None
        else:
            snapshot[path] = None
    return snapshot


def restore_release_file_state(snapshot: Dict[pathlib.Path, bytes | None]) -> None:
    for path, data in snapshot.items():
        if data is None:
            if path.exists() and path.is_file():
                path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


@contextlib.contextmanager
def defer_sigint(label: str):
    interrupted = {"value": False}
    previous_handler = signal.getsignal(signal.SIGINT)

    def _handler(signum, frame):
        interrupted["value"] = True
        print(f"[signal] Deferring interrupt during {label}; stopping once it completes.")

    signal.signal(signal.SIGINT, _handler)
    try:
        yield interrupted
    finally:
        signal.signal(signal.SIGINT, previous_handler)


# ---------- Build ----------
def uv_build_project(project_dir: pathlib.Path, dist_kind: str):
    # clean
    for sub in ("dist", "build"):
        d = project_dir / sub
        if d.exists():
            shutil.rmtree(d)
    for egg in project_dir.rglob("*.egg-info"):
        shutil.rmtree(egg, ignore_errors=True)

    # build with uv
    if dist_kind in ("wheel", "both"):
        run(["uv", "build", "--project", str(project_dir), "--wheel"], cwd=project_dir)
    if dist_kind in ("sdist", "both"):
        run(["uv", "build", "--project", str(project_dir), "--sdist"], cwd=project_dir)


def effective_dist_kind(package_name: str, requested: str) -> str:
    """Return the build artifact kind supported by a published package."""
    if package_name in WHEEL_ONLY_PACKAGES:
        if requested == "sdist":
            raise SystemExit(
                f"ERROR: {package_name} is wheel-only by package policy. "
                "Use --dist wheel or --dist both."
            )
        if requested == "both":
            return "wheel"
    return requested


def uv_build_repo_root(dist_kind: str):
    for sub in ("dist", "build"):
        d = REPO_ROOT / sub
        if d.exists():
            shutil.rmtree(d)
    if dist_kind in ("wheel", "both"):
        run(["uv", "build", "--wheel"], cwd=REPO_ROOT)
    if dist_kind in ("sdist", "both"):
        run(["uv", "build", "--sdist"], cwd=REPO_ROOT)


def dist_files(project_dir: pathlib.Path) -> List[str]:
    return sorted(glob.glob(str((project_dir / "dist" / "*").resolve())))


def dist_files_root() -> List[str]:
    return sorted(glob.glob(str((REPO_ROOT / "dist" / "*").resolve())))


# ---------- Twine ----------
def twine_check(files: List[str]):
    if not files:
        raise SystemExit("No artifacts to check")
    run([sys.executable, "-m", "twine", "check", *files], cwd=REPO_ROOT)


def twine_upload(files: List[str], repo: str, skip_existing: bool, retries: int):
    global UPLOAD_COLLISION_DETECTED, UPLOAD_SUCCESS_COUNT, UPLOAD_SKIPPED_EXISTING_COUNT
    if not files:
        raise SystemExit("No artifacts to upload")
    UPLOAD_COLLISION_DETECTED = False
    UPLOAD_SUCCESS_COUNT = 0
    UPLOAD_SKIPPED_EXISTING_COUNT = 0
    print(f"+ twine upload -r {repo} ({len(files)} files)")
    base_cmd = [sys.executable, "-m", "twine", "upload", "--non-interactive", "-r", repo, "--verbose"]
    if skip_existing:
        base_cmd.append("--skip-existing")

    def _is_reuse_output(s: str) -> bool:
        s = (s or "").lower()
        keys = [
            "this filename has already been used",
            "file name has already been used",
            "file already exists",
            "filename already exists",
            "400 bad request",
            "409 conflict",
        ]
        return any(k in s for k in keys)

    for f in files:
        cmd = base_cmd + [f]
        fname = os.path.basename(f)
        for attempt in range(1, int(retries) + 1):
            proc = subprocess.run(
                cmd, cwd=str(REPO_ROOT), text=True, capture_output=True, env=os.environ.copy()
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            if proc.returncode == 0:
                UPLOAD_SUCCESS_COUNT += 1
                print(f"[upload] uploaded: {fname}")
                break
            # returncode != 0
            if skip_existing and _is_reuse_output(out):
                UPLOAD_COLLISION_DETECTED = True
                UPLOAD_SKIPPED_EXISTING_COUNT += 1
                print(f"[upload] skipped existing (already on server): {fname}")
                # continue with next file without failing
                break
            if attempt >= retries:
                if out.strip():
                    print(out)
                raise subprocess.CalledProcessError(proc.returncode, cmd, output=proc.stdout, stderr=proc.stderr)
            print(f"[upload] error on {fname} (attempt {attempt}/{retries}); retrying...")
    print(
        f"[upload] summary: uploaded={UPLOAD_SUCCESS_COUNT} "
        f"skipped_existing={UPLOAD_SKIPPED_EXISTING_COUNT} total={len(files)} repo={repo}"
    )

# ---------- Cleanup/Purge (web login) ----------
def cleanup_leave_latest(cfg: Cfg, packages: list[str]):
    if cfg.skip_cleanup:
        return

    credentials = cleanup_credentials(cfg)
    if credentials is None:
        return
    cleanup_user, cleanup_pass = credentials
    host = cleanup_host(cfg.repo)

    def run_cleanup(package: str):
        cmd = [
            "pypi-cleanup",
            "--leave-most-recent-only",
            "--do-it",
            "-y",
            "--host", host,
            "--package", package,
            "--username", cleanup_user,
        ]
        if cfg.clean_days is not None:
            cmd.extend(["--days", str(cfg.clean_days)])
        if cfg.clean_delete_project:
            cmd.append("--delete-project")
        if cfg.verbose:
            cmd.append("-v")

        print(f"[cleanup] Keeping only latest release for {package} on {cfg.repo}")
        try:
            run(cmd, cwd=REPO_ROOT, env={
                "PYPI_USERNAME": cleanup_user,
                "PYPI_PASSWORD": cleanup_pass,
                "PYPI_CLEANUP_PASSWORD": cleanup_pass,
            }, timeout=(cfg.cleanup_timeout or None))
        except subprocess.TimeoutExpired:
            print(f"[cleanup] warning: timed out after {cfg.cleanup_timeout}s for {package}; skipping.")
        except subprocess.CalledProcessError as exc:
            print(f"[cleanup] warning: pypi-cleanup exited with status {exc.returncode} for {package}; continuing.")

    for pkg in packages:
        run_cleanup(pkg)


def delete_exact_pypi_releases(cfg: Cfg, packages: list[str]) -> None:
    versions = list(cfg.delete_pypi_releases or [])
    if not versions:
        return
    if cfg.skip_cleanup:
        raise SystemExit("ERROR: --delete-pypi-release cannot be used with --skip-cleanup.")

    if cfg.dry_run:
        for version in versions:
            for package in packages:
                print(f"[cleanup] Would delete exact release {version} from {package} on {cfg.repo}")
        return

    cleanup_user, cleanup_pass = cleanup_credentials(cfg, required=True) or ("", "")
    host = cleanup_host(cfg.repo)
    env = {
        "PYPI_USERNAME": cleanup_user,
        "PYPI_PASSWORD": cleanup_pass,
        "PYPI_CLEANUP_PASSWORD": cleanup_pass,
    }

    for version in versions:
        pattern = exact_release_regex(version)
        for package in packages:
            cmd = [
                "pypi-cleanup",
                "--version-regex",
                pattern,
                "--do-it",
                "-y",
                "--host",
                host,
                "--package",
                package,
                "--username",
                cleanup_user,
            ]
            if cfg.verbose:
                cmd.append("-v")
            print(f"[cleanup] Deleting exact release {version} from {package} on {cfg.repo}")
            run(cmd, cwd=REPO_ROOT, env=env, timeout=(cfg.cleanup_timeout or None))


# ---------- Yank ----------
def yank_previous_versions(cfg: Cfg, packages: list[str], chosen: str):
    if cfg.repo != "pypi":
        return
    print(f"[yank] Attempting to yank versions older than {chosen} on {cfg.repo}")
    for name in packages:
        rels = sorted(pypi_releases(name, cfg.repo), key=safe_ver)
        for v in rels:
            if safe_ver(v) < safe_ver(chosen):
                cmd = [sys.executable, "-m", "twine", "yank", "-r", cfg.repo, name, v, "-y"]
                try:
                    run(cmd, cwd=REPO_ROOT)
                    print(f"[yank] Yanked {name} {v}")
                except Exception as e:
                    print(f"[yank] warning: could not yank {name} {v}: {e}")


# ---------- Symlink handling (umbrella) ----------
def remove_symlinks_for_umbrella() -> list[tuple[pathlib.Path, str, bool]]:
    """
    Remove only top-level symlinks under src/agilab/apps and src/agilab/apps-pages.
    Return list to restore (path, target, is_dir).
    """
    removed: list[tuple[pathlib.Path, str, bool]] = []
    for rel in ("src/agilab/apps", "src/agilab/apps-pages"):
        base = REPO_ROOT / rel
        if not base.exists():
            continue
        try:
            for p in base.iterdir():
                if p.is_symlink():
                    try:
                        target = os.readlink(str(p))
                    except OSError:
                        target = ""
                    is_dir = p.is_dir()
                    print(f"[symlink] removing {p}")
                    p.unlink(missing_ok=True)
                    removed.append((p, target, is_dir))
        except Exception:
            pass
    return removed


def restore_symlinks(entries: list[tuple[pathlib.Path, str, bool]]):
    for path, target, is_dir in entries:
        try:
            if not target:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(target, path, target_is_directory=is_dir)
            print(f"[symlink] restored {path} -> {target}")
        except Exception as e:
            print(f"[symlink] warning: failed to restore {path}: {e}")


# ---------- Git ----------
def _tag_exists(tag: str, repo: pathlib.Path = REPO_ROOT) -> bool:
    try:
        subprocess.run(
            ["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
            cwd=str(repo),
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False


def compute_date_tag() -> str:
    base = datetime.now(timezone.utc).strftime("%Y.%m.%d")
    tag = base
    n = 2
    while _tag_exists(f"v{tag}"):
        tag = f"{base}-{n}"
        n += 1
    return tag


def _is_git_repo(path: pathlib.Path) -> bool:
    try:
        subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=str(path),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, NotADirectoryError):
        return False


def _candidate_repo_paths(env_keys: tuple[str, ...], default_dirname: str) -> List[Tuple[str, pathlib.Path]]:
    candidates: List[Tuple[str, pathlib.Path]] = []
    for key in env_keys:
        value = os.environ.get(key)
        if value:
            candidates.append((f"env:{key}", pathlib.Path(value).expanduser()))
    default_path = (REPO_ROOT.parent / default_dirname).expanduser()
    candidates.append(("default", default_path))
    return candidates


def find_apps_repository() -> Tuple[pathlib.Path | None, str | None]:
    for source, raw_path in _candidate_repo_paths(APPS_REPO_ENV_KEYS, DEFAULT_APPS_REPO_DIRNAME):
        try:
            resolved = raw_path.resolve()
        except FileNotFoundError:
            resolved = raw_path
        if not resolved.exists():
            if source.startswith("env:"):
                print(f"[git] apps repository path '{resolved}' from {source.split(':',1)[1]} does not exist; skipping")
            continue
        if not _is_git_repo(resolved):
            if source.startswith("env:"):
                print(f"[git] apps repository path '{resolved}' from {source.split(':',1)[1]} is not a git repository; skipping")
            continue
        return resolved, source
    return None, None


def find_docs_repository() -> Tuple[pathlib.Path | None, str | None]:
    for source, raw_path in _candidate_repo_paths(DOCS_REPO_ENV_KEYS, DEFAULT_DOCS_REPO_DIRNAME):
        try:
            resolved = raw_path.resolve()
        except FileNotFoundError:
            resolved = raw_path
        if not resolved.exists():
            if source.startswith("env:"):
                print(f"[git] docs repository path '{resolved}' from {source.split(':',1)[1]} does not exist; skipping")
            continue
        if not _is_git_repo(resolved):
            if source.startswith("env:"):
                print(f"[git] docs repository path '{resolved}' from {source.split(':',1)[1]} is not a git repository; skipping")
            continue
        return resolved, source
    return None, None


def _git_status_paths(repo: pathlib.Path) -> list[str]:
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo),
        check=True,
        text=True,
        capture_output=True,
    )
    paths: list[str] = []
    for line in proc.stdout.splitlines():
        if not line:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip()
        if path:
            paths.append(path)
    return paths


def _is_docs_repo_release_path(path: str) -> bool:
    return any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in DOCS_REPO_RELEASE_PATH_PREFIXES)


def _git_upstream(repo: pathlib.Path) -> str | None:
    proc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        cwd=str(repo),
        check=False,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return None
    upstream = proc.stdout.strip()
    return upstream or None


def _git_ahead_behind(repo: pathlib.Path, upstream: str) -> tuple[int, int]:
    proc = subprocess.run(
        ["git", "rev-list", "--left-right", "--count", f"{upstream}...HEAD"],
        cwd=str(repo),
        check=True,
        text=True,
        capture_output=True,
    )
    left_count, right_count = proc.stdout.strip().split()
    behind = int(left_count)
    ahead = int(right_count)
    return ahead, behind


def _git_commit_paths(repo: pathlib.Path, revision: str) -> list[str]:
    proc = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", revision],
        cwd=str(repo),
        check=True,
        text=True,
        capture_output=True,
    )
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _git_commit_summary(repo: pathlib.Path, revision: str) -> str:
    proc = subprocess.run(
        ["git", "show", "-s", "--format=%h %s", revision],
        cwd=str(repo),
        check=True,
        text=True,
        capture_output=True,
    )
    return proc.stdout.strip()


def _unpublished_non_release_commits(repo: pathlib.Path, upstream: str) -> list[str]:
    proc = subprocess.run(
        ["git", "rev-list", "--reverse", f"{upstream}..HEAD"],
        cwd=str(repo),
        check=True,
        text=True,
        capture_output=True,
    )
    non_release: list[str] = []
    for revision in [line.strip() for line in proc.stdout.splitlines() if line.strip()]:
        paths = _git_commit_paths(repo, revision)
        if not paths or any(not _is_docs_repo_release_path(path) for path in paths):
            non_release.append(_git_commit_summary(repo, revision))
    return non_release


def ensure_docs_repo_push_ready(repo: pathlib.Path) -> None:
    upstream = _git_upstream(repo)
    if not upstream:
        raise SystemExit(
            f"ERROR: docs repository '{repo}' has no upstream branch; "
            "refusing to push release-managed docs from an ambiguous branch."
        )

    ahead, behind = _git_ahead_behind(repo, upstream)
    if behind:
        raise SystemExit(
            f"ERROR: docs repository '{repo}' is behind {upstream} by {behind} commit(s). "
            "Rebase or replay the docs release from an up-to-date clean checkout before publishing."
        )

    if ahead:
        non_release = _unpublished_non_release_commits(repo, upstream)
        if non_release:
            raise SystemExit(
                f"ERROR: docs repository '{repo}' has unpublished non-docs commits outside "
                "release-managed docs/source/; refusing to push the docs release branch: "
                + ", ".join(non_release)
            )


def ensure_docs_repo_release_ready(repo: pathlib.Path) -> list[str]:
    dirty_paths = _git_status_paths(repo)
    if not dirty_paths:
        return []
    release_paths = [path for path in dirty_paths if _is_docs_repo_release_path(path)]
    ignored_paths = [path for path in dirty_paths if not _is_docs_repo_release_path(path)]
    if ignored_paths:
        print(
            "[git] docs repository has unrelated dirty paths outside release-managed docs/source/; "
            "ignoring them for docs release: "
            + ", ".join(sorted(ignored_paths))
        )
    return release_paths


def _create_tag_in_repo(repo_path: pathlib.Path, tag_ref: str, release_label: str, remote: str):
    run(["git", "tag", "-a", tag_ref, "-m", f"Release {release_label}"], cwd=repo_path)
    run(["git", "push", remote, tag_ref], cwd=repo_path)


def create_and_push_tag(tag: str, *, include_apps_repo: bool = True, include_docs_repo: bool = False):
    tag_ref = f"v{tag}"
    _create_tag_in_repo(REPO_ROOT, tag_ref, tag, "origin")
    print(f"[git] created and pushed {tag_ref}")

    if include_apps_repo:
        apps_repo, source = find_apps_repository()
        if not apps_repo:
            print("[git] apps repository not found; skipping secondary tag")
        else:
            apps_remote = os.environ.get(APPS_REPO_REMOTE_ENV, "origin")
            if _tag_exists(tag_ref, apps_repo):
                print(f"[git] apps repository '{apps_repo}' already has {tag_ref}; skipping secondary tag push")
            else:
                try:
                    _create_tag_in_repo(apps_repo, tag_ref, tag, apps_remote)
                except subprocess.CalledProcessError as exc:
                    raise SystemExit(
                        f"ERROR: failed to tag apps repository at {apps_repo} ({apps_remote}): {exc}"
                    ) from exc
                print(f"[git] created and pushed {tag_ref} in apps repository ({apps_repo})")

    if include_docs_repo:
        docs_repo, source = find_docs_repository()
        if not docs_repo:
            print("[git] docs repository not found; skipping docs tag")
            return
        dirty_release_paths = ensure_docs_repo_release_ready(docs_repo)
        if dirty_release_paths:
            raise SystemExit(
                f"ERROR: docs repository '{docs_repo}' has uncommitted release-managed docs paths: "
                + ", ".join(sorted(dirty_release_paths))
            )
        docs_remote = os.environ.get(DOCS_REPO_REMOTE_ENV, "origin")
        if _tag_exists(tag_ref, docs_repo):
            print(f"[git] docs repository '{docs_repo}' already has {tag_ref}; skipping docs tag push")
            return
        try:
            _create_tag_in_repo(docs_repo, tag_ref, tag, docs_remote)
        except subprocess.CalledProcessError as exc:
            raise SystemExit(
                f"ERROR: failed to tag docs repository at {docs_repo} ({docs_remote}): {exc}"
            ) from exc
        print(f"[git] created and pushed {tag_ref} in docs repository ({docs_repo})")


def github_release_notes(chosen_version: str, package_names: list[str]) -> str:
    packages = ", ".join(package_names)
    return (
        f"Published AGILAB {chosen_version} to PyPI.\n\n"
        f"Packages: {packages}\n"
    )


def create_or_update_github_release(tag: str, chosen_version: str, package_names: list[str]) -> None:
    tag_ref = tag if tag.startswith("v") else f"v{tag}"
    gh = shutil.which("gh")
    if not gh:
        raise SystemExit(
            "ERROR: GitHub Release creation requires the GitHub CLI ('gh'). "
            "Install gh or create the release manually before considering the PyPI release complete."
        )

    title = f"AGILAB {chosen_version}"
    notes = github_release_notes(chosen_version, package_names)
    view = subprocess.run(
        [gh, "release", "view", tag_ref],
        cwd=str(REPO_ROOT),
        check=False,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if view.returncode == 0:
        run([gh, "release", "edit", tag_ref, "--title", title, "--notes", notes, "--latest"], cwd=REPO_ROOT)
        print(f"[github] updated GitHub Release {tag_ref}")
        return

    run(
        [
            gh,
            "release",
            "create",
            tag_ref,
            "--title",
            title,
            "--notes",
            notes,
            "--verify-tag",
            "--latest",
        ],
        cwd=REPO_ROOT,
    )
    print(f"[github] created GitHub Release {tag_ref}")


def delete_former_github_release(current_tag: str, *, limit: int = 20) -> str | None:
    current_ref = current_tag if current_tag.startswith("v") else f"v{current_tag}"
    gh = shutil.which("gh")
    if not gh:
        raise SystemExit(
            "ERROR: --delete-former-github-release requires the GitHub CLI ('gh'). "
            "Install gh or delete the former GitHub Release manually."
        )

    proc = subprocess.run(
        [gh, "release", "list", "--limit", str(limit), "--json", "tagName"],
        cwd=str(REPO_ROOT),
        check=False,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise SystemExit(
            "ERROR: could not list GitHub Releases before deleting the former release: "
            + (proc.stderr or proc.stdout or "").strip()
        )

    try:
        releases = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: could not parse GitHub Release list JSON: {exc}") from exc

    former_ref = None
    for release in releases:
        tag_name = str((release or {}).get("tagName") or "").strip()
        if tag_name and tag_name != current_ref:
            former_ref = tag_name
            break

    if former_ref is None:
        print(f"[github] no former GitHub Release found to delete before {current_ref}")
        return None

    run([gh, "release", "delete", former_ref, "--yes"], cwd=REPO_ROOT)
    print(f"[github] deleted former GitHub Release {former_ref}; tag kept")
    return former_ref


def github_release_url(tag: str) -> str:
    tag_ref = tag if tag.startswith("v") else f"v{tag}"
    return f"{GITHUB_RELEASES_URL}/tag/{tag_ref}"


def _write_text_if_changed(path: pathlib.Path, text: str) -> bool:
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    if old == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def _replace_latest_release_url(text: str, release_url: str) -> str:
    updated, count = GITHUB_RELEASE_URL_RE.subn(release_url, text, count=1)
    if count:
        return updated
    marker = "latest public GitHub release"
    if marker in text:
        raise SystemExit(
            "ERROR: docs/source/index.rst mentions the latest public GitHub release "
            "but no GitHub release URL was found to update."
        )
    return text


def sync_docs_source_mirror(source: pathlib.Path) -> None:
    script = REPO_ROOT / "tools" / "sync_docs_source.py"
    if not script.exists():
        raise SystemExit(f"ERROR: docs mirror sync script not found: {script}")
    run(
        [
            sys.executable,
            str(script),
            "--source",
            str(source),
            "--target",
            str(REPO_ROOT / "docs/source"),
            "--apply",
            "--delete",
        ],
        cwd=REPO_ROOT,
    )


def update_docs_index_release_link(tag: str) -> None:
    release_url = github_release_url(tag)
    docs_repo, source = find_docs_repository()
    public_index = REPO_ROOT / "docs/source/index.rst"

    if docs_repo:
        canonical_source = docs_repo / "docs/source"
        canonical_index = canonical_source / "index.rst"
        if not canonical_index.exists():
            raise SystemExit(f"ERROR: canonical docs index not found: {canonical_index}")
        text = canonical_index.read_text(encoding="utf-8")
        if _write_text_if_changed(canonical_index, _replace_latest_release_url(text, release_url)):
            print(f"[docs] updated canonical latest release link: {canonical_index}")
        sync_docs_source_mirror(canonical_source)
        return

    if public_index.exists():
        raise SystemExit(
            "ERROR: canonical docs repository was not found; refusing to update only the "
            "public docs/source mirror because the mirror stamp would drift. Set DOCS_REPOSITORY "
            "or keep ../thales_agilab available before publishing to PyPI."
        )


def update_public_docs_index_release_link(tag: str) -> None:
    public_index = REPO_ROOT / "docs/source/index.rst"
    if not public_index.exists():
        return
    release_url = github_release_url(tag)
    text = public_index.read_text(encoding="utf-8")
    if _write_text_if_changed(public_index, _replace_latest_release_url(text, release_url)):
        print(f"[docs] updated public latest release link: {public_index}")


def _format_package_list(package_names: list[str]) -> str:
    quoted = [f"`{name}`" for name in package_names]
    if not quoted:
        return "the selected packages"
    if len(quoted) == 1:
        return quoted[0]
    return ", ".join(quoted[:-1]) + f", and {quoted[-1]}"


def _release_date_from_tag(tag: str) -> str:
    tag_body = tag[1:] if tag.startswith("v") else tag
    date_part = tag_body.split("-", 1)[0]
    match = re.fullmatch(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", date_part)
    if not match:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    year, month, day = (int(part) for part in match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


def _changelog_section(chosen_version: str, tag: str, package_names: list[str]) -> str:
    release_url = github_release_url(tag)
    release_date = _release_date_from_tag(tag)
    packages = _format_package_list(package_names)
    return (
        f"## [{chosen_version}] - {release_date}\n\n"
        f"GitHub Release: {release_url}\n\n"
        "### Changed\n\n"
        f"- Published AGILAB `{chosen_version}` to PyPI for {packages}.\n"
        "- Updated release metadata so public docs, changelog, PyPI, and GitHub "
        "Releases point to the same source tag.\n"
        "- Kept release automation active so future PyPI publishes create or "
        "update the matching GitHub Release after pushing the tag.\n"
    )


def update_changelog_release_entry(chosen_version: str, tag: str, package_names: list[str]) -> None:
    path = REPO_ROOT / "CHANGELOG.md"
    if not path.exists():
        print("[release] CHANGELOG.md not found; skipping changelog release entry")
        return

    text = path.read_text(encoding="utf-8")
    section = _changelog_section(chosen_version, tag, package_names)
    heading_re = re.compile(
        rf"^## \[{re.escape(chosen_version)}\] - .+?(?=^## \[|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    if heading_re.search(text):
        updated = heading_re.sub(section.rstrip() + "\n\n", text, count=1)
    else:
        first_heading = re.search(r"^## \[", text, flags=re.MULTILINE)
        if first_heading:
            updated = text[: first_heading.start()] + section + "\n" + text[first_heading.start():]
        else:
            updated = text.rstrip() + "\n\n" + section

    link_ref = f"[{chosen_version}]: {github_release_url(tag)}"
    link_re = re.compile(rf"^\[{re.escape(chosen_version)}\]: .*$", re.MULTILINE)
    if link_re.search(updated):
        updated = link_re.sub(link_ref, updated, count=1)
    elif updated.endswith("\n"):
        updated += link_ref + "\n"
    else:
        updated += "\n" + link_ref + "\n"

    if _write_text_if_changed(path, updated):
        print(f"[release] updated changelog entry for {chosen_version}")


def update_public_demo_release_test(tag: str) -> None:
    path = REPO_ROOT / "test/test_public_demo_links.py"
    if not path.exists():
        print("[release] public demo link test not found; skipping latest release constant")
        return
    tag_ref = tag if tag.startswith("v") else f"v{tag}"
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'^LATEST_RELEASE_URL = f"\{RELEASES_URL\}/tag/v[^"]+"$',
        f'LATEST_RELEASE_URL = f"{{RELEASES_URL}}/tag/{tag_ref}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if count == 0:
        manifest_backed = (
            'LATEST_RELEASE_URL = _release_proof_manifest()["release"]["github_release_url"]'
            in text
        )
        if manifest_backed:
            print("[release] latest release test derives from release_proof.toml")
            return
        raise SystemExit(f"ERROR: could not update LATEST_RELEASE_URL in {path}")
    if _write_text_if_changed(path, updated):
        print(f"[release] updated latest release test constant to {tag_ref}")


def update_release_proof_references_in_source(tag: str, docs_source: pathlib.Path) -> None:
    tag_ref = tag if tag.startswith("v") else f"v{tag}"
    release_url = github_release_url(tag_ref)
    script = REPO_ROOT / "tools" / "release_proof_report.py"
    if not script.exists():
        raise SystemExit(f"ERROR: release proof report script not found: {script}")

    run(
        [
            sys.executable,
            str(script),
            "--docs-source",
            str(docs_source),
            "--refresh-from-local",
            "--github-release-tag",
            tag_ref,
            "--github-release-url",
            release_url,
            "--render",
            "--check",
            "--compact",
        ],
        cwd=REPO_ROOT,
    )


def update_release_proof_references(tag: str) -> None:
    public_source = REPO_ROOT / "docs/source"

    docs_repo, source = find_docs_repository()
    if docs_repo:
        canonical_source = docs_repo / "docs/source"
        manifest = canonical_source / "data/release_proof.toml"
        if not manifest.exists():
            raise SystemExit(f"ERROR: canonical release proof manifest not found: {manifest}")
        update_release_proof_references_in_source(tag, canonical_source)
        sync_docs_source_mirror(canonical_source)
        return

    if public_source.exists():
        update_release_proof_references_in_source(tag, public_source)


def update_public_docs_mirror_stamp_from_current_tree() -> None:
    public_source = REPO_ROOT / "docs/source"
    script = REPO_ROOT / "tools" / "sync_docs_source.py"
    if not public_source.exists() or not script.exists():
        return
    run(
        [
            sys.executable,
            str(script),
            "--source",
            str(public_source),
            "--target",
            str(public_source),
            "--apply",
            "--quiet",
        ],
        cwd=REPO_ROOT,
    )


def update_public_release_references(tag: str, chosen_version: str, package_names: list[str]) -> None:
    update_docs_index_release_link(tag)
    update_changelog_release_entry(chosen_version, tag, package_names)
    update_public_demo_release_test(tag)
    update_release_proof_references(tag)


def update_public_release_references_for_guard(
    tag: str,
    chosen_version: str,
    package_names: list[str],
) -> None:
    """Update only release metadata tracked in this repository for pre-upload tests."""

    update_public_docs_index_release_link(tag)
    update_changelog_release_entry(chosen_version, tag, package_names)
    update_public_demo_release_test(tag)
    public_source = REPO_ROOT / "docs/source"
    if public_source.exists():
        update_release_proof_references_in_source(tag, public_source)
        update_public_docs_mirror_stamp_from_current_tree()


def generate_docs_in_docs_repository():
    docs_repo, source = find_docs_repository()
    if not docs_repo:
        print("[docs] docs repository not found; skipping --gen-docs")
        return
    print(f"[docs] generating docs in {docs_repo} (source={source})")
    commands = [
        ["uv", "sync", "--dev", "--group", "sphinx"],
        ["uv", "run", "python", "docs/gen-docs.py", "--agilab-repository", str(REPO_ROOT)],
    ]
    for cmd in commands:
        run(cmd, cwd=docs_repo)


def git_commit_docs_repository(chosen_version: str, *, push: bool = False):
    docs_repo, source = find_docs_repository()
    if not docs_repo:
        print("[git] docs repository not found; skipping docs repo commit")
        return

    if push:
        ensure_docs_repo_push_ready(docs_repo)

    dirty_paths = ensure_docs_repo_release_ready(docs_repo)
    if not dirty_paths:
        print("[git] no docs repository release changes to commit")
        return

    unique_paths = sorted(set(dirty_paths))
    run(["git", "add", "-A", "--", *unique_paths], cwd=docs_repo)
    diff_status = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=str(docs_repo),
        check=False,
    )
    if diff_status.returncode == 0:
        print("[git] no staged docs repository changes to commit")
        return

    run(["git", "commit", "-m", f"docs(release): sync docs for {chosen_version}"], cwd=docs_repo)
    print(f"[git] committed docs repository changes for {chosen_version}")
    if push:
        ensure_docs_repo_push_ready(docs_repo)
        branch = current_git_branch(docs_repo)
        remote = os.environ.get(DOCS_REPO_REMOTE_ENV, "origin")
        run(["git", "push", remote, branch], cwd=docs_repo)
        print(f"[git] pushed docs repository changes on {branch}")


def should_commit_docs_repository_after_release(
    *,
    docs_repo_ready: bool,
    gen_docs: bool,
    release_tag: str | None,
) -> bool:
    """Commit docs repo changes created by release reference updates or docs generation."""

    return docs_repo_ready and (gen_docs or release_tag is not None)


def git_paths_to_commit(include_docs: bool = False) -> list[str]:
    paths: list[str] = []
    for _, toml_path, project_dir in publishable_libs():
        if toml_path.exists():
            paths.append(str(toml_path.relative_to(REPO_ROOT)))
        readme = project_dir / "README.md"
        if readme.exists():
            paths.append(str(readme.relative_to(REPO_ROOT)))
    if UMBRELLA[1].exists():
        paths.append(str(UMBRELLA[1].relative_to(REPO_ROOT)))
    for pyproject_path in builtin_app_pyprojects():
        paths.append(str(pyproject_path.relative_to(REPO_ROOT)))
    umbrella_readme = UMBRELLA[2] / "README.md"
    if umbrella_readme.exists():
        paths.append(str(umbrella_readme.relative_to(REPO_ROOT)))
    for package_name in [name for name, *_ in publishable_libs()] + [UMBRELLA[0]]:
        badge_path = static_badge_path(package_name)
        if badge_path.exists():
            paths.append(str(badge_path.relative_to(REPO_ROOT)))
    for coverage_badge_path in sorted((REPO_ROOT / "badges").glob("coverage-*.svg")):
        paths.append(str(coverage_badge_path.relative_to(REPO_ROOT)))
    for rel_path in PUBLIC_RELEASE_METADATA_PATHS:
        release_path = REPO_ROOT / rel_path
        if release_path.exists():
            paths.append(rel_path)
    # Generated HTML stays out of git even when --gen-docs is requested.
    # Docs publication consumes the generated site separately from release metadata.
    # Preserve order but drop duplicates
    seen: set[str] = set()
    unique: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def current_git_branch(repo: pathlib.Path = REPO_ROOT) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(repo),
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def git_commit_version(chosen_version: str, include_docs: bool = False, *, push: bool = False):
    files = git_paths_to_commit(include_docs=include_docs)
    if not files:
        print("[git] nothing to commit")
        return
    app_prefixed = [f for f in files if f.startswith("src/agilab/apps/")]
    regular_files = [f for f in files if not f.startswith("src/agilab/apps/")]
    if regular_files:
        run(["git", "add", *regular_files], cwd=REPO_ROOT)
    if app_prefixed:
        # app paths can live under ignored parent globs; stage tracked updates only.
        run(["git", "add", "-u", *app_prefixed], cwd=REPO_ROOT)
    diff_status = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=str(REPO_ROOT),
        check=False,
    )
    if diff_status.returncode == 0:
        print("[git] no staged release metadata changes to commit")
        ensure_release_metadata_committed(files)
        return
    run(["git", "commit", "-m", f"chore(release): bump version to {chosen_version}"], cwd=REPO_ROOT)
    ensure_release_metadata_committed(files)
    print(f"[git] committed version bump to {chosen_version}")
    if push:
        branch = current_git_branch(REPO_ROOT)
        run(["git", "push", "origin", branch], cwd=REPO_ROOT)
        print(f"[git] pushed release metadata on {branch}")


def ensure_release_metadata_committed(files: list[str]) -> None:
    if not files:
        return
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--", *files],
        cwd=str(REPO_ROOT),
        check=False,
        text=True,
        capture_output=True,
    )
    dirty = [line for line in (proc.stdout or "").splitlines() if line.strip()]
    if dirty:
        formatted = "\n".join(f"  {line}" for line in dirty)
        raise SystemExit(
            "ERROR: release metadata paths are still dirty after the release commit. "
            "Refusing to tag a source tree that does not match the uploaded artifacts:\n"
            f"{formatted}"
        )


def git_reset_pyprojects():
    files = git_paths_to_commit()
    if not files:
        return
    try:
        run(["git", "checkout", "--", *files], cwd=REPO_ROOT)
        print("[git] reset release metadata edits")
    except Exception as e:
        print(f"[git] warning: could not reset release metadata files: {e}")


# ---------- Main ----------
def main():
    args = parse_args()
    cfg = make_cfg(args)
    upload_completed = False
    release_finalized = False
    release_metadata_committed = False
    release_references_updated = False
    docs_generated = False
    release_snapshot: Dict[pathlib.Path, bytes | None] | None = None
    docs_repo_ready = False

    print(f"[config] repo={cfg.repo} python={sys.executable} dist={cfg.dist} "
          f"skip_existing={cfg.skip_existing} retries={cfg.retries} clean={not cfg.skip_cleanup}")

    require_safe_pypi_release(cfg)
    if cfg.pypirc_check:
        assert_pypirc_has(cfg.repo)
    run_release_preflight(cfg)
    if cfg.gen_docs or (cfg.repo == "pypi" and cfg.git_tag):
        docs_repo, source = find_docs_repository()
        if docs_repo:
            if cfg.gen_docs:
                ensure_docs_repo_release_ready(docs_repo)
            docs_repo_ready = True

    # Validate explicit version if provided
    if cfg.version is not None and not re.fullmatch(r"\d+\.\d+\.\d+(?:\.post\d+)?", cfg.version):
        raise SystemExit("ERROR: Invalid --version format. Use X.Y.Z or X.Y.Z.postN")

    selected_packages = set(cfg.packages or ALL_PACKAGE_NAMES)
    unknown = selected_packages - set(ALL_PACKAGE_NAMES)
    if unknown:
        raise SystemExit(f"ERROR: Unknown package(s): {', '.join(sorted(unknown))}")

    selected_core_entries = [entry for entry in publishable_libs() if entry[0] in selected_packages]
    build_umbrella = UMBRELLA[0] in selected_packages
    if not selected_core_entries and not build_umbrella:
        raise SystemExit("ERROR: --packages must include at least one buildable package")

    selected_core_names = [name for name, *_ in selected_core_entries]
    version_targets = selected_core_names + ([UMBRELLA[0]] if build_umbrella else [])
    build_entries = selected_core_entries + ([UMBRELLA] if build_umbrella else [])

    if cfg.cleanup_only and cfg.delete_pypi_releases:
        delete_exact_pypi_releases(cfg, version_targets)
        return

    if cfg.version is not None:
        latest_existing = latest_existing_release(version_targets, cfg.repo)
        if latest_existing is not None and safe_ver(cfg.version) < safe_ver(latest_existing):
            raise SystemExit(
                f"ERROR: Explicit --version {cfg.version} is lower than existing release "
                f"{latest_existing} on {cfg.repo}. Choose a version >= the latest release."
            )

    removed_symlinks: list[tuple[pathlib.Path, str, bool]] = []
    try:
        if not cfg.dry_run and build_umbrella:
            removed_symlinks = remove_symlinks_for_umbrella()

        # Name hygiene
        sanitize_project_names([p for _, p, _ in selected_core_entries])

        package_versions, collisions = compute_package_versions(build_entries, cfg.repo, cfg.version)
        chosen = primary_release_version(package_versions)

        print("[plan] Package versions:")
        for name in version_targets:
            print(f"  - {name}: {package_versions[name]}")
        date_tag = normalize_base(chosen)  # primary date base (YYYY.MM.DD)
        print(f"[plan] Tag base (UTC): {date_tag}")
        planned_tag = compute_date_tag() if cfg.repo == "pypi" and cfg.git_tag else None
        if cfg.dry_run:
            print("[dry-run] Collisions per package:")
            for n in version_targets:
                hits = collisions.get(n) or []
                print(f"  - {n}: {', '.join(hits) if hits else '(none)'}")

        # Cleanup-only path
        if cfg.cleanup_only:
            cleanup_leave_latest(cfg, version_targets)
            return

        # Optional purge BEFORE
        if cfg.purge_before:
            cleanup_leave_latest(cfg, version_targets)

        # Apply version + pin internal deps, then build
        release_snapshot = capture_release_file_state(git_paths_to_commit(include_docs=cfg.gen_docs))
        current_versions = {name: get_version_from_pyproject(toml) for name, toml, _ in publishable_libs()}
        pins = current_versions.copy()
        pins.update(package_versions)

        # Update README badges before building so the packaged long_description
        # and uploaded PyPI page embed the new versioned badge immediately.
        update_selected_badges(selected_core_entries, build_umbrella)

        all_files: List[str] = []

        # core
        for name, toml, project in selected_core_entries:
            package_version = package_versions[name]
            try:
                set_version_in_pyproject(toml, package_version)
            except Exception as e:
                raise SystemExit(f"fatal: Could not update version in {toml}\n{e}")
            pin_internal_deps_for_package(name, toml, pins)
            update_release_badge_for_project(name, toml, project)
            dist_kind = effective_dist_kind(name, cfg.dist)
            if cfg.dry_run:
                print(f"[build] {name}: (dry-run would build {dist_kind} artifacts for {package_version})")
                files = []
            else:
                uv_build_project(project, dist_kind)
                files = dist_files(project)
                if files:
                    print(f"[build] {name}: {', '.join(files)}")
            all_files.extend(files)

        # umbrella
        if build_umbrella:
            package_version = package_versions[UMBRELLA[0]]
            _, umbrella_toml, _ = UMBRELLA
            try:
                set_version_in_pyproject(umbrella_toml, package_version)
            except Exception as e:
                raise SystemExit(f"fatal: Could not update version in {umbrella_toml}\n{e}")
            pin_internal_deps_for_package(UMBRELLA[0], umbrella_toml, pins)
            update_release_badge_for_project(UMBRELLA[0], umbrella_toml, UMBRELLA[2])
            if cfg.dry_run:
                print(f"[build] umbrella: (dry-run would build {cfg.dist} artifacts for {package_version})")
                root_files = []
            else:
                uv_build_repo_root(cfg.dist)
                root_files = dist_files_root()
                if root_files:
                    print(f"[build] umbrella: {', '.join(root_files)}")
            all_files.extend(root_files)

        # Dry-run end
        if cfg.dry_run:
            print("[dry-run] Would twine check & upload:")
            for f in all_files:
                print("  -", f)
            return

        run_pre_upload_external_install_guard(cfg, all_files)
        run_pre_upload_release_guard(
            cfg,
            planned_tag=planned_tag,
            chosen_version=chosen,
            version_targets=version_targets,
        )

        if cfg.repo == "pypi" and cfg.gen_docs:
            generate_docs_in_docs_repository()
            docs_generated = True

        run_release_coverage_workflow_prerequisite(cfg)

        # Twine
        twine_check(all_files)
        twine_upload(all_files, cfg.repo, cfg.skip_existing, cfg.retries)
        if not cfg.dry_run and UPLOAD_COLLISION_DETECTED and UPLOAD_SUCCESS_COUNT == 0:
            if cfg.repo == "pypi":
                raise SystemExit(
                    f"ERROR: PyPI upload reported a version collision for {chosen}. "
                    "Automatic .postN PyPI version bumps are disabled; choose an explicit new release version."
                )
            print('[auto-bump] upload collision detected; bumping to next .postN and retrying upload...')
            package_versions2 = {
                name: next_free_post_for_all([name], cfg.repo, normalize_base(version))
                for name, version in package_versions.items()
            }
            chosen2 = primary_release_version(package_versions2)
            pins2 = pins.copy()
            pins2.update(package_versions2)
            update_selected_badges(selected_core_entries, build_umbrella)
            all_files2: List[str] = []
            for name, toml, project in selected_core_entries:
                set_version_in_pyproject(toml, package_versions2[name])
                pin_internal_deps_for_package(name, toml, pins2)
                update_release_badge_for_project(name, toml, project)
                uv_build_project(project, effective_dist_kind(name, cfg.dist))
                all_files2.extend(dist_files(project))
            if build_umbrella:
                _, umbrella_toml, _ = UMBRELLA
                set_version_in_pyproject(umbrella_toml, package_versions2[UMBRELLA[0]])
                pin_internal_deps_for_package(UMBRELLA[0], umbrella_toml, pins2)
                update_release_badge_for_project(UMBRELLA[0], umbrella_toml, UMBRELLA[2])
                uv_build_repo_root(cfg.dist)
                all_files2.extend(dist_files_root())
            run_pre_upload_external_install_guard(cfg, all_files2)
            run_pre_upload_release_guard(
                cfg,
                planned_tag=planned_tag,
                chosen_version=chosen2,
                version_targets=version_targets,
            )
            twine_check(all_files2)
            globals()['UPLOAD_COLLISION_DETECTED'] = False
            globals()['UPLOAD_SUCCESS_COUNT'] = 0
            twine_upload(all_files2, cfg.repo, cfg.skip_existing, cfg.retries)
            chosen = chosen2
            package_versions = package_versions2

        if not cfg.dry_run:
            update_selected_badges(selected_core_entries, build_umbrella)
            upload_completed = True

        # Yank (optional, PyPI only)
        if cfg.yank_previous:
            yank_previous_versions(cfg, version_targets, chosen)

        if cfg.delete_pypi_releases:
            delete_exact_pypi_releases(cfg, version_targets)

        # Purge AFTER (optional)
        if cfg.purge_after:
            cleanup_leave_latest(cfg, version_targets)

        if cfg.gen_docs and not docs_generated:
            if cfg.dry_run:
                print("[docs] --gen-docs requested; skipping because this is a dry-run")
            else:
                generate_docs_in_docs_repository()

        # Git tag/commit (optional)
        if cfg.git_commit_version or (cfg.repo == "pypi" and cfg.git_tag):
            with defer_sigint("release metadata finalization") as deferred_interrupt:
                tag = planned_tag if cfg.repo == "pypi" and cfg.git_tag else None
                if tag is not None and not release_references_updated:
                    update_public_release_references(tag, chosen, version_targets)
                    release_references_updated = True
                if cfg.git_commit_version and not release_metadata_committed:
                    git_commit_version(chosen, include_docs=cfg.gen_docs, push=True)
                    if should_commit_docs_repository_after_release(
                        docs_repo_ready=docs_repo_ready,
                        gen_docs=cfg.gen_docs,
                        release_tag=tag,
                    ):
                        git_commit_docs_repository(chosen, push=True)
                if tag is not None:
                    create_and_push_tag(tag, include_docs_repo=bool(docs_repo_ready))
                    create_or_update_github_release(tag, chosen, version_targets)
                    release_finalized = True
                    if cfg.delete_former_github_release:
                        delete_former_github_release(tag)
            release_finalized = True
            if deferred_interrupt["value"]:
                raise KeyboardInterrupt("Interrupted after release metadata finalization")
        else:
            release_finalized = upload_completed

    finally:
        if removed_symlinks:
            restore_symlinks(removed_symlinks)
        if cfg.dry_run and release_snapshot is not None:
            restore_release_file_state(release_snapshot)
        if cfg.git_reset_on_failure and not cfg.dry_run and not release_finalized:
            git_reset_pyprojects()


if __name__ == "__main__":
    main()
