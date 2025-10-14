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
    ap.add_argument("--days", "--clean-days", dest="clean_days", type=int, default=None,
                    help="Only delete releases uploaded in the last N days (omit to consider all).")
    ap.add_argument("--delete-project", "--clean-delete-project", dest="clean_delete_project",
                    action="store_true",
                    help="Pass --delete-project to pypi-cleanup (destructive: deletes all matched releases).")
    # Dedicated cleanup credentials (PyPI web login requires account password, not API token)
    ap.add_argument("--cleanup", dest="cleanup_creds", metavar="USER:PASS", default=None,
                    help="Credentials for pypi-cleanup web login in the form 'username:password'.")
    ap.add_argument("--skip-cleanup", dest="skip_cleanup", action="store_true",
                    help="Skip pypi-cleanup pruning pre/post upload (avoids 2FA prompts and hangs).")
    ap.add_argument("--cleanup-timeout", dest="cleanup_timeout", type=int, default=60,
                    help="Timeout in seconds for pypi-cleanup calls (0 disables). Prevents hangs on 2FA prompts.")
    # Back-compat: accept split credentials as separate flags (used by some IDE run configs)
    ap.add_argument("--cleanup-username", dest="cleanup_user", default=None,
                    help="Cleanup web-login username (alias for --cleanup USER:PASS).")
    ap.add_argument("--cleanup-password", dest="cleanup_pass", default=None,
                    help="Cleanup web-login password (alias for --cleanup USER:PASS).")
    ap.add_argument("--reuse-cleanup-for-twine", action="store_true",
                    help="On TestPyPI, reuse --cleanup username/password for Twine if none were provided.")
    # Unified Twine auth (optional): avoids repeated prompts
    ap.add_argument("--twine-username", dest="twine_user", default=None,
                    help="Twine username to upload to {testpypi,pypi}. Overrides ~/.pypirc if set.")
    ap.add_argument("--twine-password", dest="twine_pass", default=None,
                    help="Twine password/token. If omitted but username is set, you will be prompted once.")
    ap.add_argument("--yank-previous", action="store_true",
                    help="On PyPI, yank previously released versions (older than the chosen version) after a successful upload.")
    # Repo state management (opt-in)
    ap.add_argument("--git-commit-version", action="store_true",
                    help="After successful upload, git add and commit all edited pyproject.toml files with the chosen version.")
    ap.add_argument("--git-reset-on-failure", action="store_true",
                    help="If a failure occurs after editing pyproject.toml files, reset them with 'git checkout --'.")
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
CLEAN_LEAVE_LATEST: bool = bool(args.cleanup_creds or args.cleanup_user or args.cleanup_pass or args.clean)

# Prefill Twine creds from ~/.pypirc if CLI omitted both (prevents repeated prompts)
def _pypirc_creds(repo: str) -> tuple[str | None, str | None]:
    try:
        cfg = configparser.RawConfigParser()
        cfg.read(pathlib.Path.home() / ".pypirc")
        if cfg.has_section(repo):
            return (
                cfg.get(repo, "username", fallback=None),
                cfg.get(repo, "password", fallback=None),
            )
    except Exception:
        pass
    return (None, None)

if not TWINE_USER and not TWINE_PASS:
    u, p = _pypirc_creds(TARGET)
    if u and p:
        TWINE_USER, TWINE_PASS = u, p

# Optional: on TestPyPI, reuse cleanup credentials for Twine if requested and none provided
def _parse_cleanup_cli_creds() -> tuple[str | None, str | None]:
    cu = cp = None
    if getattr(args, "cleanup_creds", None):
        parts = str(args.cleanup_creds).split(":", 1)
        if len(parts) == 2 and parts[0] and parts[1]:
            cu, cp = parts[0], parts[1]
    if (not cu or not cp) and (getattr(args, "cleanup_user", None) or getattr(args, "cleanup_pass", None)):
        if getattr(args, "cleanup_user", None) and getattr(args, "cleanup_pass", None):
            cu, cp = args.cleanup_user, args.cleanup_pass
    return (cu, cp)

if TARGET == "testpypi" and not (TWINE_USER and TWINE_PASS) and getattr(args, "reuse_cleanup_for_twine", False):
    cu, cp = _parse_cleanup_cli_creds()
    if cu and cp:
        TWINE_USER, TWINE_PASS = cu, cp

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
    # As a last resort, fall back to ~/.pypirc if one of them is missing
    u2, p2 = _pypirc_creds(TARGET)
    if not TWINE_USER and u2:
        TWINE_USER = u2
    if not TWINE_PASS and p2:
        TWINE_PASS = p2
    # If still incomplete, fail fast to avoid multiple interactive prompts later
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

# Optional git integration flags
GIT_COMMIT_VERSION: bool = False
GIT_RESET_ON_FAILURE: bool = False
try:
    # args is defined above; guard in case of import-time usage
    GIT_COMMIT_VERSION = bool(getattr(args, "git_commit_version", False))
    GIT_RESET_ON_FAILURE = bool(getattr(args, "git_reset_on_failure", False))
except Exception:
    pass

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
    if env:
        merged_env.update(env)
    subprocess.run(cmd, cwd=str(cwd or pathlib.Path.cwd()), check=True, text=True, env=merged_env)


def cleanup_leave_latest(packages):
    if SKIP_CLEANUP:
        return

    # Determine host
    host = "https://pypi.org/"
    if TARGET == "testpypi":
        host = "https://test.pypi.org/"
        # On TestPyPI, skip unless explicit credentials were provided to avoid interactive prompts
        if not (args.cleanup_creds or (args.cleanup_user and args.cleanup_pass)):
            print("[cleanup] Skipping cleanup on TestPyPI unless --cleanup user:password is provided (avoids interactive login/timeouts).")
            return

    # Auth strategy for pypi-cleanup:
    # - PyPI web login used by pypi-cleanup REQUIRES account username+password (API tokens are NOT accepted).
    # - Prefer explicit --cleanup USER:PASS or --cleanup-username/--cleanup-password when provided.
    # - Else fall back to ~/.pypirc entries if they contain a real username (not __token__).
    # - As a last resort, allow environment variables PYPI_USERNAME/PYPI_CLEANUP_PASSWORD.
    user_from_pypirc = None
    pwd_from_pypirc = None
    env_cleanup_user = os.getenv("PYPI_USERNAME")
    env_cleanup_pass = os.getenv("PYPI_CLEANUP_PASSWORD") or os.getenv("PYPI_PASSWORD")
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
        cleanup_sections = [
            f"{TARGET}_cleanup", f"{TARGET}-cleanup",
            "pypi_cleanup", "pypi-cleanup",
        ]
        for sec in cleanup_sections:
            if cfg.has_section(sec):
                cand_user = cfg.get(sec, "username", fallback=None)
                cand_pass = cfg.get(sec, "password", fallback=None)
                if cand_user:
                    user_from_pypirc = cand_user
                if cand_pass:
                    pwd_from_pypirc = cand_pass
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

    cli_user = cli_pass = None
    if args.cleanup_creds:
        parts = args.cleanup_creds.split(":", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise SystemExit("ERROR: --cleanup value must be 'username:password'")
        cli_user, cli_pass = parts[0], parts[1]
    elif args.cleanup_user or args.cleanup_pass:
        if not (args.cleanup_user and args.cleanup_pass):
            raise SystemExit("ERROR: provide both --cleanup-username and --cleanup-password (or use --cleanup USER:PASS)")
        cli_user, cli_pass = args.cleanup_user, args.cleanup_pass

    cleanup_user = (
        valid_user(cli_user)
        or valid_user(user_from_pypirc)
        or valid_user(env_cleanup_user)
    )
    cleanup_pass = (
        valid_pass(cli_pass)
        or valid_pass(pwd_from_pypirc)
        or valid_pass(env_cleanup_pass)
    )

    token_like = cleanup_pass and str(cleanup_pass).startswith("pypi-")
    # Guardrails: prevent common mistakes that lead to silent no-ops
    #  - Using a project/package name (e.g., 'agilab') instead of your PyPI account username
    #  - Using an API token as the "username" (cleanup requires web-login password)
    def _looks_like_project(u: str | None) -> bool:
        if not u:
            return False
        u_norm = u.strip().lower()
        # Known packages in this repo + umbrella name
        known = {"agilab", "agi-env", "agi-node", "agi-cluster", "agi-core"}
        return u_norm in known

    if _looks_like_project(cleanup_user):
        print(
            "[cleanup] Refusing to use a project name ('%s') as cleanup username.\n"
            "          Provide your PyPI account username with --cleanup USER:PASS or --cleanup-username/--cleanup-password."
            % cleanup_user
        )
        return
    if not cleanup_user:
        print("[cleanup] Skipping cleanup: no cleanup username available.\n"
              "          Configure ~/.pypirc with a real account username/password or pass --cleanup user:password.")
        return
    if not cleanup_pass or token_like:
        print("[cleanup] Skipping cleanup: requires a real account password (pypi-cleanup uses the web login).\n"
              "          Provide --cleanup user:password or set PYPI_CLEANUP_PASSWORD/PYPI_USERNAME.")
        return

    cleanup_env_base = os.environ.copy()
    cleanup_env_base["PYPI_USERNAME"] = cleanup_user
    cleanup_env_base["PYPI_PASSWORD"] = cleanup_pass
    cleanup_env_base["PYPI_CLEANUP_PASSWORD"] = cleanup_pass

    def run_cleanup(extra_cmd):
        cmd = [
            "pypi-cleanup",
            "--leave-most-recent-only",
            "--do-it",
            "-y",
            "--host", host,
        ]
        if cleanup_user:
            cmd.extend(["--username", cleanup_user])
        if args.clean_days is not None:
            cmd.extend(["--days", str(args.clean_days)])
        if args.clean_delete_project:
            cmd.append("--delete-project")
        cmd.extend(extra_cmd)

        env = cleanup_env_base.copy()
        print(f"[cleanup] Keeping only latest release for {extra_cmd[-1]} on {TARGET}")
        if VERBOSE:
            cmd.append("-v")
            print("[cleanup] Command:", " ".join(cmd))
        run_kwargs = dict(cwd=str(REPO_ROOT), env=env)
        if CLEANUP_TIMEOUT:
            run_kwargs["timeout"] = CLEANUP_TIMEOUT
        try:
            subprocess.run(cmd, check=True, **run_kwargs)
        except subprocess.TimeoutExpired:
            print(f"[cleanup] warning: pypi-cleanup timed out after {CLEANUP_TIMEOUT}s for {extra_cmd[-1]}; skipping.")
        except subprocess.CalledProcessError as exc:
            print(f"[cleanup] warning: pypi-cleanup exited with status {exc.returncode} for {extra_cmd[-1]}; continuing.")
            if not VERBOSE:
                print("[cleanup] re-run with --verbose to inspect output or run the command manually.")

    for pkg in packages:
        run_cleanup(["--package", pkg])

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
        rels = set()
        for ver, files in (data.get("releases") or {}).items():
            # keep versions that still have files and at least one non-yanked file
            if files and any(not f.get("yanked", False) for f in files):
                rels.add(ver)
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

# Alternative: commit *every* pyproject.toml in the repo.
from pathlib import Path
def git_paths_to_commit() -> list[str]:
    root = REPO_ROOT
    return [str(p) for p in Path(root).rglob("pyproject.toml") if ".git" not in p.parts]

def git_commit_version(chosen_version: str):
    """
    Commit version/metadata changes in curated pyproject.toml files.

    Safety:
    - Only considers the curated set from git_paths_to_commit()
    - Intersects that set with Git's *tracked* files (git ls-files)
    - Clears assume-unchanged / skip-worktree so Git notices edits
    - Does nothing (and cleans index) if no actual changes are staged
    """
    all_candidates = git_paths_to_commit()
    if not all_candidates:
        print("[git] nothing to commit (no pyproject.toml files found in scope)")
        return

    # Convert absolute paths to repo-relative for ls-files comparison
    repo_str = str(REPO_ROOT)
    rel_candidates = [
        (p if not p.startswith(repo_str) else p[len(repo_str) + 1 :])
        for p in all_candidates
    ]

    # Ask Git which of those are tracked
    try:
        # 'git ls-files -- <list>' prints only tracked paths that match
        out = run(["git", "ls-files", "--"] + rel_candidates, cwd=REPO_ROOT)
        # Our run() prints and then executes; capture is via exceptions only – so call again to capture stdout
        cp = subprocess.run(
            ["git", "ls-files", "--"] + rel_candidates,
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            check=True,
        )
        tracked_rel = [line.strip() for line in cp.stdout.splitlines() if line.strip()]
    except Exception as e:
        print(f"[git] WARN: ls-files failed ({e}); falling back to all candidates")
        tracked_rel = rel_candidates

    if not tracked_rel:
        print("[git] nothing to commit (none of the curated pyproject.toml are tracked)")
        return

    # Clear index hints so Git notices changes even if files were marked H/S
    try:
        run(["git", "update-index", "--no-assume-unchanged", "--no-skip-worktree", "--"] + tracked_rel, cwd=REPO_ROOT)
    except Exception as e:
        print(f"[git] WARN: update-index best-effort failed: {e}")

    # Stage only the tracked curated files
    run(["git", "add", "--"] + tracked_rel, cwd=REPO_ROOT)

    # If nothing is actually staged, reset and exit quietly
    cp = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--"] + tracked_rel,
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    staged = [s for s in cp.stdout.splitlines() if s.endswith("pyproject.toml")]
    if not staged:
        # Keep the index clean in case add touched something without changes
        try:
            run(["git", "reset", "--quiet", "--"] + tracked_rel, cwd=REPO_ROOT)
        except Exception:
            pass
        print("[git] No pyproject.toml changes to commit.")
        return

    # Commit (preserve your message style)
    run(["git", "commit", "-m", f"chore(release): bump version to {chosen_version}"], cwd=REPO_ROOT)
    print(f"[git] committed version bump to {chosen_version}")


def git_reset_pyprojects():
    files = git_paths_to_commit()
    if not files:
        return
    try:
        run(["git", "checkout", "--", *files], cwd=REPO_ROOT)
        print("[git] reset pyproject.toml edits")
    except Exception as e:
        print(f"[git] warning: could not reset pyproject.toml files: {e}")

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
        # Cleanup runs once after builds when publishing (see below).

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

        if CLEAN_LEAVE_LATEST and not DRY_RUN:
            cleanup_leave_latest(core_names + [UMBRELLA[0]])

        twine_check(all_files)
        twine_upload(all_files, TARGET)

        if TARGET == "pypi" and YANK_PREVIOUS:
            yank_previous_versions(core_names + [UMBRELLA[0]], TARGET, chosen)

        if TARGET == "pypi":
            create_and_push_tag(date_tag)
        # Always try to commit pyproject.toml changes after a successful publish
        try:
            git_commit_version(chosen)  # 'chosen' is your final version string
        except Exception as e:
            # Do not fail the publish if commit fails; just warn
            print(f"[git] WARN: commit step failed: {e}")

    finally:
        if removed_symlinks:
            restore_symlinks(removed_symlinks)
        # Optionally reset edits to pyproject on failure or when requested
        # We don't have exception context here reliably; honor explicit flag to keep repo clean.
        if GIT_RESET_ON_FAILURE and not DRY_RUN:
            git_reset_pyprojects()


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
