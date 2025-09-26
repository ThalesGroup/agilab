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
                    help="Base version (e.g., 0.7.4). If omitted, a unified .postN is computed.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show chosen version & collisions; do not build or upload.")
    ap.add_argument("--no-pypirc-check", dest="pypirc_check", action="store_false",
                    help="Disable ~/.pypirc preflight (enabled by default).")
        # Cleanup & auth options (backward-compatible aliases)
    ap.add_argument("--clean", action="store_true",
                    help="Interactively delete versions on TestPyPI before publishing.")
    ap.add_argument("--user", "--clean-user", dest="clean_user", default=None,
                    help="Username for deletion (e.g., TestPyPI account name for interactive login).")
    ap.add_argument("--regex", "--clean-regex", dest="clean_regex", default=None,
                    help="Regex of versions to delete. Example: ^0\\.1\\.0\\.post\\d+$")
    ap.add_argument("--days", "--clean-days", dest="clean_days", type=int, default=None,
                    help="Only delete releases uploaded in the last N days (omit to consider all).")
    ap.add_argument("--delete-project", "--clean-delete-project", dest="clean_delete_project",
                    action="store_true",
                    help="Pass --delete-project to pypi-cleanup (destructive: deletes all matched releases).")
    return ap.parse_args()

args = parse_args()
TARGET: str = args.repo
BASE_VERSION: str | None = args.version.strip().lstrip("v") if args.version else None
DO_PYPIRC_CHECK: bool = args.pypirc_check
DRY_RUN: bool = args.dry_run

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
    subprocess.run(cmd, cwd=str(cwd or pathlib.Path.cwd()), check=True, text=True, env=env)

def ensure_tools():
    # tomlkit, uv, twine
    try:
        import tomlkit  # noqa: F401
    except Exception:
        run([sys.executable, "-m", "pip", "install", "--upgrade", "tomlkit"])
    for tool in ("uv", "twine"):
        try:
            run([tool, "--version"])
        except Exception:
            run([sys.executable, "-m", "pip", "install", "--upgrade", tool])

ensure_tools()
from tomlkit import parse as toml_parse, dumps as toml_dumps  # type: ignore

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
    Returns (chosen_version, collisions)
    collisions: map package_name -> list of versions that caused bumps (for reporting).
    """
    collisions: Dict[str, List[str]] = {n: [] for n in core_names}

    if base_version:
        base = base_version
    else:
        base = max_base_across_packages(core_names, repo_target)

    # If user provided a full X[.postN]? we ALWAYS emit a .postK (never plain base)
    chosen = next_free_post_for_all(core_names, repo_target, base)

    # Fill collisions detail
    for n in core_names:
        rels = pypi_releases(n, repo_target)
        # Anything equal to chosen is a collision (should be none), anything equal to base or base.post<k'<k> explains why we bumped
        base_hits = []
        if base in rels:
            base_hits.append(base)
        for v in rels:
            b, post = split_base_and_post(v)
            if b == base and v != base and safe_ver(v) < safe_ver(chosen):
                base_hits.append(v)
        collisions[n] = sorted(set(base_hits), key=safe_ver)

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
    run([sys.executable, "-m", "twine", "upload", "--non-interactive",
         "-r", repo, *files], cwd=REPO_ROOT)

# Umbrella
def uv_build_repo_root():
    for sub in ("dist", "build"):
        d = REPO_ROOT / sub
        if d.exists():
            shutil.rmtree(d)
    run(["uv", "build", "--wheel"], cwd=REPO_ROOT)

def dist_files_root() -> List[str]:
    return sorted(glob.glob(str((REPO_ROOT / "dist" / "*").resolve())))

def remove_symlinks_for_umbrella():
    # Avoid bundling symlinks that may point outside the project
    for rel in ("src/agilab/apps", "src/agilab/pages"):
        base = REPO_ROOT / rel
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_symlink():
                print(f"[symlink] removing {p}")
                p.unlink(missing_ok=True)

# Git tagging when publishing to PyPI
def create_and_push_tag(version: str):
    tag = f"v{version}"
    run(["git", "tag", "-a", tag, "-m", f"Release {tag}"], cwd=REPO_ROOT)
    run(["git", "push", "origin", tag], cwd=REPO_ROOT)
    print(f"[git] created and pushed {tag}")

# ------------------------- Main -------------------------
def main():
    # Basic hygiene on names
    sanitize_project_names([p for _, p, _ in CORE])

    core_names = [n for n, _, __ in CORE]
    chosen, collisions = compute_unified_version(core_names, TARGET, BASE_VERSION)

    print(f"[plan] Unified version: {chosen}")
    if DRY_RUN:
        print("[dry-run] Collisions that forced bump (per package):")
        for n in core_names:
            hits = collisions[n]
            print(f"  - {n}: {', '.join(hits) if hits else '(none)'}")
        return  # exit without building/uploading

    # Pin internal deps to the chosen version and build/upload each core
    pins = {n: chosen for n, _, __ in CORE}
    for name, toml, project in CORE:
        set_project_version(toml, chosen)
        pin_deps(toml, pins)
        uv_build_project(project)
        files = dist_files(project)
        print(f"Successfully built {', '.join(files) if files else '(no files)'}")
        twine_check(files)
        twine_upload(files, TARGET)

    # Umbrella package
    remove_symlinks_for_umbrella()
    _, umbrella_toml, _ = UMBRELLA
    # Ensure umbrella version is unified and internal deps are pinned
    set_project_version(umbrella_toml, chosen)
    pin_deps(umbrella_toml, pins)

    uv_build_repo_root()
    files = dist_files_root()
    print(f"Successfully built {', '.join(files) if files else '(no files)'}")
    twine_check(files)
    twine_upload(files, TARGET)

    if TARGET == "pypi":
        create_and_push_tag(chosen)

if __name__ == "__main__":
    main()
