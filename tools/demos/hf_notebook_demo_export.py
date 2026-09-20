"""Export the fixed, verified notebook showcase for the public Tokki Space."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESOURCE_PATH = "src/agilab/resources/notebook_agent_demo"
RESOURCE_PATHS = (
    RESOURCE_PATH,
    "src/agilab/resources/notebook_agent_local_demo",
)
VERIFIED_FILES = {"app.py", "models.py", "solution.ipynb", "lab_stages.toml"}
SOURCE_FILES = (
    "LICENSE",
    "src/agilab/agent_runtime/notebook_demo_evidence.py",
    "src/agilab/agent_runtime/notebook_app_runtime.py",
    "src/agilab/agent_runtime/notebook_showcase.py",
    "src/agilab/agent_runtime/notebook_verifier.py",
    *(f"{resource}/{name}" for resource in RESOURCE_PATHS
      for name in sorted(VERIFIED_FILES | {"LICENSE", "result.json"})),
)

GENERATED_FILES = {
    "src/agilab/__init__.py": '"""Standalone public demo package."""\n',
    "src/agilab/agent_runtime/__init__.py": '"""Fixed public showcase; no agent provider runtime."""\n',
    "hf_app.py": (
        "import streamlit as st\n"
        "from agilab.agent_runtime.notebook_showcase import render\n"
        "render()\n"
        'st.set_page_config(page_title="Tokki · Notebook to working app", layout="wide")\n'
    ),
    "README.md": """---
title: Tokki · Notebook to working app
emoji: 🚀
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
license: bsd-3-clause
---

# Tokki · One request, a verified app

Compare two verified Iris builds: the original GPT-6 Astra version and a local
Qwen 3.8 27B version. Both are completed apps integrated with AGILAB.
Change the model controls and rerun the notebook, model and interface checks.
No account or AI provider subscription is needed to try this completed app.

**Build from your own notebook:** open that panel in the app to set up the local
builder with your own Tokki installation and provider. No provider credentials,
private Tokki runtime, license or notebook uploads are hosted by this Space.

- [Tokki](https://github.com/jpmorard/tokki-public)
- [AGILAB and local notebook setup](https://github.com/ThalesGroup/agilab#build-from-your-own-notebook)

The public showcase code is from AGILAB under the root BSD-3-Clause LICENSE.
Both bundled apps adapt Aurélien Géron's handson-ml3 decision-tree notebook;
Their Apache-2.0 license and pinned source provenance are retained in
`src/agilab/resources/notebook_agent_demo/` and
`src/agilab/resources/notebook_agent_local_demo/`.
""",
    "requirements.txt": "streamlit==1.64.0\nscikit-learn==1.9.1\nmatplotlib==3.10.8\n",
    "Dockerfile": """FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONPATH=/app/src
RUN cd /app/src/agilab/resources/notebook_agent_demo && python /app/src/agilab/agent_runtime/notebook_verifier.py
RUN cd /app/src/agilab/resources/notebook_agent_local_demo && python /app/src/agilab/agent_runtime/notebook_verifier.py
EXPOSE 7860
CMD ["streamlit", "run", "hf_app.py", "--server.address=0.0.0.0", "--server.port=7860", "--server.headless=true", "--browser.gatherUsageStats=false"]
""",
}


def export(destination: Path, *, source_root: Path = ROOT) -> dict:
    if destination.is_symlink():
        raise ValueError("Destination must not be a symlink")
    destination = destination.resolve()
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError("Destination must be new or empty")
    source_root = source_root.resolve()
    payload = {}
    for name in SOURCE_FILES:
        source = source_root / name
        if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(source_root):
            raise ValueError(f"Invalid public source file: {name}")
        payload[name] = source.read_bytes()
    for resource in RESOURCE_PATHS:
        report = json.loads(payload[f"{resource}/result.json"])
        if report.get("status") != "passed" or set(report.get("files", {})) != VERIFIED_FILES:
            raise ValueError(f"Expected the complete verified demo report: {resource}")
        for name, expected in report["files"].items():
            if hashlib.sha256(payload[f"{resource}/{name}"]).hexdigest() != expected:
                raise ValueError(f"Demo artifact changed: {resource}/{name}")
    payload.update({name: text.encode("utf-8") for name, text in GENERATED_FILES.items()})
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(payload.items())}
    payload["PUBLIC_HASHES.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    for name, data in payload.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return {"files": sorted(payload), "sha256": {
        name: hashlib.sha256(data).hexdigest() for name, data in sorted(payload.items())
    }}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(export(args.destination), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
