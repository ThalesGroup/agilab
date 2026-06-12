"""Shared Cython build-tool configuration for AGILAB worker builds."""

import hashlib
import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

CYTHON_BUILD_REQUIREMENT = "cython==3.2.4"
CYTHON_CACHE_ENV = "AGILAB_CYTHON_CACHE"
CYTHON_TYPE_PREPROCESS_ENV = "AGILAB_CYTHON_TYPE_PREPROCESS"
CYTHON_DIRECTIVES_ENV = "AGILAB_CYTHON_DIRECTIVES"
CYTHON_ANNOTATE_ENV = "AGILAB_CYTHON_ANNOTATE"
CYTHON_DISABLE_BUILD_CACHE_ENV = "AGILAB_DISABLE_WORKER_BUILD_CACHE"
CYTHON_PYX_STAMP_PREFIX = "# agilab-pyx:"
CYTHON_PREVIEW_REPORT_SUFFIX = ".cython-preview.json"
CYTHON_BUILD_STAMP_FILENAME = ".agilab-cython-build-stamp.json"

CYTHON_FLAG_TRUE_VALUES = frozenset({"1", "true", "yes", "on", "enable", "enabled"})
CYTHON_FLAG_FALSE_VALUES = frozenset({"0", "false", "no", "off", "disable", "disabled"})

# Worker code is arbitrary user-authored Python: cdivision and infer_types are
# intentionally opt-in because they can change results on unaudited workers.
CYTHON_DIRECTIVE_ALLOWLIST = frozenset(
    {
        "boundscheck",
        "wraparound",
        "cdivision",
        "initializedcheck",
        "infer_types",
        "overflowcheck",
        "nonecheck",
        "embedsignature",
        "profile",
        "linetrace",
    }
)
# Named bundle removing index checks only; deliberately excludes cdivision,
# which changes arithmetic results instead of just removing checks.
CYTHON_UNCHECKED_BUNDLE: dict[str, bool] = {
    "boundscheck": False,
    "wraparound": False,
    "initializedcheck": False,
    "nonecheck": False,
}

_PROJECT_CYTHON_TABLE_KEYS = ("tool", "agilab", "cython")
_PROJECT_CYTHON_ALLOWED_FIELDS = frozenset({"enabled", "directives"})


class ProjectCythonConfig(NamedTuple):
    """Per-project ``[tool.agilab.cython]`` settings from pyproject.toml."""

    enabled: bool | None
    directives: str | None
    pyproject_path: Path | None


def cython_directives_spec_disables_defaults(spec: str) -> bool:
    """Return whether a directives spec opts out of the framework defaults."""

    return spec.strip().lower() in CYTHON_FLAG_FALSE_VALUES


def parse_cython_directive_overrides(
    raw_value: str,
    *,
    source: str | None = None,
) -> dict[str, bool]:
    """Parse an ``AGILAB_CYTHON_DIRECTIVES``-style spec through the hard allowlist.

    ``source`` (the env var name, a pyproject path, or a CLI flag) is named in
    every error so a misdeclared project config points at the offending file.
    """

    suffix = f" (from {source})" if source else ""
    directives: dict[str, bool] = {}
    for item in raw_value.split(","):
        part = item.strip()
        if not part:
            continue
        if part == "unchecked":
            directives.update(CYTHON_UNCHECKED_BUNDLE)
            continue
        if "=" not in part:
            key, value = part, "true"
        else:
            key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip().lower()
        if not key:
            continue
        if key not in CYTHON_DIRECTIVE_ALLOWLIST:
            # A typo silently dropping a safety directive is worse than failing.
            raise ValueError(
                f"Unknown Cython compiler directive {key!r}{suffix}; allowed: "
                f"unchecked, {', '.join(sorted(CYTHON_DIRECTIVE_ALLOWLIST))}"
            )
        if value in CYTHON_FLAG_TRUE_VALUES:
            directives[key] = True
        elif value in CYTHON_FLAG_FALSE_VALUES:
            directives[key] = False
        else:
            raise ValueError(
                f"Unsupported Cython directive boolean value for {key!r}: {value!r}{suffix}"
            )
    return directives


def validate_cython_directives_spec(spec: str, *, source: str | None = None) -> None:
    """Hard-fail on unknown directive names before any build subprocess runs."""

    if cython_directives_spec_disables_defaults(spec):
        return
    parse_cython_directive_overrides(spec, source=source)


def read_project_cython_config(project_dir) -> ProjectCythonConfig:
    """Read ``[tool.agilab.cython]`` from a worker project's pyproject.toml.

    A missing pyproject means "nothing declared"; a malformed table or an
    unknown field is a hard error naming the file, matching the
    typo-is-worse-than-failing policy used for directive names.
    """

    if project_dir is None:
        return ProjectCythonConfig(None, None, None)
    pyproject_path = Path(project_dir).expanduser() / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except OSError:
        return ProjectCythonConfig(None, None, None)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid TOML in {pyproject_path}: {exc}") from exc

    table: object = data
    for key in _PROJECT_CYTHON_TABLE_KEYS:
        table = table.get(key, {}) if isinstance(table, dict) else {}
    if not isinstance(table, dict) or not table:
        return ProjectCythonConfig(None, None, pyproject_path)

    unknown = sorted(set(table) - _PROJECT_CYTHON_ALLOWED_FIELDS)
    if unknown:
        raise ValueError(
            f"Unknown [tool.agilab.cython] keys {unknown} in {pyproject_path}; "
            f"allowed: {', '.join(sorted(_PROJECT_CYTHON_ALLOWED_FIELDS))}"
        )
    enabled = table.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise ValueError(
            f"[tool.agilab.cython].enabled must be a boolean in {pyproject_path}, "
            f"got {enabled!r}"
        )
    directives = table.get("directives")
    if directives is not None and not isinstance(directives, str):
        raise ValueError(
            f"[tool.agilab.cython].directives must be a string in {pyproject_path}, "
            f"got {directives!r}"
        )
    return ProjectCythonConfig(enabled, directives, pyproject_path)


def resolve_cython_directives_spec(
    *,
    environ: Mapping[str, str] | None = None,
    env_value: str | None = None,
    project_dir=None,
) -> tuple[str | None, str | None]:
    """Resolve the effective directives spec and the source it came from.

    Precedence: ``AGILAB_CYTHON_DIRECTIVES`` (env var, or a pre-resolved
    ``env_value``) > project ``[tool.agilab.cython].directives`` > framework
    default (``None`` — callers apply their own safe defaults).
    """

    if env_value is None:
        if environ is None:
            environ = os.environ
        env_value = environ.get(CYTHON_DIRECTIVES_ENV)
    env_spec = (str(env_value) if env_value is not None else "").strip()
    if env_spec:
        return env_spec, CYTHON_DIRECTIVES_ENV
    config = read_project_cython_config(project_dir)
    if config.directives is not None and config.directives.strip():
        return config.directives.strip(), str(config.pyproject_path)
    return None, None


def cython_build_overlay_specs() -> tuple[str, str]:
    """Return uv ``--with`` specs needed by worker build subprocesses."""

    return ("setuptools", CYTHON_BUILD_REQUIREMENT)


def cython_source_sha256(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def cython_pyx_stamp_line(source: str, *, type_preprocess: bool) -> str:
    return (
        f"{CYTHON_PYX_STAMP_PREFIX} "
        f"src-sha256={cython_source_sha256(source)} "
        f"type-preprocess={int(bool(type_preprocess))}"
    )


def add_cython_pyx_stamp(source: str, *, stamp_line: str) -> str:
    """Insert a generated-source stamp outside the PEP 263 line-1/2 window."""

    lines = source.splitlines(keepends=True)
    insert_at = min(2, len(lines))
    newline = "" if stamp_line.endswith("\n") else "\n"
    return "".join([*lines[:insert_at], stamp_line, newline, *lines[insert_at:]])


def cython_pyx_stamp_matches(pyx_source: str, source: str, *, type_preprocess: bool) -> bool:
    expected = cython_pyx_stamp_line(source, type_preprocess=type_preprocess)
    return any(line.rstrip("\r\n") == expected for line in pyx_source.splitlines()[:8])


__all__ = [
    "CYTHON_PYX_STAMP_PREFIX",
    "CYTHON_BUILD_REQUIREMENT",
    "CYTHON_CACHE_ENV",
    "CYTHON_DIRECTIVES_ENV",
    "CYTHON_DIRECTIVE_ALLOWLIST",
    "CYTHON_ANNOTATE_ENV",
    "CYTHON_DISABLE_BUILD_CACHE_ENV",
    "CYTHON_FLAG_FALSE_VALUES",
    "CYTHON_FLAG_TRUE_VALUES",
    "CYTHON_PREVIEW_REPORT_SUFFIX",
    "CYTHON_BUILD_STAMP_FILENAME",
    "CYTHON_TYPE_PREPROCESS_ENV",
    "CYTHON_UNCHECKED_BUNDLE",
    "ProjectCythonConfig",
    "add_cython_pyx_stamp",
    "cython_build_overlay_specs",
    "cython_directives_spec_disables_defaults",
    "cython_pyx_stamp_line",
    "cython_pyx_stamp_matches",
    "cython_source_sha256",
    "parse_cython_directive_overrides",
    "read_project_cython_config",
    "resolve_cython_directives_spec",
    "validate_cython_directives_spec",
]
