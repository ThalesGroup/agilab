"""Run and download the verified INRIA text notebook adaptation."""
from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
import threading
from types import ModuleType
import zipfile

import streamlit as st

from agilab.agent_runtime.notebook_demo_evidence import render_build_evidence

DEMO_ROOT = Path(__file__).parents[1] / "resources" / "text_notebook_demo"
PUBLIC_FILES = frozenset({
    "app.py", "text_core.py", "solution.ipynb", "lab_stages.toml", "pyproject.toml",
    "requirements.txt", "LICENSE", "DATA_LICENSE", "DATA_SOURCES.md", "NOTICE",
    "README.md", "data/wiki_news.csv", "source/original.ipynb",
})
_APP_LOCK = threading.RLock()


def _read_verified_bundle() -> tuple[dict, dict[str, bytes]]:
    if DEMO_ROOT.is_symlink() or (DEMO_ROOT / "result.json").is_symlink():
        raise ValueError("Text demo directory and receipt must not be symlinks")
    receipt = (DEMO_ROOT / "result.json").read_bytes()
    report = json.loads(receipt)
    if (not isinstance(report, dict) or report.get("status") != "passed"
            or report.get("schema") != "agilab.notebook_agent.public_demo.v1"):
        raise ValueError("Text demo has no supported passed receipt")
    verification = report.get("verification", {})
    for section in (verification, verification.get("text", {}) if isinstance(verification, dict) else {}):
        if (not isinstance(section, dict) or section.get("status") != "passed"
                or not isinstance(section.get("checks"), list) or not section["checks"]
                or any(not isinstance(v, str) or not v.strip() for v in section["checks"])):
            raise ValueError("Text demo verification is incomplete")
    for section, keys in (("source", ("repository", "commit", "url", "license", "sha256")),
                          ("data", ("license", "attribution", "sha256")),
                          ("demo", ("title", "description"))):
        metadata = report.get(section)
        if not isinstance(metadata, dict) or any(
            not isinstance(metadata.get(key), str) or not metadata[key].strip() for key in keys
        ):
            raise ValueError(f"Text demo {section} metadata is incomplete")
    for key in ("run_id", "verification_scope"):
        if not isinstance(report.get(key), str) or not report[key].strip():
            raise ValueError(f"Text demo {key} is missing")
    seconds, stages = report.get("seconds"), report.get("workflow_stages")
    if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds) or seconds <= 0
            or isinstance(stages, bool) or not isinstance(stages, int) or stages < 1):
        raise ValueError("Text demo run metadata is invalid")
    files = report.get("files")
    if not isinstance(files, dict) or set(files) != PUBLIC_FILES:
        raise ValueError("Text demo artifact manifest is incomplete or unexpected")
    payload = {"result.json": receipt}
    for name, expected in sorted(files.items()):
        path = DEMO_ROOT
        for part in PurePosixPath(name).parts:
            path = path / part
            if path.is_symlink():
                raise ValueError(f"Text demo artifact is a symlink: {name}")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError(f"Invalid text demo hash: {name}")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError(f"Text demo artifact changed since verification: {name}")
        payload[name] = content
    if (files["source/original.ipynb"] != report["source"]["sha256"]
            or files["data/wiki_news.csv"] != report["data"]["sha256"]):
        raise ValueError("Text demo provenance does not match its files")
    for path in DEMO_ROOT.rglob("*"):
        if path.is_symlink():
            raise ValueError("Text demo contains a symlink")
        relative = path.relative_to(DEMO_ROOT)
        if path.is_file() and relative.as_posix() not in payload:
            if "__pycache__" not in relative.parts or path.suffix != ".pyc":
                raise ValueError(f"Unverified text demo artifact: {relative}")
    return report, payload


def load_report() -> dict:
    return _read_verified_bundle()[0]


def _zip_bundle(payload: dict[str, bytes]) -> bytes:
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(payload.items()):
            archive.writestr(name, data)
    return content.getvalue()


def download_bundle() -> bytes:
    return _zip_bundle(_read_verified_bundle()[1])


def _run_verified_app(payload: dict[str, bytes]) -> None:
    with _APP_LOCK:
        previous = sys.modules.pop("text_core", None)
        module = ModuleType("text_core")
        module.__file__ = str(DEMO_ROOT / "text_core.py")
        sys.modules["text_core"] = module
        try:
            exec(compile(payload["text_core.py"], module.__file__, "exec"), module.__dict__)
            app_path = str(DEMO_ROOT / "app.py")
            exec(compile(payload["app.py"], app_path, "exec"),
                 {"__name__": "__main__", "__file__": app_path})
        finally:
            sys.modules.pop("text_core", None)
            if previous is not None:
                sys.modules["text_core"] = previous


def render() -> None:
    try:
        report, payload = _read_verified_bundle()
    except (OSError, ValueError, TypeError) as exc:
        st.error(f"Text demo unavailable: {exc}")
        return
    st.caption("TOKKI × AGILAB · NOTEBOOK TO APP")
    render_build_evidence(report)
    with st.expander("Source, recorded build and downloadable workflow"):
        source = report["source"]
        st.markdown(f"Source: [{source['repository']}]({source['url']}) · {source['license']}")
        st.caption("Lesson introduced August 5, 2026 · pinned notebook updated September 2, 2026")
        st.write(f"Corpus: {report['data']['attribution']} · {report['data']['license']}")
        st.caption(f"Run: {report['run_id']} · source commit: {source['commit']}")
        st.write("Interface checks: " + ", ".join(report["verification"]["checks"]))
        st.write("Independent checks: " + ", ".join(report["verification"]["text"]["checks"]))
        st.caption("Checks cover this bounded adaptation, not every experiment in the source lesson. "
                   "Artifact hashes are checked before execution and download.")
        st.download_button("Download the text app and workflow", _zip_bundle(payload),
                           "tokki-agilab-text-atlas.zip", "application/zip", key="text_bundle")
    _run_verified_app(payload)


if __name__ == "__main__":
    render()
