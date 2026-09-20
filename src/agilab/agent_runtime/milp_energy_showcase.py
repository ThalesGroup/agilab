"""Public build-agent receipt and fixed-code AGILAB MILP energy demo."""
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

DEMO_ROOT = Path(__file__).parents[1] / "resources" / "milp_energy_demo"
PUBLIC_FILES = frozenset({
    "app.py", "energy_core.py", "energy_runner.py", "agilab_pool.py",
    "solution.ipynb", "lab_stages.toml", "pyproject.toml", "requirements.txt",
    "README.md", "LICENSE", "AGILAB_LICENSE", "tests.py", "source/original.ipynb", "source/LICENSE",
})


def _read_verified_bundle() -> tuple[dict, dict[str, bytes]]:
    if DEMO_ROOT.is_symlink() or (DEMO_ROOT / "result.json").is_symlink():
        raise ValueError("MILP Energy demo and receipt must not be symlinks")
    receipt = (DEMO_ROOT / "result.json").read_bytes()
    report = json.loads(receipt)
    if (not isinstance(report, dict) or report.get("status") != "passed"
            or report.get("schema") != "agilab.notebook_agent.public_demo.v1"):
        raise ValueError("MILP Energy demo has no supported passed receipt")
    verification = report.get("verification", {})
    for section in (verification, verification.get("milp_energy", {})
                    if isinstance(verification, dict) else {}):
        if (not isinstance(section, dict) or section.get("status") != "passed"
                or not isinstance(section.get("checks"), list) or not section["checks"]
                or any(not isinstance(v, str) or not v.strip() for v in section["checks"])):
            raise ValueError("MILP Energy demo verification is incomplete")
    for section, keys in (("source", ("title", "license", "sha256", "url", "commit", "license_sha256")),
                          ("engine", ("repository", "commit", "path", "sha256"))):
        metadata = report.get(section)
        if not isinstance(metadata, dict) or any(
            not isinstance(metadata.get(key), str) or not metadata[key].strip() for key in keys
        ):
            raise ValueError(f"MILP Energy demo {section} metadata is incomplete")
    if not re.fullmatch(r"[0-9a-f]{40}", report["engine"]["commit"]):
        raise ValueError("AGILAB engine must be pinned to a source commit")
    source = report["source"]
    if (source["license"] != "CC-BY-4.0"
            or not re.fullmatch(r"[0-9a-f]{40}", source["commit"])
            or source["url"] != "https://github.com/PyPSA/PyPSA/blob/"
            + source["commit"] + "/docs/examples/modular-committable.ipynb"):
        raise ValueError("MILP notebook provenance or attribution is invalid")
    if any(not isinstance(report.get(key), str) or not report[key].strip()
           for key in ("run_id", "verification_scope")):
        raise ValueError("MILP Energy build metadata is incomplete")
    seconds, stages = report.get("seconds"), report.get("workflow_stages")
    if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds) or seconds <= 0
            or isinstance(stages, bool) or not isinstance(stages, int) or stages < 1):
        raise ValueError("MILP Energy build timing or stages are invalid")
    files = report.get("files")
    if not isinstance(files, dict) or set(files) != PUBLIC_FILES:
        raise ValueError("MILP Energy artifact manifest is incomplete or unexpected")
    payload = {"result.json": receipt}
    for name, expected in sorted(files.items()):
        path = DEMO_ROOT
        for part in Path(name).parts:
            path = path / part
            if path.is_symlink():
                raise ValueError(f"Symlinked MILP energy artifact: {name}")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError(f"Invalid MILP energy artifact hash: {name}")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError(f"MILP Energy artifact changed since verification: {name}")
        payload[name] = content
    if (files["source/original.ipynb"] != report["source"]["sha256"]
            or files["source/LICENSE"] != report["source"]["license_sha256"]
            or files["agilab_pool.py"] != report["engine"]["sha256"]):
        raise ValueError("MILP Energy source or engine provenance does not match")
    for path in sorted(DEMO_ROOT.rglob("*")):
        if path.is_symlink():
            raise ValueError("MILP Energy demo contains a symlink")
        relative = path.relative_to(DEMO_ROOT)
        if path.is_file() and relative.as_posix() not in payload:
            if "__pycache__" not in relative.parts or path.suffix != ".pyc":
                raise ValueError(f"Unverified MILP energy artifact: {relative}")
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
        return
    names = ("agilab_pool", "energy_core", "energy_runner")
    saved = {name: sys.modules.pop(name, None) for name in names}
    try:
        for name in names:
            module = ModuleType(name)
            module.__file__ = str(DEMO_ROOT / f"{name}.py")
            sys.modules[name] = module
            exec(compile(payload[f"{name}.py"], module.__file__, "exec"), module.__dict__)
        app_path = str(DEMO_ROOT / "app.py")
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
        st.error(f"MILP Energy demo unavailable: {exc}")
        return
    st.caption("TOKKI × AGILAB · NOTEBOOK TO APP")
    render_build_evidence(report)
    with st.expander("Source, recorded build and downloadable workflow"):
        source = report["source"]
        st.markdown(
            f"Adapted from PyPSA contributors' [Modular Expansion with Unit Commitment]({source['url']}) "
            "notebook, introduced February 17, 2026 and updated August 5, 2026. "
            "Notebook and code: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)."
        )
        st.write("Adaptations add an interactive energy lab, the HiGHS solver, configurable scenarios, "
                 "solution checks, and AGILAB batch measurements. PyPSA's library is MIT licensed.")
        engine = report["engine"]
        st.markdown(
            f"Scenario batches use the unchanged [AGILAB pool engine]"
            f"(https://github.com/{engine['repository']}/blob/{engine['commit']}/{engine['path']})."
        )
        st.caption(f"Completed autonomous build: {report['run_id']}")
        st.write("Independent checks cover the pinned notebook and engine, a known optimum, "
                 "infeasibility, physical constraints, cost reconstruction and equivalent scenario batches.")
        st.caption("Scaling measures independent MILP scenarios on this machine, with one HiGHS thread "
                   "per scenario. It does not measure distributed execution or acceleration of one MILP.")
        st.download_button("Download the MILP energy lab and workflow", _zip_bundle(payload),
                           "tokki-agilab-milp-energy.zip", "application/zip", key="milp_energy_bundle")
    _run_verified_app(payload)


if __name__ == "__main__":
    render()
