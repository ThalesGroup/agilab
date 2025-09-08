#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Local publisher for TestPyPI or PyPI, mirroring your GA workflow.

Usage:
  python local_publish.py --version 0.7.4 --repo testpypi
  python local_publish.py --version 1.2.3 --repo pypi

Auth:
  --repo testpypi -> TEST_PYPI_API_TOKEN (or TEST_PYPI_SECRET)
  --repo pypi     -> PYPI_API_TOKEN
"""

import argparse
import glob
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.request
from typing import Dict, List

# ------------------------- CLI -------------------------
def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="Base version, e.g. 0.7.4 (no 'v').")
    ap.add_argument("--repo", choices=["testpypi", "pypi"], default="testpypi", help="Upload target.")
    return ap.parse_args()

args = parse_args()

# ------------------------- Config -------------------------
REPO_ROOT = pathlib.Path.cwd().resolve()
BASE_VERSION = args.version.strip().lstrip("v")
TARGET = args.repo  # 'testpypi' or 'pypi'

UPLOAD_URLS = {
    "testpypi": "https://test.pypi.org/legacy/",
    "pypi": "https://upload.pypi.org/legacy/",
}
JSON_API = {
    "testpypi": "https://test.pypi.org/pypi/{name}/json",
    "pypi": "https://pypi.org/pypi/{name}/json",
}
UPLOAD_URL = UPLOAD_URLS[TARGET]

# Twine auth
TWINE_USERNAME = "__token__"
if TARGET == "pypi":
    TWINE_PASSWORD = os.environ.get("PYPI_API_TOKEN")
else:
    TWINE_PASSWORD = os.environ.get("TEST_PYPI_API_TOKEN") or os.environ.get("TEST_PYPI_SECRET")

if not TWINE_PASSWORD:
    sys.exit("ERROR: Missing token. Set PYPI_API_TOKEN (pypi) or TEST_PYPI_API_TOKEN/TEST_PYPI_SECRET (testpypi).")

# Package layout
CORE: List[tuple[str, pathlib.Path, pathlib.Path]] = [
    ("agi-env",     REPO_ROOT / "src/agilab/core/agi-env/pyproject.toml",     REPO_ROOT / "src/agilab/core/agi-env"),
    ("agi-node",    REPO_ROOT / "src/agilab/core/agi-node/pyproject.toml",    REPO_ROOT / "src/agilab/core/agi-node"),
    ("agi-cluster", REPO_ROOT / "src/agilab/core/agi-cluster/pyproject.toml", REPO_ROOT / "src/agilab/core/agi-cluster"),
    ("agi-core",    REPO_ROOT / "src/agilab/core/agi-core/pyproject.toml",    REPO_ROOT / "src/agilab/core/agi-core"),
]
UMBRELLA = ("agilab", REPO_ROOT / "pyproject.toml", REPO_ROOT)

# ------------------------- Subprocess helper -------------------------
def run(cmd: List[str], cwd: pathlib.Path | None = None, env: dict | None = None):
    print("+", " ".join(map(str, cmd)), f"(cwd={str(cwd or pathlib.Path.cwd())})")
    subprocess.run(cmd, cwd=str(cwd or pathlib.Path.cwd()), check=True, text=True, env=env)

# ------------------------- Ensure tools -------------------------
def ensure_tools():
    try:
        import tomlkit  # noqa: F401
    except Exception:
        run([sys.executable, "-m", "pip", "install", "--upgrade", "tomlkit"])
    for pkg in ("uv", "twine"):
        try:
            run([pkg, "--version"])
        except Exception:
            run([sys.executable, "-m", "pip", "install", "--upgrade", pkg])

ensure_tools()

# ------------------------- TOML helpers -------------------------
from tomlkit import parse as toml_parse, dumps as toml_dumps  # type: ignore

_name_pat = re.compile(r'^[A-Za-z0-9_.-]+')
def clean_name(name: str) -> str:
    m = _name_pat.match(str(name))
    return m.group(0) if m else str(name)

def load_doc(p: pathlib.Path):
    return toml_parse(p.read_text(encoding="utf-8"))

def save_doc(p: pathlib.Path, doc):
    p.write_text(toml_dumps(doc), encoding="utf-8")

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

# ------------------------- Version computation -------------------------
def pypi_releases(name: str) -> set[str]:
    url = JSON_API[TARGET].format(name=name)
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.load(r) or {}
        return set((data.get("releases") or {}).keys())
    except Exception:
        return set()

def compute_unified_version(base: str, package_names: List[str]) -> str:
    union = set()
    for n in package_names:
        keys = pypi_releases(n)
        if base in keys:
            union.add(base)
        union.update(v for v in keys if re.fullmatch(re.escape(base) + r"\.post\d+", v))
    if not union:
        return base
    max_n = 0
    for v in union:
        if v == base:
            max_n = max(max_n, 0)
        else:
            m = re.fullmatch(re.escape(base) + r"\.post(\d+)", v)
            if m:
                try:
                    max_n = max(max_n, int(m.group(1)))
                except Exception:
                    pass
    return f"{base}.post{max_n+1}"

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
        for group, arr in list(proj["optional-dependencies"].items()):
            proj["optional-dependencies"][group] = pin_list(arr)

    if changed:
        doc["project"] = proj
        save_doc(pyproject, doc)
    return changed

# ------------------------- Build & upload -------------------------
def uv_build_project(project_dir: pathlib.Path, wheel_only: bool = True):
    for sub in ("dist", "build"):
        d = project_dir / sub
        if d.exists():
            shutil.rmtree(d)
    cmd = ["uv", "build", "--project", str(project_dir)]
    cmd += (["--wheel"] if wheel_only else ["--sdist", "--wheel"])
    run(cmd, cwd=REPO_ROOT)

def dist_files(project_dir: pathlib.Path) -> List[str]:
    return sorted(glob.glob(str((project_dir / "dist" / "*").resolve())))

def twine_check(files: List[str]):
    if not files:
        raise SystemExit("No artifacts found for twine check")
    run([sys.executable, "-m", "twine", "check", *files], cwd=REPO_ROOT)

def twine_upload(files: List[str]):
    if not files:
        raise SystemExit("No artifacts found for upload")
    env = os.environ.copy()
    env["TWINE_USERNAME"] = TWINE_USERNAME
    env["TWINE_PASSWORD"] = TWINE_PASSWORD
    print(f"+ twine upload -> {TARGET} ({UPLOAD_URL}) [{len(files)} files]")
    run(
        [sys.executable, "-m", "twine", "upload", "--non-interactive", "--skip-existing",
         "--repository-url", UPLOAD_URL, *files],
        cwd=REPO_ROOT,
        env=env,
    )

# ------------------------- Umbrella helpers -------------------------
def uv_build_repo_root(wheel_only: bool = True):
    for sub in ("dist", "build"):
        d = REPO_ROOT / sub
        if d.exists():
            shutil.rmtree(d)
    cmd = ["uv", "build"]
    cmd += (["--wheel"] if wheel_only else ["--sdist", "--wheel"])
    run(cmd, cwd=REPO_ROOT)

def dist_files_root() -> List[str]:
    return sorted(glob.glob(str((REPO_ROOT / "dist" / "*").resolve())))

def remove_symlinks_for_umbrella():
    for rel in ("src/agilab/apps", "src/agilab/views"):
        base = REPO_ROOT / rel
        if not base.exists():
            continue
        for p in base.rglob("*"):
            try:
                if p.is_symlink():
                    print(f"[symlink] removing {p}")
                    p.unlink(missing_ok=True)
            except Exception as e:
                print(f"[warn] could not remove symlink {p}: {e}")

# ------------------------- Git tag (always push when pypi) -------------------------
def create_and_push_tag(version: str):
    tag = f"v{version}"
    try:
        run(["git", "rev-parse", "--git-dir"], cwd=REPO_ROOT)
    except Exception:
        print("[git] repo not initialized; skipping tag.")
        return
    run(["git", "tag", "-a", tag, "-m", f"Release {tag}"], cwd=REPO_ROOT)
    print(f"[git] created tag {tag}")
    run(["git", "push", "origin", tag], cwd=REPO_ROOT)
    print(f"[git] pushed tag {tag} to origin")

# ------------------------- Main -------------------------
def main():
    print(f"[plan] Target repo: {TARGET} -> {UPLOAD_URL}")
    print(f"[plan] Base version input: {BASE_VERSION}")

    # Core packages
    sanitize_project_names([p for _, p, _ in CORE])
    unified = compute_unified_version(BASE_VERSION, [n for n, _, __ in CORE])
    print(f"[plan] Unified version for all core packages: {unified}")

    final_versions: Dict[str, str] = {}
    pins = {n: unified for n, _, __ in CORE}

    for name, toml, project in CORE:
        set_project_version(toml, unified)
        pin_deps(toml, pins)
        uv_build_project(project, wheel_only=True)
        files = dist_files(project)
        twine_check(files)
        twine_upload(files)
        final_versions[name] = unified

    (REPO_ROOT / "versions.json").write_text(json.dumps(final_versions, indent=2), encoding="utf-8")
    print("Core packages uploaded. Final versions:", final_versions)

    # Umbrella
    remove_symlinks_for_umbrella()
    _, umbrella_toml, _ = UMBRELLA
    doc = load_doc(umbrella_toml)
    proj = doc.get("project") or {}
    proj["name"] = clean_name(proj.get("name", ""))
    proj["version"] = unified

    core_names = set(final_versions.keys())
    def pin_list(arr):
        out = []
        for dep in arr:
            s = str(dep)
            parts = s.split(";", 1)
            left, marker = parts[0].strip(), (";" + parts[1] if len(parts) == 2 else "")
            m = re.match(r"^([A-Za-z0-9_.-]+)(\[[^\]]+\])?", left)
            if m:
                pkg, extras = m.group(1), (m.group(2) or "")
                if pkg in core_names:
                    s = f"{pkg}{extras}=={unified}{marker}"
            out.append(s)
        return out

    if "dependencies" in proj and proj["dependencies"] is not None:
        proj["dependencies"] = pin_list(proj["dependencies"])
    if "optional-dependencies" in proj and proj["optional-dependencies"] is not None:
        for g, arr in list(proj["optional-dependencies"].items()):
            proj["optional-dependencies"][g] = pin_list(arr)
    save_doc(umbrella_toml, doc)

    uv_build_repo_root(wheel_only=True)
    files = dist_files_root()
    twine_check(files)
    twine_upload(files)
    print("Umbrella uploaded successfully.")

    # Tag + push when publishing to PyPI
    if TARGET == "pypi":
        create_and_push_tag(unified)

if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.stderr.write(str(e) + "\n")
        sys.exit(e.returncode)
