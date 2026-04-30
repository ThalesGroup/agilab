import sys
import os
import tomllib
from importlib import metadata as importlib_metadata
from pathlib import Path
import subprocess
from unittest import mock

repo_root = Path(__file__).resolve().parents[2]
agi_path: Path | None = None

try:
    agi_path_storage = Path("~/.local/share/agilab/.agilab-path").expanduser()
    agi_path = Path(agi_path_storage.read_text().strip())
except Exception as e:
    print(
        "Warning: unable to locate AGILAB path for docs build "
        f"({e}). Continuing with minimal sys.path."
    )


def _add_path(path: Path) -> None:
    if path.exists():
        path_str = str(path)
        if path_str not in sys.path:
            print(f"Adding {path_str} to sys.path")
            sys.path.insert(0, path_str)


def _add_core_paths(core_root: Path) -> None:
    for rel in ("agi-env/src", "agi-node/src", "agi-cluster/src", "agi-core/src"):
        _add_path(core_root / rel)


def _add_agilab_lib_paths(agilab_package_root: Path) -> None:
    _add_path(agilab_package_root / "lib/agi-gui/src")


# Prefer the pinned public framework submodule when present.
if (repo_root / ".external/agilab/src").exists():
    _add_path(repo_root / ".external/agilab/src")
if (repo_root / ".external/agilab/src/agilab").exists():
    _add_agilab_lib_paths(repo_root / ".external/agilab/src/agilab")
if (repo_root / ".external/agilab/src/agilab/core").exists():
    _add_core_paths(repo_root / ".external/agilab/src/agilab/core")

# Legacy fallback: local `core` symlink in older developer checkouts.
if (repo_root / "core").exists():
    _add_core_paths(repo_root / "core")

# Fallback: use the upstream checkout recorded by `~/.local/share/agilab/.agilab-path`.
if agi_path is not None:
    # `.agilab-path` commonly points at `<repo>/src/agilab`. Add the parent so
    # `import agilab` works, while still supporting a repo-root path.
    if agi_path.name == "agilab" and (agi_path / "__init__.py").exists():
        _add_path(agi_path.parent)
        _add_agilab_lib_paths(agi_path)

    _add_path(agi_path / "src")
    if (agi_path / "src/agilab/core").exists():
        _add_agilab_lib_paths(agi_path / "src/agilab")
        _add_core_paths(agi_path / "src/agilab/core")
    elif (agi_path / "core").exists():
        _add_core_paths(agi_path / "core")

try:
    from agi_env import AgiEnv  # noqa: F401  # Optional at build time
except Exception as e:
    print(f"Warning: agi_env unavailable during docs build: {e}")

# -- Path Setup --------------------------------------------------------------


# Autodoc should describe the checkout being built. Keep `.agilab-path` only as
# an import fallback above; scanning it here can document stale generated apps.
project_root = repo_root
for proj in [
    "*project",
    "agilab/cluster",
    "agilab/node",
    "agilab/env",
]:
    for src in project_root.rglob(f"{proj}/src"):
        path = str(src)
        if not src.exists():
            print(path, "does not exist; skipping")
            continue
        if path not in sys.path:
            print(f"Adding {path} to sys.path")
            sys.path.insert(0, path)

# -- Project Information -----------------------------------------------------


def _resolve_agilab_repo_root() -> Path | None:
    if agi_path is None:
        return None

    if agi_path.name == "agilab" and agi_path.parent.name == "src":
        return agi_path.parent.parent

    if (agi_path / "pyproject.toml").exists():
        return agi_path

    if (agi_path.parent / "pyproject.toml").exists():
        return agi_path.parent

    return None


def _read_pyproject_version(pyproject_path: Path) -> str | None:
    try:
        project_data = tomllib.loads(pyproject_path.read_text())
        version_value = project_data.get("project", {}).get("version")
        if isinstance(version_value, str) and version_value.strip():
            return version_value.strip()
    except Exception as e:
        print(f"Warning: unable to read docs version from {pyproject_path}: {e}")
    return None


def _read_git_version(repo_path: Path) -> str | None:
    try:
        version_value = subprocess.check_output(
            [
                "git",
                "-C",
                str(repo_path),
                "describe",
                "--tags",
                "--dirty",
                "--always",
                "--match",
                "v*",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if version_value.startswith("v"):
            version_value = version_value[1:]
        return version_value or None
    except Exception:
        return None


def _resolve_docs_version() -> str:
    candidate_roots = []
    for root in (_resolve_agilab_repo_root(), repo_root):
        if root is not None and root not in candidate_roots:
            candidate_roots.append(root)

    for root in candidate_roots:
        version_value = _read_git_version(root)
        if version_value is not None:
            return version_value

    for root in candidate_roots:
        pyproject_path = root / "pyproject.toml"
        if pyproject_path.exists():
            version_value = _read_pyproject_version(pyproject_path)
            if version_value is not None:
                return version_value

    try:
        return importlib_metadata.version("agilab")
    except Exception as e:
        print(f"Warning: unable to read installed AGILab version: {e}")

    return "dev"


project = "AGILab"
author = "Jean-Pierre MORARD"
copyright = "2026, THALES SIX GTS France SAS"
release = _resolve_docs_version()
version = release

# -- General Configuration ---------------------------------------------------

# Build extensions list dynamically so docs can build even if some plugins
import importlib
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]

_enabled_optional_exts: set[str] = set()


def _try_add(ext_mod: str):
    try:
        importlib.import_module(ext_mod)
        extensions.append(ext_mod)
        _enabled_optional_exts.add(ext_mod)
    except Exception:
        print(f"Warning: Sphinx extension not available: {ext_mod}")

# Optional extensions
for ext in [
    "myst_parser",
    "sphinx_autodoc_typehints",
    "sphinx.ext.coverage",
    "sphinx.ext.inheritance_diagram",
    "sphinx.ext.mathjax",
    "sphinx_pyreverse",
    "sphinx.ext.graphviz",
    "sphinx_design",
    "sphinx_tabs.tabs",
]:
    _try_add(ext)

# Exclude patterns
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
suppress_warnings = [
    # Some optional diagram extensions register overlapping directives.
    "app.add_directive",
]

autodoc_mock_imports = [
    # Prevent heavy optional deps from breaking the build when absent
    "psutil",
    "asyncssh",
    # Dask is required by agi_cluster but not always installed in docs envs.
    "dask",
    "dask.distributed",
    "distributed",
]

# -- MyST Parser Configuration -----------------------------------------------

_has_myst = "myst_parser" in _enabled_optional_exts

# Specify source file extensions, enabling Markdown only when MyST is available
source_suffix = {
    ".rst": "restructuredtext",
}
if _has_myst:
    source_suffix[".md"] = "markdown"
else:
    print("Warning: myst_parser missing; Markdown sources will be skipped.")

# Configure MyST settings if needed
myst_enable_extensions = []
if _has_myst:
    myst_enable_extensions = [
        "amsmath",
        "attrs_inline",
        "colon_fence",
        "deflist",
        "dollarmath",
        "fieldlist",
        "html_admonition",
        "html_image",
        "linkify",
        "replacements",
        "smartquotes",
        "strikethrough",
        "substitution",
        "tasklist",
    ]
_github_repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
if "/" in _github_repository:
    _github_owner, _github_repo = _github_repository.split("/", 1)
    html_baseurl = f"https://{_github_owner}.github.io/{_github_repo}"
else:
    html_baseurl = "https://thalesgroup.github.io/agilab"

# -- Templates Path ----------------------------------------------------------

templates_path = ["_templates"]

# -- Autodoc Configuration ---------------------------------------------------

# Options for autodoc
autodoc_default_options = {
    "members": True,  # Include all members
    "undoc-members": True,  # Include members without docstrings
    "private-members": False,  # Exclude private members
    "special-members": "__init__",  # Include special members like __init__
    "inherited-members": False,  # Avoid expanding third-party base classes
    "show-inheritance": True,  # Show class inheritance
}
autodoc_typehints = "none"

# -- Napoleon Configuration --------------------------------------------------

# Napoleon settings for Google and NumPy docstrings
napoleon_google_docstring = True
napoleon_numpy_docstring = True

nitpick_ignore_regex = [
    ("py:class", r"Path|pathlib\.Path|optional|any|pl\.DataFrame|collections\.abc\.Mapping"),
    ("py:class", r"ConfigDict|IncEx|DeprecatedParseProtocol|MappingNamespace"),
    ("py:class", r"types\.SimpleNamespace|abc\.ABC|polars\.dataframe\.frame\.DataFrame"),
    ("py:class", r"pandas\.core\.frame\.DataFrame"),
    ("py:class", r"AnnAssign|ast\.(?:Node|ClassDef|For|FunctionDef|AST|Import|ImportFrom)"),
    ("py:class", r"AST node|node|ast\.NodeTransformer|BaseWorker|pd\.DataFrame"),
    ("py:class", r"pydantic\.main\.BaseModel"),
    ("py:class", r"agi_cluster\.agi_distributor\.run_request_support\.RunRequest"),
    ("py:class", r"pathlib\._local\.Path|pathspec\.pathspec\.PathSpec"),
    ("py:class", r"agi_env\.content_renamer_support\.ContentRenamer"),
    ("py:exc", r"None|None\.|ValidationError"),
    ("py:data", r"typing\.(?:Any|Tuple)"),
    ("py:func", r"AgiEnv\._build_env"),
    ("py:mod", r"logging"),
]

# -- HTML Output Configuration -----------------------------------------------

html_theme = "sphinx_rtd_theme"  # Specify the theme

# Logo # put your SVG in, say, _static/agi_logo.svg
html_logo = "logo/agi_logo.svg"
display_version = True
html_context = {
    "docs_version": release,
}

# Theme options
html_theme_options = {
    "navigation_depth": 4,
    "collapse_navigation": False,
    "prev_next_buttons_location": "bottom",
}

# Static files path
html_static_path = ["_static"]

# Custom CSS files
html_css_files = [
    "custom.css",  # Add your custom CSS file if you have one
]

# Sphinx Tabs compatibility with docutils>=0.21 removes the ``backrefs`` key. Guard
# against the missing attribute so the HTML builder keeps working after upgrades.
try:
    from sphinx_tabs import tabs as _sphinx_tabs

    def _safe_tabs_visit(translator, node):
        attrs = node.attributes.copy()
        for key in ("classes", "ids", "names", "dupnames", "backrefs"):
            attrs.pop(key, None)
        text = translator.starttag(node, node.tagname, **attrs)
        translator.body.append(text.strip())

    _sphinx_tabs.visit = _safe_tabs_visit
except Exception as e:
    print(f"Warning: sphinx_tabs not available ({e}); skipping compatibility patch.")

# -- Additional Configurations (Optional) ------------------------------------


# -- End of conf.py ----------------------------------------------------------
