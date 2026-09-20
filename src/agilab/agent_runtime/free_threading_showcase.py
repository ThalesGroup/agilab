"""Public build-agent receipt and fixed-code AGILAB free-threading demo."""
from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path
import re
import sys
from types import ModuleType
import zipfile

import streamlit as st

from agilab.agent_runtime.notebook_demo_evidence import render_build_evidence
from agilab.agent_runtime.notebook_app_runtime import APP_EXECUTION_LOCK as _APP_LOCK
from agilab.agent_runtime.notebook_app_runtime import app_session_state

DEMO_ROOT = Path(__file__).parents[1] / "resources" / "free_threading_demo"
PUBLIC_FILES = frozenset({
    "app.py", "free_threading_core.py", "benchmark.py", "agilab_pool.py",
    "solution.ipynb", "lab_stages.toml", "pyproject.toml", "requirements.txt",
    "README.md", "LICENSE", "tests.py", "source/original.ipynb",
})


def _read_verified_bundle() -> tuple[dict, dict[str, bytes]]:
    if DEMO_ROOT.is_symlink() or (DEMO_ROOT / "result.json").is_symlink():
        raise ValueError("Free-threading demo and receipt must not be symlinks")
    receipt = (DEMO_ROOT / "result.json").read_bytes()
    report = json.loads(receipt)
    if (not isinstance(report, dict) or report.get("status") != "passed"
            or report.get("schema") != "agilab.notebook_agent.public_demo.v1"):
        raise ValueError("Free-threading demo has no supported passed receipt")
    if "build_model" in report:
        model = report["build_model"]
        if not isinstance(model, dict) or any(
            not isinstance(model.get(key), str) or not model[key].strip()
            for key in ("id", "provider", "execution")
        ):
            raise ValueError("Free-threading demo build model metadata is invalid")
    verification = report.get("verification", {})
    for section in (verification, verification.get("free_threading", {})
                    if isinstance(verification, dict) else {}):
        if (not isinstance(section, dict) or section.get("status") != "passed"
                or not isinstance(section.get("checks"), list) or not section["checks"]
                or any(not isinstance(v, str) or not v.strip() for v in section["checks"])):
            raise ValueError("Free-threading demo verification is incomplete")
    for section, keys in (("source", ("title", "license", "sha256")),
                          ("engine", ("repository", "commit", "path", "sha256"))):
        metadata = report.get(section)
        if not isinstance(metadata, dict) or any(
            not isinstance(metadata.get(key), str) or not metadata[key].strip() for key in keys
        ):
            raise ValueError(f"Free-threading demo {section} metadata is incomplete")
    if not re.fullmatch(r"[0-9a-f]{40}", report["engine"]["commit"]):
        raise ValueError("AGILAB engine must be pinned to a source commit")
    if any(not isinstance(report.get(key), str) or not report[key].strip()
           for key in ("run_id", "verification_scope")):
        raise ValueError("Free-threading build metadata is incomplete")
    seconds, stages = report.get("seconds"), report.get("workflow_stages")
    if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds) or seconds <= 0
            or isinstance(stages, bool) or not isinstance(stages, int) or stages < 1):
        raise ValueError("Free-threading build timing or stages are invalid")
    files = report.get("files")
    if not isinstance(files, dict) or set(files) != PUBLIC_FILES:
        raise ValueError("Free-threading artifact manifest is incomplete or unexpected")
    payload = {"result.json": receipt}
    for name, expected in sorted(files.items()):
        path = DEMO_ROOT
        for part in Path(name).parts:
            path = path / part
            if path.is_symlink():
                raise ValueError(f"Symlinked free-threading artifact: {name}")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError(f"Invalid free-threading artifact hash: {name}")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError(f"Free-threading artifact changed since verification: {name}")
        payload[name] = content
    if (files["source/original.ipynb"] != report["source"]["sha256"]
            or files["agilab_pool.py"] != report["engine"]["sha256"]):
        raise ValueError("Free-threading source or engine provenance does not match")
    for path in sorted(DEMO_ROOT.rglob("*")):
        if path.is_symlink():
            raise ValueError("Free-threading demo contains a symlink")
        relative = path.relative_to(DEMO_ROOT)
        if path.is_file() and relative.as_posix() not in payload:
            if "__pycache__" not in relative.parts or path.suffix != ".pyc":
                raise ValueError(f"Unverified free-threading artifact: {relative}")
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
    # These generated top-level imports are scoped just like the other demos.
    # Do not queue overlapping public benchmarks or hold visitors waiting.
    if not _APP_LOCK.acquire(blocking=False):
        st.info("Another notebook demo session is running. Try again shortly.")
        st.button("Retry demo", key="threading_retry")
        return
    names = ("agilab_pool", "free_threading_core", "benchmark")
    saved = {name: sys.modules.pop(name, None) for name in names}
    try:
        for name in names:
            module = ModuleType(name)
            module.__file__ = str(DEMO_ROOT / f"{name}.py")
            sys.modules[name] = module
            exec(compile(payload[f"{name}.py"], module.__file__, "exec"), module.__dict__)
        app_path = str(DEMO_ROOT / "app.py")
        with app_session_state(st.session_state, "threading", ("analysis", "analysis_signature", "benchmark_result", "benchmark_signature")):
            exec(compile(payload["app.py"], app_path, "exec"),
                 {"__name__": "__main__", "__file__": app_path})
    finally:
        for name in names:
            sys.modules.pop(name, None)
            if saved[name] is not None:
                sys.modules[name] = saved[name]
        _APP_LOCK.release()


def render() -> None:
    try:
        report, payload = _read_verified_bundle()
    except (OSError, ValueError, TypeError) as exc:
        st.error(f"Free-threading demo unavailable: {exc}")
        return
    st.caption("TOKKI × AGILAB · NOTEBOOK TO APP")
    render_build_evidence(report)
    if model := report.get("build_model"):
        st.caption(f"Build model: {model['id']} ({model['execution']} · {model['provider']}).")
    with st.expander("Source, recorded build and downloadable workflow"):
        st.write("Original AGILAB benchmark notebook · September 19, 2026 · BSD-3-Clause")
        engine = report["engine"]
        st.markdown(
            f"Execution uses the unchanged [AGILAB pool engine]"
            f"(https://github.com/{engine['repository']}/blob/{engine['commit']}/{engine['path']})."
        )
        st.caption(f"Completed autonomous build: {report['run_id']}")
        st.write("Independent checks cover the original engine, image calculations, actual GIL "
                 "state, identical results, complete tile collection, and repeated timings.")
        st.caption("This measures the bundled AGILAB pool engine on one machine. "
                   "It does not certify the whole AGILAB dependency stack for free-threaded Python.")
        st.download_button("Download the free-threading app and workflow", _zip_bundle(payload),
                           "tokki-agilab-free-threading.zip", "application/zip", key="threading_bundle")
    _run_verified_app(payload)


if __name__ == "__main__":
    render()
