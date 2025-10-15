#!/usr/bin/env python3
"""
pypi_publish.py — build & upload multiple packages to (Test)PyPI
- Auto `.postN` bump if version already exists on PyPI.
- Robust version editing:
    * Updates `version` in either `[project]` (PEP 621) or `[tool.poetry]`
    * Handles single/double quotes and trailing comments
    * Replaces only within the matched section
- Optional yanking via Twine (guarded).
- Symlink restore, dotenv, retries, verbose logging.
- Cleanup controls and credential flags (incl. parse-known passthrough).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Set, Tuple, Dict

# --------------------------- TOML loader -----------------------------------
try:
    import tomllib  # Python 3.11+
except Exception:  # pragma: no cover
    tomllib = None
    try:
        import tomli as tomllib  # type: ignore
    except Exception:
        pass

# --------------------------- Constants -------------------------------------
DEFAULT_PACKAGE_ROOTS = [
    "src/agilab/core/agi-env",
    "src/agilab/core/agi-node",
    "src/agilab/core/agi-cluster",
    "src/agilab/core/agi-core",
    ".",  # meta-package (agilab)
]

PYPI_API_JSON = "https://pypi.org/pypi/{name}/json"
POST_RE = re.compile(r"^(?P<base>.+?)(?:\\.post(?P<n>\\d+))?$")

# --------------------------- Logging ---------------------------------------
class Logger:
    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose

    def info(self, msg: str) -> None:
        print(msg)

    def debug(self, msg: str) -> None:
        if self.verbose:
            print(msg)

log = Logger(verbose=False)

# --------------------------- Subprocess ------------------------------------
def run(cmd: Sequence[str] | str, *, cwd: Path | None = None, env: dict | None = None) -> None:
    display = cmd if isinstance(cmd, str) else " ".join(shlex.quote(c) for c in cmd)
    log.info(f"+ {display}")
    subprocess.run(cmd, check=True, text=True, cwd=str(cwd) if cwd else None, env=(env or os.environ))

# --------------------------- TOML helpers ----------------------------------
def read_pyproject(pyproject: Path) -> dict:
    if not tomllib:
        raise RuntimeError("tomllib/tomli is required (use Python 3.11+ or `pip install tomli`).")
    return tomllib.loads(pyproject.read_text(encoding="utf-8"))


def _replace_key_in_span(src: str, span: tuple[int, int], key: str, new_value: str) -> tuple[str, bool]:
    """
    Replace `key = "<...>"` within the span. Supports single/double quotes and trailing comments.
    Returns (new_src, replaced?).
    """
    s, e = span
    block = src[s:e]
    # match: key = '...' or "..." with optional spaces and trailing comment
    key_re = re.compile(
        rf"(?m)^\\s*{re.escape(key)}\\s*=\\s*(['\\\"])"
        rf"(?P<val>.*?)\\1\\s*(?P<comment>#.*)?$"
    )
    m = key_re.search(block)
    if not m:
        return src, False
    quote = m.group(1)
    comment = m.group('comment') or ""
    new_line = f"{key} = {quote}{new_value}{quote}{comment}"
    new_block = key_re.sub(new_line, block, count=1)
    return src[:s] + new_block + src[e:], True


def _section_span(src: str, header: str):
    m = re.search(rf"(?m)^\s*\[{re.escape(header)}\]\s*$", src)
    if not m:
        return None
    start = m.end()
    m2 = re.search(r"(?m)^\s*\[[^\]]+\]\s*$", src[start:])
    end = start + m2.start() if m2 else len(src)
    return start, end

def _replace_key_in_span(src: str, span, key: str, new_value: str):
    s, e = span
    block = src[s:e]
    # version = "..."   or   version = '...'   (allow trailing comments)
    pat = re.compile(rf'(?m)^\s*{re.escape(key)}\s*=\s*([\'"])(?P<val>.*?)\1\s*(?P<c>#.*)?$')
    m = pat.search(block)
    if not m:
        return src, False
    q = m.group(1); c = m.group('c') or ''
    newline = f'{key} = {q}{new_value}{q}{c}'
    new_block = pat.sub(newline, block, count=1)
    return src[:s] + new_block + src[e:], True

def write_version(pyproject_path: Path, new_version: str) -> None:
    src = pyproject_path.read_text(encoding="utf-8")
    for section in ("project", "tool.poetry"):
        span = _section_span(src, section)
        if span:
            src2, ok = _replace_key_in_span(src, span, "version", new_version)
            if ok:
                pyproject_path.write_text(src2, encoding="utf-8")
                return
    raise RuntimeError(f"Could not update version in {pyproject_path}")

# --------------------------- Version bump ----------------------------------
def fetch_pypi_versions(dist_name: str, timeout: float = 10.0) -> Set[str]:
    url = PYPI_API_JSON.format(name=dist_name)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return set(data.get("releases", {}).keys())
    except urllib.error.HTTPError as e:
        return set() if e.code == 404 else set()
    except Exception:
        return set()

def next_post_version(base_version: str, existing: Set[str]) -> str:
    m = POST_RE.match(base_version)
    if not m:
        return base_version
    base = m.group("base")
    cur_post = int(m.group("n") or 0)
    exact_exists = base_version in existing
    max_post = -1
    base_plain_exists = False
    for v in existing:
        mv = POST_RE.match(v)
        if not mv or mv.group("base") != base:
            continue
        if mv.group("n") is None:
            base_plain_exists = True
        else:
            max_post = max(max_post, int(mv.group("n")))
    if exact_exists:
        return f"{base}.post{max(cur_post, max_post) + 1}"
    if cur_post == 0 and base_plain_exists:
        return f"{base}.post{(max_post + 1) if max_post >= 0 else 1}"
    return base_version

def ensure_unique_version(pyproject: Path, *, require_network: bool = False) -> tuple[str, str]:
    meta = read_pyproject(pyproject)
    project = (meta.get("project") or {}) or (meta.get("tool", {}).get("poetry") or {})
    # poetic fallback for name
    name = (meta.get("project") or {}).get("name") or (meta.get("tool", {}).get("poetry") or {}).get("name")
    version = (meta.get("project") or {}).get("version") or (meta.get("tool", {}).get("poetry") or {}).get("version")
    if not name or not version:
        raise RuntimeError(f"[project]/[tool.poetry] name and version must be set in {pyproject}")

    existing = fetch_pypi_versions(name)
    if require_network and not existing:
        raise RuntimeError("PyPI availability check required but no data returned. Is the network blocked?")
    final = next_post_version(version, existing)
    if final != version:
        write_version(pyproject, final)
        log.info(f"[version] {name}: {version} -> {final} (auto .post bump)")
    else:
        log.debug(f"[version] {name}: {version} (unchanged)")
    return name, final

# --------------------------- Housekeeping ----------------------------------
def remove_path(p: Path) -> None:
    if p.exists():
        run(["rm", "-rf", str(p)])

def clean_artifacts(root: Path) -> None:
    remove_path(root / "dist")
    remove_path(root / "build")
    for egg in root.rglob("*.egg-info"):
        remove_path(egg)

def build(root: Path, python_bin: str, dist: str = "both", extra_env: dict | None = None) -> list[Path]:
    # Use a tiny shim that pops cwd from sys.path before importing PyPA build
    code = [
        "import sys, runpy",
        "sys.path.pop(0)",             # remove cwd so local build.py can't shadow
        "runpy.run_module('build.__main__', run_name='__main__')",
    ]
    cmd = [python_bin, "-c", ";".join(code)]
    if dist in ("sdist", "wheel"):
        # forward the flag through env var that PyPA build respects (or just do both and let --sdist/--wheel be CLI)
        cmd += ["--" + dist]
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    run(cmd, cwd=root, env=env)

    dist_dir = root / "dist"
    return sorted(dist_dir.glob("*")) if dist_dir.exists() else []


# --------------------------- Upload & Yank ---------------------------------
def upload(files: Iterable[Path], python_bin: str, repo: str, *, skip_existing: bool = True,
           retries: int = 1, twine_opts: Sequence[str] = (), twine_username: str | None = None,
           twine_password: str | None = None) -> None:
    files = list(files)
    if not files:
        log.info("[upload] nothing to upload")
        return
    cmd = [python_bin, "-m", "twine", "upload", "--non-interactive", "-r", repo, *twine_opts]
    if skip_existing:
        cmd.append("--skip-existing")
    cmd.extend(str(p) for p in files)

    child_env = dict(os.environ)
    if twine_username:
        child_env["TWINE_USERNAME"] = twine_username
    if twine_password:
        child_env["TWINE_PASSWORD"] = twine_password

    attempt = 0
    while True:
        try:
            run(cmd, env=child_env)
            return
        except subprocess.CalledProcessError:
            if attempt >= retries:
                raise
            attempt += 1
            wait = min(8 * attempt, 30)
            log.info(f"[upload] error (attempt {attempt}/{retries}); retrying in {wait}s...")
            time.sleep(wait)

def yank(dist_name: str, version: str, reason: str, *, python_bin: str, repo: str,
         twine_username: str | None = None, twine_password: str | None = None) -> None:
    cmd = [python_bin, "-m", "twine", "yank", "-r", repo, dist_name, version]
    if reason:
        cmd += ["--reason", reason]
    child_env = dict(os.environ)
    if twine_username:
        child_env["TWINE_USERNAME"] = twine_username
    if twine_password:
        child_env["TWINE_PASSWORD"] = twine_password
    run(cmd, env=child_env)

# --------------------------- Symlinks --------------------------------------
def restore_symlinks(mapping: Dict[str, str]) -> None:
    for link, target in mapping.items():
        link_p, target_p = Path(link), Path(target)
        try:
            if link_p.exists() or link_p.is_symlink():
                link_p.unlink()
            link_p.parent.mkdir(parents=True, exist_ok=True)
            link_p.symlink_to(target_p)
            log.info(f"[symlink] restored {link} -> {target}")
        except Exception as exc:
            log.info(f"[symlink] failed {link} -> {target}: {exc}")

# --------------------------- .env loader -----------------------------------
def load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

# --------------------------- Config / CLI ----------------------------------
@dataclass(frozen=True)
class Config:
    package_roots: tuple[Path, ...]
    python_bin: str
    repo: str
    dist: str
    skip_existing: bool
    retries: int
    strict_online: bool
    twine_opts: tuple[str, ...]
    symlink_map: Dict[str, str]
    verbose: bool
    do_clean: bool
    cleanup_only: bool
    purge_after: bool
    purge_on_fail: bool
    yank_version: str
    yank_reason: str
    yank_now: bool
    yank_allow_prod: bool
    twine_username: str | None
    twine_password: str | None

def parse_args(argv: Sequence[str]) -> tuple[Config, list[str]]:
    ap = argparse.ArgumentParser(description="Build & upload packages with auto .postN; robust version edit; optional yank & cleanup.")
    ap.add_argument("--repo", default=os.environ.get("TARGET") or os.environ.get("PYPI_REPOSITORY") or "pypi",
                    help="Twine repo (pypi | testpypi | alias in ~/.pypirc).")
    ap.add_argument("--python", dest="python_bin", default=sys.executable, help="Python interpreter.")
    ap.add_argument("--dist", choices=["both", "sdist", "wheel"], default="both", help="Artifacts to build.")
    ap.add_argument("--no-skip-existing", action="store_true", help="Do not pass --skip-existing to twine.")
    ap.add_argument("--retries", type=int, default=1, help="Upload retries on error (default: 1).")
    ap.add_argument("--strict-online", action="store_true", help="Fail if PyPI check cannot be performed.")
    ap.add_argument("--twine-opts", default="", help="Extra args passed to twine (quoted string).")
    ap.add_argument("--symlinks", default="", help="JSON file of symlink mapping to restore before build.")
    ap.add_argument("--dotenv", default="", help="Load environment variables from a .env file.")
    ap.add_argument("-v", "--verbose", action="store_true", help="Verbose logging.")
    ap.add_argument("roots", nargs="*", default=DEFAULT_PACKAGE_ROOTS, help="Package roots with pyproject.toml")

    # cleanup options
    ap.add_argument("--no-clean", action="store_true", help="Skip pre-build cleanup of dist/build/*.egg-info.")
    ap.add_argument("--cleanup-only", action="store_true", help="Only clean artifacts and exit (no build/upload).")
    ap.add_argument("--purge-after", action="store_true", help="Remove built artifacts after successful upload.")
    ap.add_argument("--purge-on-fail", action="store_true", help="Also purge artifacts if the process fails.")

    # yank options
    ap.add_argument("--yank-version", default="", help="Yank this VERSION via twine after (or before) upload.")
    ap.add_argument("--yank-reason", default="", help="Reason string to include with the yank.")
    ap.add_argument("--yank-now", action="store_true", help="Perform yank before upload (advanced).")
    ap.add_argument("--yank-allow-prod", action="store_true", help="Allow yanking on 'pypi' (safeguard off).")

    # credentials (compat)
    ap.add_argument("--username", "-u", default=os.environ.get("TWINE_USERNAME"),
                    help="Twine username (defaults to env TWINE_USERNAME).")
    ap.add_argument("--password", "-p", default=os.environ.get("TWINE_PASSWORD"),
                    help="Twine password (defaults to env TWINE_PASSWORD).")

    ns, unknown = ap.parse_known_args(argv)

    if ns.dotenv:
        load_dotenv(Path(ns.dotenv))

    symlink_map: Dict[str, str] = {}
    if ns.symlinks:
        p = Path(ns.symlinks)
        if p.exists():
            try:
                symlink_map = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"[symlink] cannot parse {p}: {e}")

    twine_opts = list(shlex.split(ns.twine_opts)) if ns.twine_opts else []
    twine_opts.extend(unknown)  # passthrough unknown flags to Twine
    roots = tuple(Path(r).resolve() for r in ns.roots)

    global log
    log = Logger(verbose=bool(ns.verbose))

    cfg = Config(
        package_roots=roots,
        python_bin=ns.python_bin,
        repo=ns.repo,
        dist=ns.dist,
        skip_existing=not ns.no_skip_existing,
        retries=max(0, ns.retries),
        strict_online=bool(ns.strict_online),
        twine_opts=tuple(twine_opts),
        symlink_map=symlink_map,
        verbose=bool(ns.verbose),
        do_clean=not bool(ns.no_clean),
        cleanup_only=bool(ns.cleanup_only),
        purge_after=bool(ns.purge_after),
        purge_on_fail=bool(ns.purge_on_fail),
        yank_version=ns.yank_version.strip(),
        yank_reason=ns.yank_reason,
        yank_now=bool(ns.yank_now),
        yank_allow_prod=bool(ns.yank_allow_prod),
        twine_username=ns.username,
        twine_password=ns.password,
    )
    return cfg, unknown

# --------------------------- Main ------------------------------------------
def _purge_all(package_roots: tuple[Path, ...]) -> None:
    for root in package_roots:
        clean_artifacts(root)

def main(argv: Sequence[str] | None = None) -> None:
    cfg, _unknown = parse_args(argv or sys.argv[1:])
    log.info(f"[config] repo={cfg.repo} python={cfg.python_bin} dist={cfg.dist} "
             f"skip_existing={cfg.skip_existing} retries={cfg.retries} clean={cfg.do_clean}")

    if cfg.yank_version and cfg.repo == "pypi" and not cfg.yank_allow_prod:
        raise SystemExit("Refusing to yank on 'pypi' without --yank-allow-prod")

    if cfg.symlink_map:
        restore_symlinks(cfg.symlink_map)

    if cfg.cleanup_only:
        _purge_all(cfg.package_roots)
        log.info("[cleanup] completed (cleanup-only)")
        return

    all_artifacts: List[Path] = []
    top_pyproj = (cfg.package_roots[-1] / "pyproject.toml")
    top_meta = read_pyproject(top_pyproj) if top_pyproj.exists() else {}
    top_name = (top_meta.get("project") or {}).get("name") or (top_meta.get("tool", {}).get("poetry") or {}).get("name")

    try:
        if cfg.yank_now and cfg.yank_version:
            if not top_name:
                raise SystemExit("Cannot yank: top-level package name not found in pyproject.toml")
            yank(top_name, cfg.yank_version, cfg.yank_reason, python_bin=cfg.python_bin, repo=cfg.repo,
                 twine_username=cfg.twine_username, twine_password=cfg.twine_password)

        for root in cfg.package_roots:
            pyproj = root / "pyproject.toml"
            if not pyproj.exists():
                raise FileNotFoundError(f"Missing pyproject.toml: {pyproj}")
            ensure_unique_version(pyproj, require_network=cfg.strict_online)
            if cfg.do_clean:
                clean_artifacts(root)
            artifacts = build(root, cfg.python_bin, dist=cfg.dist)
            if not artifacts:
                log.info(f"[build] no artifacts found in {root}/dist")
            all_artifacts.extend(artifacts)

        upload(
            all_artifacts,
            cfg.python_bin,
            cfg.repo,
            skip_existing=cfg.skip_existing,
            retries=cfg.retries,
            twine_opts=cfg.twine_opts,
            twine_username=cfg.twine_username,
            twine_password=cfg.twine_password,
        )

        if (not cfg.yank_now) and cfg.yank_version:
            if not top_name:
                raise SystemExit("Cannot yank: top-level package name not found in pyproject.toml")
            yank(top_name, cfg.yank_version, cfg.yank_reason, python_bin=cfg.python_bin, repo=cfg.repo,
                 twine_username=cfg.twine_username, twine_password=cfg.twine_password)

        if cfg.purge_after:
            _purge_all(cfg.package_roots)
            log.info("[cleanup] purged artifacts after upload")

        log.info("[done]")
    except Exception:
        if cfg.purge_on_fail:
            _purge_all(cfg.package_roots)
            log.info("[cleanup] purged artifacts due to failure (--purge-on-fail)")
        raise

if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.stderr.write(str(e) + "\\n")
        sys.exit(e.returncode)
    except Exception as e:
        sys.stderr.write(f"fatal: {e}\\n")
        sys.exit(1)
