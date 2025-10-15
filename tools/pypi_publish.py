#!/usr/bin/env python3
"""
pypi_publish.py — build & upload multiple packages to (Test)PyPI.

Consistency & behavior:
  - Local build.py is kept intact. We avoid shadowing by running PyPA's build via run_module and explicit argv.
  - Version bump: reads [project] or [tool.poetry], auto-appends .postN if version exists on PyPI.
    * Replaces the version line preserving indentation and EOL; inserts if missing.
  - Credentials: --username/--password are accepted but IGNORED. Auth comes from ~/.pypirc or external TWINE_* env.
  - Cleanup: --no-clean, --cleanup-only, --purge-after, --purge-on-fail.
  - Unknown CLI args are passed to Twine (e.g., --repository-url).

Usage example:
  uv run tools/pypi_publish.py --repo pypi --purge-after --username anything --password anything
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

# ---------- Config ----------

DEFAULT_PACKAGE_ROOTS = [
    "src/agilab/core/agi-env",
    "src/agilab/core/agi-node",
    "src/agilab/core/agi-cluster",
    "src/agilab/core/agi-core",
    ".",  # meta-package (agilab)
]

PYPI_API_JSON = "https://pypi.org/pypi/{name}/json"

# ---------- TOML loader ----------
try:
    import tomllib  # Python 3.11+
except Exception:
    tomllib = None
    try:
        import tomli as tomllib  # type: ignore
    except Exception:
        pass
if tomllib is None:
    raise SystemExit("tomllib/tomli is required (use Python 3.11+ or `pip install tomli`).")

# ---------- Logging ----------
class Logger:
    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
    def info(self, msg: str) -> None:
        print(msg)
    def debug(self, msg: str) -> None:
        if self.verbose:
            print(msg)

log = Logger(False)

# ---------- Subprocess ----------
def run(cmd: Sequence[str] | str, *, cwd: Path | None = None, env: dict | None = None) -> None:
    display = cmd if isinstance(cmd, str) else " ".join(shlex.quote(c) for c in cmd)
    log.info(f"+ {display}")
    subprocess.run(cmd, check=True, text=True, cwd=str(cwd) if cwd else None, env=(env or os.environ))

# ---------- TOML helpers & version editing ----------
_VERSION_LINE = re.compile(
    r'^(?P<indent>[ \t]*)'           # indentation
    r'version\s*=\s*'                # key =
    r'([\'"])(?P<val>.*?)\2'         # quoted value, backref closes the quote
    r'(?P<trail>[ \t]*#.*)?'         # optional trailing comment
    r'(?P<eol>\r?\n|\r)?$',          # captured EOL (if present)
    re.M,
)

def _read_pyproject(pyproject: Path) -> dict:
    return tomllib.loads(pyproject.read_text(encoding="utf-8"))

def _section_span(src: str, header: str) -> tuple[int, int] | None:
    m = re.search(rf"(?m)^\s*\[{re.escape(header)}\]\s*$", src)
    if not m:
        return None
    start = m.end()
    m2 = re.search(r"(?m)^\s*\[[^\]]+\]\s*$", src[start:])
    end = start + (m2.start() if m2 else len(src))
    return start, end

def _replace_or_insert_version_in(src: str, header: str, new_version: str) -> tuple[str, bool]:
    span = _section_span(src, header)
    if not span:
        return src, False
    s, e = span
    block = src[s:e]
    lines = block.splitlines(keepends=True)

    # Detect dominant EOL (default to '\n')
    default_eol = "\n"
    for L in lines:
        if L.endswith("\r\n"):
            default_eol = "\r\n"; break
        if L.endswith("\n"):
            default_eol = "\n"

    # Try replacement first
    for i, L in enumerate(lines):
        m = _VERSION_LINE.match(L)
        if not m:
            continue
        indent = m.group("indent") or ""
        eol = m.group("eol") or default_eol
        lines[i] = f'{indent}version = "{new_version}"{eol}'
        new_block = "".join(lines)
        out = src[:s] + new_block + src[e:]
        if not out.endswith(("\r\n", "\n", "\r")):
            out += default_eol
        return out, True

    # Insert at top (before first non-empty line)
    insert_at = 0
    while insert_at < len(lines) and lines[insert_at].strip() == "":
        insert_at += 1
    lines.insert(insert_at, f'version = "{new_version}"{default_eol}')
    new_block = "".join(lines)
    out = src[:s] + new_block + src[e:]
    if not out.endswith(("\r\n", "\n", "\r")):
        out += default_eol
    return out, True

def write_version(pyproject: Path, new_version: str) -> None:
    src = pyproject.read_text(encoding="utf-8")
    for section in ("project", "tool.poetry"):
        src2, changed = _replace_or_insert_version_in(src, section, new_version)
        if changed:
            pyproject.write_text(src2, encoding="utf-8")
            return
    raise RuntimeError(f"Could not update version in {pyproject}")

# ---------- PyPI version helpers ----------
_POST_RE = re.compile(r"^(?P<base>.+?)(?:\.post(?P<n>\d+))?$")

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

def _next_post_version(base_version: str, existing: Set[str]) -> str:
    m = _POST_RE.match(base_version)
    if not m:
        return base_version
    base = m.group("base")
    cur_post = int(m.group("n") or 0)
    exact_exists = base_version in existing

    max_post = -1
    base_plain_exists = False
    for v in existing:
        mv = _POST_RE.match(v)
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
    meta = _read_pyproject(pyproject)
    project = meta.get("project") or {}
    poetry  = (meta.get("tool") or {}).get("poetry") or {}
    name = project.get("name") or poetry.get("name")
    version = project.get("version") or poetry.get("version")
    if not name or not version:
        raise RuntimeError(f"[project]/[tool.poetry] name and version must be set in {pyproject}")
    existing = fetch_pypi_versions(name)
    if require_network and not existing:
        raise RuntimeError("PyPI availability check required but returned no data (network?).")
    final = _next_post_version(version, existing)
    if final != version:
        write_version(pyproject, final)
        log.info(f"[version] {name}: {version} -> {final} (auto .post bump)")
    else:
        log.debug(f"[version] {name}: {version} (unchanged)")
    return name, final

# ---------- Cleanup ----------
def _rm_rf(p: Path) -> None:
    if p.exists():
        run(["rm", "-rf", str(p)])

def clean_artifacts(root: Path) -> None:
    _rm_rf(root / "dist")
    _rm_rf(root / "build")
    for egg in root.rglob("*.egg-info"):
        _rm_rf(egg)

# ---------- Build (keeps local build.py, avoids shadowing) ----------
def pep517_build(root: Path, python_bin: str, dist: str = "both") -> list[Path]:
    """
    Invoke PyPA 'build' for `root`, ensuring:
      - We don't import a local build.py (remove empty path entry from sys.path[0]).
      - Explicit positional source dir is '.'.
    """
    code = (
        "import sys, os, runpy\n"
        "if sys.path and sys.path[0] == '': sys.path.pop(0)\n"
        "args = []\n"
        "d = os.environ.get('AGI_BUILD_DIST')\n"
        "if d in ('sdist','wheel'):\n"
        "    args.append('--' + d)\n"
        "sys.argv = ['pypa-build-shim'] + args + ['.']\n"
        "runpy.run_module('build.__main__', run_name='__main__')\n"
    )
    env = dict(os.environ)
    env['AGI_BUILD_DIST'] = dist
    run([python_bin, "-c", code], cwd=root, env=env)

    dist_dir = root / "dist"
    return sorted(dist_dir.glob("*")) if dist_dir.exists() else []

# ---------- Upload (auth from ~/.pypirc or external env) ----------
def twine_upload(files: Iterable[Path], python_bin: str, repo: str, *, skip_existing: bool = True,
                 retries: int = 1, twine_opts: Sequence[str] = ()) -> None:
    files = list(files)
    if not files:
        log.info("[upload] nothing to upload")
        return
    cmd = [python_bin, "-m", "twine", "upload", "--non-interactive", "-r", repo, *twine_opts]
    if skip_existing:
        cmd.append("--skip-existing")
    cmd.extend(str(p) for p in files)

    attempt = 0
    while True:
        try:
            run(cmd)  # rely on ~/.pypirc or externally provided env
            return
        except subprocess.CalledProcessError:
            if attempt >= retries:
                raise
            attempt += 1
            wait = min(8 * attempt, 30)
            log.info(f"[upload] error (attempt {attempt}/{retries}); retrying in {wait}s...")
            time.sleep(wait)

# ---------- Symlinks & dotenv ----------
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

def load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

# ---------- CLI ----------
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
    username: str | None  # parsed, ignored
    password: str | None  # parsed, ignored

def parse_args(argv: Sequence[str]) -> tuple[Config, list[str]]:
    ap = argparse.ArgumentParser(description="Build & upload packages with automatic .postN bump (auth via ~/.pypirc).")
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

    # credentials (accepted but intentionally ignored)
    ap.add_argument("--username", "-u", default=None, help="Ignored. Auth is taken from ~/.pypirc or env.")
    ap.add_argument("--password", "-p", default=None, help="Ignored. Auth is taken from ~/.pypirc or env.")

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
    twine_opts.extend(unknown)  # passthrough to twine

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
        username=ns.username,
        password=ns.password,
    )
    return cfg, unknown

# ---------- Main ----------
def _purge_all(package_roots: tuple[Path, ...]) -> None:
    for root in package_roots:
        clean_artifacts(root)

def main(argv: Sequence[str] | None = None) -> None:
    cfg, _unknown = parse_args(sys.argv[1:] if argv is None else argv)
    log.info(f"[config] repo={cfg.repo} python={cfg.python_bin} dist={cfg.dist} "
             f"skip_existing={cfg.skip_existing} retries={cfg.retries} clean={cfg.do_clean}")

    if cfg.symlink_map:
        restore_symlinks(cfg.symlink_map)

    if cfg.cleanup_only:
        _purge_all(cfg.package_roots)
        log.info("[cleanup] completed (cleanup-only)")
        return

    all_artifacts: List[Path] = []
    try:
        for root in cfg.package_roots:
            pyproj = root / "pyproject.toml"
            if not pyproj.exists():
                raise FileNotFoundError(f"Missing pyproject.toml: {pyproj}")

            ensure_unique_version(pyproj, require_network=cfg.strict_online)
            if cfg.do_clean:
                clean_artifacts(root)
            artifacts = pep517_build(root, cfg.python_bin, dist=cfg.dist)
            if not artifacts:
                log.info(f"[build] no artifacts found in {root}/dist")
            all_artifacts.extend(artifacts)

        twine_upload(
            all_artifacts,
            cfg.python_bin,
            cfg.repo,
            skip_existing=cfg.skip_existing,
            retries=cfg.retries,
            twine_opts=cfg.twine_opts,
        )

        if cfg.purge_after:
            _purge_all(cfg.package_roots)
            log.info("[cleanup] purged artifacts after upload]")

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
