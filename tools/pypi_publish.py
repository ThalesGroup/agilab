#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
agilab local publisher for TestPyPI / PyPI using ~/.pypirc.

Highlights
- Builds with uv (wheels and/or sdists). No pep517 shim.
- Unified version for all core packages + umbrella. If busy, auto-bumps .postN.
- Robust pyproject.toml editing with tomlkit (preserves formatting, trailing newline).
- Twine auth from ~/.pypirc; CLI --username/--password are ONLY for cleanup/purge.
- Optional purge/cleanup (web login flow) before/after using pypi-cleanup.
- Optional yank previous versions on PyPI.
- Optional git tag (date-based) and commit of version bumps.

Typical:
  uv run tools/pypi_publish.py --repo testpypi
  uv run tools/pypi_publish.py --repo pypi --purge-after \
      --username <cleanup-user> --password <cleanup-pass>

Notes
- PyPI upload requires API token via ~/.pypirc (__token__/pypi-...). We do NOT take token via CLI.
- Cleanup/purge uses PyPI web login and needs real account USER/PASS (not token).
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
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Tuple

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
from packaging.version import Version, InvalidVersion  # type: ignore

# upload-state flags (set by twine_upload)
UPLOAD_COLLISION_DETECTED: bool = False
UPLOAD_SUCCESS_COUNT: int = 0


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
    ap.add_argument("--version", help="Explicit version 'X.Y.Z[.postN]'. If omitted, base=UTC YYYY.MM.DD then .postN chosen")

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

    # Yank
    ap.add_argument("--yank-previous", action="store_true", help="On PyPI, yank versions older than the chosen version")

    # Git
    ap.add_argument("--git-tag", action="store_true", help="Create & push date tag (vYYYY.MM.DD[-N]) on PyPI")
    ap.add_argument("--git-commit-version", action="store_true", help="git add/commit pyproject version bumps")
    ap.add_argument("--git-reset-on-failure", action="store_true", help="On failure, git checkout -- pyproject files")

    # Preflight
    ap.add_argument("--no-pypirc-check", dest="pypirc_check", action="store_false", help="Skip ~/.pypirc preflight")

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
        pypirc_check=bool(getattr(args, "pypirc_check", True)),
        packages=list(args.packages) if getattr(args, "packages", None) else None,
    )


# ---------- Repo layout (agilab) ----------
REPO_ROOT = pathlib.Path.cwd().resolve()

CORE: List[Tuple[str, pathlib.Path, pathlib.Path]] = [
    ("agi-env",     REPO_ROOT / "src/agilab/core/agi-env/pyproject.toml",     REPO_ROOT / "src/agilab/core/agi-env"),
    ("agi-node",    REPO_ROOT / "src/agilab/core/agi-node/pyproject.toml",    REPO_ROOT / "src/agilab/core/agi-node"),
    ("agi-cluster", REPO_ROOT / "src/agilab/core/agi-cluster/pyproject.toml", REPO_ROOT / "src/agilab/core/agi-cluster"),
    ("agi-core",    REPO_ROOT / "src/agilab/core/agi-core/pyproject.toml",    REPO_ROOT / "src/agilab/core/agi-core"),
]
UMBRELLA = ("agilab", REPO_ROOT / "pyproject.toml", REPO_ROOT)
ALL_PACKAGE_NAMES = [name for name, *_ in CORE] + [UMBRELLA[0]]

PYPI_JSON = {
    "testpypi": "https://test.pypi.org/pypi/{name}/json",
    "pypi":     "https://pypi.org/pypi/{name}/json",
}

BADGE_PATTERN = re.compile(
    r"\[!\[PyPI version\]\(https://img\.shields\.io/[^)]+\)\]\(https://pypi\.org/project/[^)]+\)"
)



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
def pypi_releases(name: str, repo_target: str) -> set[str]:
    url = PYPI_JSON[repo_target].format(name=name)
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.load(r) or {}
        return set((data.get("releases") or {}).keys())
    except Exception as e:
        # Do NOT silently ignore; this commonly leads to version collisions later.
        print(f"[warn] Could not fetch releases for {name} from {url}: {e}")
        # Return a sentinel to force a .postN bump downstream
        return {"0.0.0.post0"}


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


def max_base_across_packages(package_names: List[str], repo_target: str) -> str:
    all_versions = set()
    for n in package_names:
        all_versions |= pypi_releases(n, repo_target)
    if not all_versions:
        return datetime.now(timezone.utc).strftime("%Y.%m.%d")  # seed by date
    bases = {normalize_base(v) for v in all_versions if v}
    return max(bases, key=safe_ver)


def next_free_post_for_all(package_names: List[str], repo_target: str, base: str) -> str:
    per_pkg = {n: pypi_releases(n, repo_target) for n in package_names}

    # start beyond current max .post across all pkgs
    k_start = 1
    for releases in per_pkg.values():
        max_post = 0
        if base in releases:
            max_post = 0
        for v in releases:
            b, post = split_base_and_post(v)
            if b == base and post is not None and post > max_post:
                max_post = post
        k_start = max(k_start, max_post + 1)

    k = k_start
    while True:
        cand = f"{base}.post{k}"
        if all(cand not in per_pkg[n] for n in package_names):
            return cand
        k += 1


def compute_unified_version(core_names: List[str], repo_target: str, base_version: str | None) -> Tuple[str, Dict[str, List[str]]]:
    collisions: Dict[str, List[str]] = {n: [] for n in core_names}

    if base_version:
        provided = base_version
        provided_base = normalize_base(provided)
        existing_by_pkg = {n: pypi_releases(n, repo_target) for n in core_names}
        provided_in_use = any(provided in rels for rels in existing_by_pkg.values())
        if not provided_in_use:
            chosen = provided
            base = provided_base
        else:
            base = provided_base
            chosen = next_free_post_for_all(core_names, repo_target, base)
    else:
        base = datetime.now(timezone.utc).strftime("%Y.%m.%d")
        # if no releases at all, still .post1 to keep everything uniform
        chosen = next_free_post_for_all(core_names, repo_target, base)

    # report collisions that influenced bump
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


def pin_internal_deps(pyproject_path: pathlib.Path, pins: Dict[str, str]) -> bool:
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
                    s = f"{pkg}{extras}=={pins[pkg]}{marker}"
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
def shields_badge(version: str, package_name: str) -> str:
    safe_version = urllib.parse.quote(version, safe="")
    return (
        f"[![PyPI version](https://img.shields.io/badge/PyPI-{safe_version}-informational?logo=pypi)]"
        f"(https://pypi.org/project/{package_name})"
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


def update_selected_badges(selected_core: List[Tuple[str, pathlib.Path, pathlib.Path]], include_umbrella: bool):
    touched = False
    for name, toml_path, project_dir in selected_core:
        readme = project_dir / "README.md"
        if not toml_path.exists():
            continue
        version = get_version_from_pyproject(toml_path)
        touched |= update_badge(readme, name, version)
    if include_umbrella:
        umbrella_toml = UMBRELLA[1]
        if umbrella_toml.exists():
            version = get_version_from_pyproject(umbrella_toml)
            readme = UMBRELLA[2] / "README.md"
            touched |= update_badge(readme, UMBRELLA[0], version)
    return touched


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
    global UPLOAD_COLLISION_DETECTED, UPLOAD_SUCCESS_COUNT
    if not files:
        raise SystemExit("No artifacts to upload")
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
                break
            # returncode != 0
            if skip_existing and _is_reuse_output(out):
                UPLOAD_COLLISION_DETECTED = True
                print(f"[upload] skipped existing (already on server): {fname}")
                # continue with next file without failing
                break
            if attempt >= retries:
                if out.strip():
                    print(out)
                raise subprocess.CalledProcessError(proc.returncode, cmd, output=proc.stdout, stderr=proc.stderr)
            print(f"[upload] error on {fname} (attempt {attempt}/{retries}); retrying...")

# ---------- Cleanup/Purge (web login) ----------
def cleanup_leave_latest(cfg: Cfg, packages: list[str]):
    if cfg.skip_cleanup:
        return

    host = "https://pypi.org/"
    if cfg.repo == "testpypi":
        host = "https://test.pypi.org/"

    # username/password precedence: CLI only
    cleanup_user = (cfg.cleanup_user or "").strip() or None
    cleanup_pass = (cfg.cleanup_pass or "").strip() or None

    if not cleanup_user or not cleanup_pass:
        print("[cleanup] Skipping: requires --username and --password (web login), tokens won't work here.")
        return
    if cleanup_user == "__token__" or str(cleanup_pass).startswith("pypi-"):
        print("[cleanup] Skipping: cleanup needs real account credentials (not API token).")
        return

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
def _tag_exists(tag: str) -> bool:
    try:
        subprocess.run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"], cwd=REPO_ROOT,
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


def create_and_push_tag(tag: str):
    run(["git", "tag", "-a", f"v{tag}", "-m", f"Release {tag}"], cwd=REPO_ROOT)
    run(["git", "push", "origin", f"v{tag}"], cwd=REPO_ROOT)
    print(f"[git] created and pushed v{tag}")


def git_paths_to_commit() -> list[str]:
    paths: list[str] = []
    for _, toml_path, project_dir in CORE:
        if toml_path.exists():
            paths.append(str(toml_path.relative_to(REPO_ROOT)))
        readme = project_dir / "README.md"
        if readme.exists():
            paths.append(str(readme.relative_to(REPO_ROOT)))
    if UMBRELLA[1].exists():
        paths.append(str(UMBRELLA[1].relative_to(REPO_ROOT)))
    umbrella_readme = UMBRELLA[2] / "README.md"
    if umbrella_readme.exists():
        paths.append(str(umbrella_readme.relative_to(REPO_ROOT)))
    # Preserve order but drop duplicates
    seen: set[str] = set()
    unique: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def git_commit_version(chosen_version: str):
    files = git_paths_to_commit()
    if not files:
        print("[git] nothing to commit")
        return
    run(["git", "add", *files], cwd=REPO_ROOT)
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


# ---------- Main ----------
def main():
    args = parse_args()
    cfg = make_cfg(args)

    print(f"[config] repo={cfg.repo} python={sys.executable} dist={cfg.dist} "
          f"skip_existing={cfg.skip_existing} retries={cfg.retries} clean={not cfg.skip_cleanup}")

    if cfg.pypirc_check:
        assert_pypirc_has(cfg.repo)

    # Validate explicit version if provided
    if cfg.version is not None and not re.fullmatch(r"\d+\.\d+\.\d+(?:\.post\d+)?", cfg.version):
        raise SystemExit("ERROR: Invalid --version format. Use X.Y.Z or X.Y.Z.postN")

    selected_packages = set(cfg.packages or ALL_PACKAGE_NAMES)
    unknown = selected_packages - set(ALL_PACKAGE_NAMES)
    if unknown:
        raise SystemExit(f"ERROR: Unknown package(s): {', '.join(sorted(unknown))}")

    selected_core_entries = [entry for entry in CORE if entry[0] in selected_packages]
    build_umbrella = UMBRELLA[0] in selected_packages
    if not selected_core_entries and not build_umbrella:
        raise SystemExit("ERROR: --packages must include at least one buildable package")

    selected_core_names = [name for name, *_ in selected_core_entries]
    version_targets = selected_core_names + ([UMBRELLA[0]] if build_umbrella else [])

    removed_symlinks: list[tuple[pathlib.Path, str, bool]] = []
    try:
        if not cfg.dry_run and build_umbrella:
            removed_symlinks = remove_symlinks_for_umbrella()

        # Name hygiene
        sanitize_project_names([p for _, p, _ in selected_core_entries])

        # Determine version target
        if cfg.packages and cfg.version is None:
            existing_versions: set[str] = set()
            for _, toml_path, _ in selected_core_entries:
                existing_versions.add(get_version_from_pyproject(toml_path))
            if build_umbrella:
                existing_versions.add(get_version_from_pyproject(UMBRELLA[1]))
            if len(existing_versions) != 1:
                raise SystemExit(
                    "ERROR: Selected packages have differing versions. "
                    "Specify --version explicitly to override."
                )
            base_version = existing_versions.pop()
        else:
            base_version = cfg.version

        chosen, collisions = compute_unified_version(version_targets, cfg.repo, base_version)

        print(f"[plan] Unified version: {chosen}")
        date_tag = normalize_base(chosen)  # date base (YYYY.MM.DD)
        print(f"[plan] Tag base (UTC): {date_tag}")
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
        current_versions = {name: get_version_from_pyproject(toml) for name, toml, _ in CORE}
        pins = current_versions.copy()
        for name in selected_core_names:
            pins[name] = chosen

        all_files: List[str] = []

        # core
        for name, toml, project in selected_core_entries:
            try:
                set_version_in_pyproject(toml, chosen)
            except Exception as e:
                raise SystemExit(f"fatal: Could not update version in {toml}\n{e}")
            pin_internal_deps(toml, pins)
            if not cfg.dry_run:
                uv_build_project(project, cfg.dist)
            files = dist_files(project)
            if files:
                print(f"[build] {name}: {', '.join(files)}")
            all_files.extend(files)

        # umbrella
        if build_umbrella:
            _, umbrella_toml, _ = UMBRELLA
            try:
                set_version_in_pyproject(umbrella_toml, chosen)
            except Exception as e:
                raise SystemExit(f"fatal: Could not update version in {umbrella_toml}\n{e}")
            pin_internal_deps(umbrella_toml, pins)
            if not cfg.dry_run:
                uv_build_repo_root(cfg.dist)
            root_files = dist_files_root()
            if root_files:
                print(f"[build] umbrella: {', '.join(root_files)}")
            all_files.extend(root_files)

        # keep README badges aligned even when running with --dry-run
        update_selected_badges(selected_core_entries, build_umbrella)

        # Dry-run end
        if cfg.dry_run:
            print("[dry-run] Would twine check & upload:")
            for f in all_files:
                print("  -", f)
            return

        # Twine
        twine_check(all_files)
        twine_upload(all_files, cfg.repo, cfg.skip_existing, cfg.retries)
        if not cfg.dry_run and UPLOAD_COLLISION_DETECTED and UPLOAD_SUCCESS_COUNT == 0:
            print('[auto-bump] upload collision detected; bumping to next .postN and retrying upload...')
            base_only = normalize_base(chosen)
            chosen2 = next_free_post_for_all(version_targets, cfg.repo, base_only)
            pins2 = pins.copy()
            for name in selected_core_names:
                pins2[name] = chosen2
            all_files2: List[str] = []
            for name, toml, project in selected_core_entries:
                set_version_in_pyproject(toml, chosen2)
                pin_internal_deps(toml, pins2)
                uv_build_project(project, cfg.dist)
                all_files2.extend(dist_files(project))
            if build_umbrella:
                _, umbrella_toml, _ = UMBRELLA
                set_version_in_pyproject(umbrella_toml, chosen2)
                pin_internal_deps(umbrella_toml, pins2)
                uv_build_repo_root(cfg.dist)
                all_files2.extend(dist_files_root())
            twine_check(all_files2)
            globals()['UPLOAD_COLLISION_DETECTED'] = False
            globals()['UPLOAD_SUCCESS_COUNT'] = 0
            twine_upload(all_files2, cfg.repo, cfg.skip_existing, cfg.retries)
            chosen = chosen2

        if not cfg.dry_run:
            update_selected_badges(selected_core_entries, build_umbrella)

        # Yank (optional, PyPI only)
        if cfg.yank_previous:
            yank_previous_versions(cfg, version_targets, chosen)

        # Purge AFTER (optional)
        if cfg.purge_after:
            cleanup_leave_latest(cfg, version_targets)

        # Git tag/commit (optional)
        if cfg.repo == "pypi" and cfg.git_tag:
            tag = compute_date_tag()  # resolves collisions with existing tags
            create_and_push_tag(tag)
        if cfg.git_commit_version:
            git_commit_version(chosen)

    finally:
        if removed_symlinks:
            restore_symlinks(removed_symlinks)
        if cfg.git_reset_on_failure and not cfg.dry_run:
            git_reset_pyprojects()


if __name__ == "__main__":
    main()
