"""Shared Cython build-tool configuration for AGILAB worker builds."""

import hashlib

CYTHON_BUILD_REQUIREMENT = "cython==3.2.4"
CYTHON_CACHE_ENV = "AGILAB_CYTHON_CACHE"
CYTHON_TYPE_PREPROCESS_ENV = "AGILAB_CYTHON_TYPE_PREPROCESS"
CYTHON_DIRECTIVES_ENV = "AGILAB_CYTHON_DIRECTIVES"
CYTHON_ANNOTATE_ENV = "AGILAB_CYTHON_ANNOTATE"
CYTHON_DISABLE_BUILD_CACHE_ENV = "AGILAB_DISABLE_WORKER_BUILD_CACHE"
CYTHON_PYX_STAMP_PREFIX = "# agilab-pyx:"
CYTHON_PREVIEW_REPORT_SUFFIX = ".cython-preview.json"
CYTHON_BUILD_STAMP_FILENAME = ".agilab-cython-build-stamp.json"


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
    "CYTHON_ANNOTATE_ENV",
    "CYTHON_DISABLE_BUILD_CACHE_ENV",
    "CYTHON_PREVIEW_REPORT_SUFFIX",
    "CYTHON_BUILD_STAMP_FILENAME",
    "CYTHON_TYPE_PREPROCESS_ENV",
    "add_cython_pyx_stamp",
    "cython_build_overlay_specs",
    "cython_pyx_stamp_line",
    "cython_pyx_stamp_matches",
    "cython_source_sha256",
]
