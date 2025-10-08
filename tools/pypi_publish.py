#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Local publisher for TestPyPI / PyPI using ~/.pypirc.

Features
- --repo {testpypi,pypi} selects destination; credentials & URL read from ~/.pypirc.
- If --version omitted, auto-compute a single .postN that is unused by ALL core packages.
- When --repo pypi, always create & push git tag 'v<version>'.
- Uses uv to build wheels; twine to check & upload.
- Optional: --dry-run to preview planned version and collisions.
- Optional: --no-pypirc-check to skip ~/.pypirc preflight.

Examples
  python local_publish.py --repo testpypi                # auto-picks next .postN
  python local_publish.py --repo testpypi --version 0.7.4
  python local_publish.py --repo pypi                    # auto .postN + push tag
  python local_publish.py --repo testpypi --dry-run
"""

from __future__ import annotations

import argparse
import os
import configparser
import glob
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.request
from typing import Dict, List, Tuple
from datetime import datetime, timezone
from tomlkit import parse as toml_parse, dumps as toml_dumps  # type: ignore


# third-party (installed on-demand if missing)
try:
    from packaging.version import Version, InvalidVersion
except Exception:
    subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "packaging"], check=True)
    from packaging.version import Version, InvalidVersion

# ------------------------- CLI -------------------------
def parse_args():
    ap = argparse.ArgumentParser(description="Publish wheels to TestPyPI or PyPI using ~/.pypirc")
    ap.add_argument("--repo", choices=["testpypi", "pypi"], required=True,
                    help="Target repository section name in ~/.pypirc")
    ap.add_argument("--version",
                    help="Base version to publish: X.Y.Z or X.Y.Z.postN (leading 'v' allowed). If omitted, a unified .postN is computed.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show chosen version & collisions; do not build or upload.")
    ap.add_argument("--verbose", action="store_true",
                    help="Verbose mode: echo cleanup commands and enable verbose output for pypi-cleanup.")
    ap.add_argument("--no-pypirc-check", dest="pypirc_check", action="store_false",
                    help="Disable ~/.pypirc preflight (enabled by default).")
        # Cleanup & auth options (backward-compatible aliases)
    ap.add_argument("--clean", action="store_true",
                    help="Interactively delete versions on TestPyPI before publishing.")
    ap.add_argument("--leave-most-recent", dest="clean_leave_latest", action="store_true",
                    help="Delete all published versions for each package except the most recent one on the target repo.")
    ap.add_argument("--days", "--clean-days", dest="clean_days", type=int, default=None,
                    help="Only delete releases uploaded in the last N days (omit to consider all).")
    ap.add_argument("--delete-project", "--clean-delete-project", dest="clean_delete_project",
                    action="store_true",
                    help="Pass --delete-project to pypi-cleanup (destructive: deletes all matched releases).")
    # Dedicated cleanup credentials (PyPI web login requires account password, not API token)
    ap.add_argument("--cleanup-username", dest="cleanup_username", default=None,
                    help="pypi-cleanup login (PyPI account username; not __token__).")
    ap.add_argument("--cleanup-password", dest="cleanup_password", default=None,
                    help="pypi-cleanup password (PyPI account password; tokens are not accepted by web login).")
    ap.add_argument("--skip-cleanup", dest="skip_cleanup", action="store_true",
                    help="Skip pypi-cleanup pruning pre/post upload (avoids 2FA prompts and hangs).")
    ap.add_argument("--cleanup-timeout", dest="cleanup_timeout", type=int, default=60,
                    help="Timeout in seconds for pypi-cleanup calls (0 disables). Prevents hangs on 2FA prompts.")
    # Unified Twine auth (optional): avoids repeated prompts
    ap.add_argument("--twine-username", dest="twine_user", default=None,
                    help="Twine username to upload to {testpypi,pypi}. Overrides ~/.pypirc if set.")
    ap.add_argument("--twine-password", dest="twine_pass", default=None,
                    help="Twine password/token. If omitted but username is set, you will be prompted once.")
    ap.add_argument("--yank-previous", action="store_true",
                    help="On PyPI, yank previously released versions (older than the chosen version) after a successful upload.")
    return ap.parse_args()

args = parse_args()
TARGET: str = args.repo
BASE_VERSION: str | None = args.version.strip().lstrip("v") if args.version else None
DO_PYPIRC_CHECK: bool = args.pypirc_check
DRY_RUN: bool = args.dry_run
VERBOSE: bool = args.verbose
TWINE_USER: str | None = args.twine_user
TWINE_PASS: str | None = args.twine_pass
YANK_PREVIOUS: bool = args.yank_previous
SKIP_CLEANUP: bool = args.skip_cleanup
CLEANUP_TIMEOUT: int = max(0, int(getattr(args, "cleanup_timeout", 60) or 0))

# If a version was provided explicitly, enforce a strict format before proceeding.
# Accepted: 'X.Y.Z' or 'X.Y.Z.postN' (after stripping an optional leading 'v').
if BASE_VERSION is not None:
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:\.post\d+)?", BASE_VERSION):
        raise SystemExit(
            "ERROR: Invalid --version format.\n"
            "       Use 'X.Y.Z' or 'X.Y.Z.postN' (leading 'v' allowed). Examples: 0.8.15, 0.8.15.post1\n"
        )

# Enforce explicit behavior for Twine auth: both-or-none (fallback to ~/.pypirc when none).
if (TWINE_USER and not TWINE_PASS) or (TWINE_PASS and not TWINE_USER):
    raise SystemExit(
        "[auth] Provide both --twine-username and --twine-password, or neither.\n"
        "       When neither is provided, twine will read credentials from ~/.pypirc."
    )

# Enforce token auth for PyPI: basic auth is no longer supported.
if TARGET == "pypi" and TWINE_USER and TWINE_USER != "__token__":
    raise SystemExit(
        "[auth] PyPI requires API tokens. Use --twine-username __token__ and provide an API token.\n"
        "        See https://pypi.org/help/#apitoken"
    )
if TARGET == "pypi" and TWINE_PASS and not str(TWINE_PASS).startswith("pypi-"):
    raise SystemExit(
        "[auth] Invalid credential for PyPI. Provide a token starting with 'pypi-' or configure ~/.pypirc."
    )

# ------------------------- Repo layout -------------------------
REPO_ROOT = pathlib.Path.cwd().resolve()

# Core packages: (name, pyproject.toml, project_dir)
CORE: List[Tuple[str, pathlib.Path, pathlib.Path]] = [
    ("agi-env",     REPO_ROOT / "src/agilab/core/agi-env/pyproject.toml",     REPO_ROOT / "src/agilab/core/agi-env"),
    ("agi-node",    REPO_ROOT / "src/agilab/core/agi-node/pyproject.toml",    REPO_ROOT / "src/agilab/core/agi-node"),
    ("agi-cluster", REPO_ROOT / "src/agilab/core/agi-cluster/pyproject.toml", REPO_ROOT / "src/agilab/core/agi-cluster"),
    ("agi-core",    REPO_ROOT / "src/agilab/core/agi-core/pyproject.toml",    REPO_ROOT / "src/agilab/core/agi-core"),
]
UMBRELLA = ("agilab", REPO_ROOT / "pyproject.toml", REPO_ROOT)

# API endpoints for version discovery
JSON_API = {
    "testpypi": "https://test.pypi.org/pypi/{name}/json",
    "pypi":     "https://pypi.org/pypi/{name}/json",
}

# ------------------------- Utils -------------------------
def run(cmd: List[str], cwd: pathlib.Path | None = None, env: dict | None = None):
    print("+", " ".join(map(str, cmd)))
    merged_env = os.environ.copy()
    if parse_argscleanenv:
        merged_env.update(env)
    subprocess.run(cmd, cwd=str(cwd or pathlib.Path.cwd()), check=True, text=True, env=merged_env)


def cleanup_leave_latest(packages):
    if not args.clean_leave_latest or SKIP_CLEANUP:
        return

    if TARGET == "testpypi":
        print("[cleanup] Skipping cleanup on TestPyPI to avoid interactive login/timeouts. Use --cleanup-username/--cleanup-password if you need it explicitly.")
        return

    host = "https://pypi.org/"
    if TARGET == "testpypi":
        host = "https://test.pypi.org/"

    for pkg in packages:
        cmd = [
            "pypi-cleanup",
            "--package", pkg,
            "--leave-most-recent",
            "--do-it",
            "-y",
            "--host", host,
        ]
        # Auth strategy for pypi-cleanup:
        # - PyPI web login used by pypi-cleanup REQUIRES account username+password (API tokens are NOT accepted).
        # - Prefer explicit --cleanup-username/--cleanup-password when provided.
        # - Else fall back to ~/.pypirc entries if they contain a real username (not __token__).
        # - As a last resort, --user sets only username; but without a password pypi-cleanup will prompt and likely fail.
        user_from_pypirc = None
        pwd_from_pypirc = None
        # Env overrides for cleanup (not used by Twine): allow PYPI_USERNAME + PYPI_CLEANUP_PASSWORD (preferred)
        # Back-compat: also accept PYPI_PASSWORD if set
        env_cleanup_user = os.getenv("PYPI_USERNAME")
        env_cleanup_pass = os.getenv("PYPI_CLEANUP_PASSWORD") or os.getenv("PYPI_PASSWORD")
        # Ignore placeholder prompts that may leak in from IDE configs
        if env_cleanup_user and env_cleanup_user.startswith("$Prompt:"):
            env_cleanup_user = None
        if env_cleanup_pass and env_cleanup_pass.startswith("$Prompt:"):
            env_cleanup_pass = None
        try:
            cfg = configparser.RawConfigParser()
            cfg.read(pathlib.Path.home() / ".pypirc")
            if cfg.has_section(TARGET):
                user_from_pypirc = cfg.get(TARGET, "username", fallback=None)
                pwd_from_pypirc = cfg.get(TARGET, "password", fallback=None)
            # Dedicated cleanup section support to avoid breaking Twine token uploads
            cleanup_sections = [
                f"{TARGET}_cleanup", f"{TARGET}-cleanup",
                "pypi_cleanup", "pypi-cleanup",
            ]
            for sec in cleanup_sections:
                if cfg.has_section(sec):
                    # Use the first matching cleanup section
                    user_from_pypirc_cleanup = cfg.get(sec, "username", fallback=None)
                    pwd_from_pypirc_cleanup = cfg.get(sec, "password", fallback=None)
                    # Override main-section credentials for cleanup purposes only
                    if user_from_pypirc_cleanup:
                        user_from_pypirc = user_from_pypirc_cleanup
                    if pwd_from_pypirc_cleanup:
                        pwd_from_pypirc = pwd_from_pypirc_cleanup
                    break
        except Exception:
            pass
        def valid_user(val: str | None) -> str | None:
            if not val:
                return None
            val = val.strip()
            if not val or val.startswith("$Prompt:"):
                return None
            if val == "__token__":
                return None
            return val

        def valid_pass(val: str | None) -> str | None:
            if not val:
                return None
            val = val.strip()
            if not val or val.startswith("$Prompt:"):
                return None
            return val

        cleanup_user = (
            valid_user(args.cleanup_username)
            or valid_user(user_from_pypirc)
            or valid_user(env_cleanup_user)
        )
        cleanup_pass = (
            valid_pass(args.cleanup_password)
            or valid_pass(pwd_from_pypirc)
            or valid_pass(env_cleanup_pass)
        )

        # Cleanup login requires a real account username/password (web form).
        # If we only have an API token, skip gracefully instead of prompting.
        token_like = cleanup_pass and str(cleanup_pass).startswith("pypi-")
        if not cleanup_user:
            print("[cleanup] Skipping cleanup: no cleanup username available.\n"
                  "          Configure ~/.pypirc with a real account username/password or pass --cleanup-username/--cleanup-password.")
            return
        if not cleanup_pass or token_like:
            print("[cleanup] Skipping cleanup: requires a real account password (pypi-cleanup uses the web login).\n"
                  "          Provide --cleanup-password/--cleanup-username or set PYPI_CLEANUP_PASSWORD/PYPI_USERNAME.")
            return

        if cleanup_user:
            cmd.extend(["--username", cleanup_user])
        if args.clean_days is not None:
            cmd.extend(["--days", str(args.clean_days)])
        if args.clean_delete_project:
            cmd.append("--delete-project")
        # Do not pass a regex by default; --leave-most-recent-only works across all versions
        print(f"[cleanup] Keeping only latest release for {pkg} on {TARGET}")
        if VERBOSE:
            cmd.append("-v")
            print("[cleanup] Command:", " ".join(cmd))
        # Prepare env for non-interactive auth (pypi-cleanup reads PYPI_USERNAME/PYPI_PASSWORD)
        cleanup_env = {}
        # Resolve username/password from explicit flags or ~/.pypirc
        uname = cleanup_user
        pword = cleanup_pass
        if uname:
            cleanup_env["PYPI_USERNAME"] = uname
        if pword:
            cleanup_env["PYPI_PASSWORD"] = pword
        # Allow cleanup to fail without aborting the publish (e.g., 404 already deleted).
        # Capture output to avoid noisy tracebacks; summarize on failure.
        # Build subprocess.run kwargs separately; pass 'cmd' as a positional argument
        run_kwargs = dict(
            cwd=str(REPO_ROOT),
            env={**os.environ, **cleanup_env} if cleanup_env else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if CLEANUP_TIMEOUT:
            run_kwargs["timeout"] = CLEANUP_TIMEOUT
        try:
            proc = subprocess.run(cmd, **run_kwargs)
        except subprocess.TimeoutExpired:
            print(f"[cleanup] warning: pypi-cleanup timed out after {CLEANUP_TIMEOUT}s for {pkg}; skipping.")
            return
        if proc.returncode != 0:
            hint = ""
            body = (proc.stdout or "") + "\n" + (proc.stderr or "")
            if "404" in body:
                hint = " (HTTP 404)"
            print(f"[cleanup] warning: pypi-cleanup failed for {pkg}{hint}; continuing.")
            if VERBOSE:
                # Print only the last few lines to aid debugging without flooding logs
                tail = "\n".join([ln for ln in body.splitlines()[-8:]])
                if tail.strip():
                    print("[cleanup] tail:\n" + tail)

def load_doc(p: pathlib.Path):
    return toml_parse(p.read_text(encoding="utf-8"))

def save_doc(p: pathlib.Path, doc):
    p.write_text(toml_dumps(doc), encoding="utf-8")

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

# ------------------------- .pypirc preflight (optional) -------------------------
def assert_pypirc_has(repo_name: str):
    cfg = configparser.RawConfigParser()
    p = pathlib.Path.home() / ".pypirc"
    if not p.exists():
        sys.exit(f"ERROR: {p} not found. Create it with a [{repo_name}] section.")
    cfg.read(p)
    if not cfg.has_section(repo_name):
        sys.exit(f"ERROR: {p} missing section [{repo_name}]. Add it to use --repo {repo_name}.")

if DO_PYPIRC_CHECK:
    assert_pypirc_has(TARGET)

# ------------------------- Version discovery -------------------------
def pypi_releases(name: str, repo_target: str) -> set[str]:
    url = JSON_API[repo_target].format(name=name)
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.load(r) or {}
        rels = set((data.get("releases") or {}).keys())
        return rels
    except Exception:
        return set()

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
        # Unusual versions: treat as very low to avoid accidental max
        return Version("0")

def max_base_across_packages(package_names: List[str], repo_target: str) -> str:
    all_versions = set()
    for n in package_names:
        all_versions |= pypi_releases(n, repo_target)
    if not all_versions:
        return "0.1.0"  # seed base if nothing published yet
    bases = {normalize_base(v) for v in all_versions if v}
    return max(bases, key=safe_ver)

def next_free_post_for_all(package_names: List[str], repo_target: str, base: str) -> str:
    # Build a per-package index for speed
    per_pkg = {n: pypi_releases(n, repo_target) for n in package_names}

    # Start from > max post seen for any package (safety)
    k_start = 1
    for releases in per_pkg.values():
        max_post = 0
        if base in releases:
            max_post = 0
        for v in releases:
            b, post = split_base_and_post(v)
            if b == base and post is not None and post > max_post:
                max_post = post
        if max_post + 1 > k_start:
            k_start = max_post + 1

    k = k_start
    while True:
        candidate = f"{base}.post{k}"
        if all(candidate not in per_pkg[n] for n in package_names):
            return candidate
        k += 1

def compute_unified_version(core_names: List[str], repo_target: str, base_version: str | None) -> Tuple[str, Dict[str, List[str]]]:
    """
    Decide the unified version to publish for all core packages.

    Priority:
      1) If --version is provided, try that exact version first across all packages.
         - If no package already has that exact version, use it as-is.
         - If any package already has it, fall back to computing the next free '.postK' from its base.
      2) If --version is omitted, compute the next free '.postK' from the max base across packages.

    Returns (chosen_version, collisions) where collisions maps package -> versions that forced bumping.
    """
    collisions: Dict[str, List[str]] = {n: [] for n in core_names}

    if base_version:
        # When a base is provided (e.g., date-based 'YYYY.MM.DD'), use it and
        # auto-bump with '.postN' if any package already has that exact version.
        provided = base_version
        provided_base = normalize_base(provided)
        existing_by_pkg = {n: pypi_releases(n, repo_target) for n in core_names}
        provided_in_use = any(provided in rels for rels in existing_by_pkg.values())
        if not provided_in_use:
            chosen = provided
            base = provided_base
        else:
            # Fall back to next free post from the provided base
            base = provided_base
            chosen = next_free_post_for_all(core_names, repo_target, base)
    else:
        base = max_base_across_packages(core_names, repo_target)
        chosen = next_free_post_for_all(core_names, repo_target, base)

    # Fill collisions detail for reporting
    for n in core_names:
        rels = pypi_releases(n, repo_target)
        hits: List[str] = []
        if base in rels:
            hits.append(base)
        for v in rels:
            b, post = split_base_and_post(v)
            if b == base and v != base and safe_ver(v) < safe_ver(chosen):
                hits.append(v)
        collisions[n] = sorted(set(hits), key=safe_ver)

    return chosen, collisions

# ------------------------- TOML ops -------------------------
def set_project_version(pyproject: pathlib.Path, version: str):
    doc = load_doc(pyproject)
    proj = doc.get("project") or {}
    proj["version"] = version
    proj["name"] = clean_name(proj.get("name", ""))
    doc["project"] = proj
    save_doc(pyproject, doc)

def pin_deps(pyproject: pathlib.Path, pins: Dict[str, str]) -> bool:
    if not pyproject.exists():
        return False
    doc = load_doc(pyproject)
    proj = doc.get("project") or {}
    changed = False

    def pin_list(arr):
        nonlocal changed
        out = []
        for dep in arr:
            s = str(dep)
            parts = s.split(";", 1)
            left, marker = parts[0].strip(), (";" + parts[1] if len(parts) == 2 else "")
            m = re.match(r"^([A-Za-z0-9_.-]+)(\[[^\]]+\])?", left)
            if m:
                pkg, extras = m.group(1), (m.group(2) or "")
                if pkg in pins:
                    s = f"{pkg}{extras}=={pins[pkg]}{marker}"
                    changed = True
            out.append(s)
        return out

    if "dependencies" in proj and proj["dependencies"] is not None:
        proj["dependencies"] = pin_list(proj["dependencies"])
    if "optional-dependencies" in proj and proj["optional-dependencies"] is not None:
        for g, arr in list(proj["optional-dependencies"].items()):
            proj["optional-dependencies"][g] = pin_list(arr)

    if changed:
        doc["project"] = proj
        save_doc(pyproject, doc)
    return changed

# ------------------------- Build & upload -------------------------
def uv_build_project(project_dir: pathlib.Path):
    for sub in ("dist", "build"):
        d = project_dir / sub
        if d.exists():
            shutil.rmtree(d)
    run(["uv", "build", "--project", str(project_dir), "--wheel"], cwd=REPO_ROOT)

def dist_files(project_dir: pathlib.Path) -> List[str]:
    return sorted(glob.glob(str((project_dir / "dist" / "*").resolve())))

def twine_check(files: List[str]):
    if not files:
        raise SystemExit("No artifacts to check")
    run([sys.executable, "-m", "twine", "check", *files], cwd=REPO_ROOT)

def twine_upload(files: List[str], repo: str):
    if not files:
        raise SystemExit("No artifacts to upload")
    print(f"+ twine upload -r {repo} ({len(files)} files)")
    cmd = [sys.executable, "-m", "twine", "upload", "--non-interactive", "--skip-existing", "-r", repo]
    # Avoid exposing secrets on the process list: prefer env vars
    upload_env = {}
    if TWINE_USER:
        upload_env["TWINE_USERNAME"] = TWINE_USER
    if TWINE_PASS:
        upload_env["TWINE_PASSWORD"] = TWINE_PASS
    cmd.extend(files)
    run(cmd, cwd=REPO_ROOT, env=upload_env)

# Umbrella
def uv_build_repo_root():
    for sub in ("dist", "build"):
        d = REPO_ROOT / sub
        if d.exists():
            shutil.rmtree(d)
    run(["uv", "build", "--wheel"], cwd=REPO_ROOT)

def dist_files_root() -> List[str]:
    return sorted(glob.glob(str((REPO_ROOT / "dist" / "*").resolve())))

def remove_symlinks_for_umbrella() -> list[tuple[pathlib.Path, str, bool]]:
    """
    Remove only top-level app/page symlinks before building the umbrella wheel.

    We intentionally avoid a recursive scan so we don't touch user-local
    virtualenvs (e.g., */.venv/bin/python symlinks) or other nested links
    that are already excluded by packaging config. The goal here is to drop
    the immediate app/page placeholders that point outside the tree.

    Returns a list of (path, target, is_dir) entries so we can restore them.
    """
    removed: list[tuple[pathlib.Path, str, bool]] = []
    for rel in ("src/agilab/apps", "src/agilab/apps-pages"):
        base = REPO_ROOT / rel
        if not base.exists():
            continue
        try:
            for p in base.iterdir():
                # Only remove the direct children that are symlinks
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
            # Best-effort cleanup; ignore permission or race errors
            pass
    return removed

def restore_symlinks(entries: list[tuple[pathlib.Path, str, bool]]):
    for path, target, is_dir in entries:
        try:
            if not target:
                # No stored target; skip restoration
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(target, path, target_is_directory=is_dir)
            print(f"[symlink] restored {path} -> {target}")
        except Exception as e:
            print(f"[symlink] warning: failed to restore {path}: {e}")

# Git tagging when publishing to PyPI
def _tag_exists(tag: str) -> bool:
    try:
        subprocess.run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"], cwd=REPO_ROOT, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False


def compute_date_tag() -> str:
    """
    Return a date-based tag in UTC as YYYY.MM.DD.
    If that tag already exists, append "-2", "-3", … until unique.
    """
    base = datetime.now(timezone.utc).strftime("%Y.%m.%d")
    tag = base
    n = 2
    while _tag_exists(tag):
        tag = f"{base}-{n}"
        n += 1
    return tag


def create_and_push_tag(tag: str):
    run(["git", "tag", "-a", tag, "-m", f"Release {tag}"], cwd=REPO_ROOT)
    run(["git", "push", "origin", tag], cwd=REPO_ROOT)
    print(f"[git] created and pushed {tag}")

# ------------------------- Main -------------------------
def main():
    if not TARGET:
        print("usage: pypi_publish.py --repo {testpypi|pypi} [options]", file=sys.stderr)
        raise SystemExit("ERROR: --repo is required")

    removed_symlinks: list[tuple[pathlib.Path, str, bool]] = []
    try:
        if not DRY_RUN:
            removed_symlinks = remove_symlinks_for_umbrella()

        # Auth preflight (best-effort): verify token format and print assumptions
        if TARGET == "pypi":
            print("[preflight] Target: PyPI (batch upload across core + umbrella)")
            if TWINE_USER:
                print(f"[preflight] TWINE_USERNAME set: {TWINE_USER}")
            else:
                print("[preflight] TWINE_USERNAME not set; relying on ~/.pypirc")
            if TWINE_PASS:
                shown = (str(TWINE_PASS)[:8] + "…") if len(str(TWINE_PASS)) > 8 else "(short)"
                print(f"[preflight] TWINE_PASSWORD token prefix: {shown}")
            print("[preflight] Note: a batch upload of multiple projects to PyPI typically requires an account-wide token.\n"
                  "           If you encounter 403 Forbidden, verify your token scope in PyPI settings.")

        # Basic hygiene on names
        sanitize_project_names([p for _, p, _ in CORE])

        core_names = [n for n, _, __ in CORE]

        # Switch to date-based versioning: use UTC date as the base (YYYY.MM.DD)
        date_tag = compute_date_tag()
        chosen, collisions = compute_unified_version(core_names, TARGET, date_tag)
        print(f"[plan] Unified version: {chosen}")
        print(f"[plan] Tag (UTC): {date_tag}")
        if DRY_RUN:
            print("[dry-run] Collisions that forced bump (per package):")
            for n in core_names:
                hits = collisions[n]
                print(f"  - {n}: {', '.join(hits) if hits else '(none)'}")
        elif args.clean_leave_latest:
            cleanup_leave_latest(core_names + [UMBRELLA[0]])

        # Pin internal deps to the chosen version and build each core
        pins = {n: chosen for n, _, __ in CORE}
        all_files: List[str] = []
        for name, toml, project in CORE:
            set_project_version(toml, chosen)
            pin_deps(toml, pins)
            uv_build_project(project)
            files = dist_files(project)
            print(f"Successfully built {', '.join(files) if files else '(no files)'}")
            all_files.extend(files)

        # Umbrella package
        _, umbrella_toml, _ = UMBRELLA
        set_project_version(umbrella_toml, chosen)
        pin_deps(umbrella_toml, pins)

        uv_build_repo_root()
        root_files = dist_files_root()
        print(f"Successfully built {', '.join(root_files) if root_files else '(no files)'}")
        all_files.extend(root_files)

        # Single pass metadata check and upload for all artifacts to minimize auth and network roundtrips
        if DRY_RUN:
            print("[dry-run] Artifacts that would be uploaded in a single twine call:")
            for f in all_files:
                print(f"  - {f}")
            cmd_preview = ["twine", "upload", "--non-interactive", "--skip-existing", "-r", TARGET]
            if TWINE_USER:
                cmd_preview += ["-u", TWINE_USER]
            if TWINE_PASS:
                cmd_preview += ["-p", "******"]
            cmd_preview += all_files
            print("[dry-run] Command:")
            print("  ", " ".join(cmd_preview))
            return

        if args.clean_leave_latest and not DRY_RUN:
            cleanup_leave_latest(core_names + [UMBRELLA[0]])

        twine_check(all_files)
        twine_upload(all_files, TARGET)

        if TARGET == "pypi" and YANK_PREVIOUS:
            yank_previous_versions(core_names + [UMBRELLA[0]], TARGET, chosen)

        if TARGET == "pypi":
            create_and_push_tag(date_tag)
    finally:
        if removed_symlinks:
            restore_symlinks(removed_symlinks)


def yank_previous_versions(packages: list[str], repo: str, chosen: str):
    """Yank previously released versions on PyPI that are older than 'chosen'."""
    if repo != "pypi":
        return
    print(f"[yank] Attempting to yank previous versions older than {chosen} on {repo}")
    for name in packages:
        rels = sorted(pypi_releases(name, repo), key=safe_ver)
        for v in rels:
            if safe_ver(v) < safe_ver(chosen):
                cmd = [sys.executable, "-m", "twine", "yank", "-r", repo, name, v, "-y"]
                yank_env = {}
                if TWINE_USER:
                    yank_env["TWINE_USERNAME"] = TWINE_USER
                if TWINE_PASS:
                    yank_env["TWINE_PASSWORD"] = TWINE_PASS
                try:
                    run(cmd, cwd=REPO_ROOT, env=yank_env)
                    print(f"[yank] Yanked {name} {v}")
                except Exception as e:
                    print(f"[yank] warning: could not yank {name} {v}: {e}")

if __name__ == "__main__":
    main()
