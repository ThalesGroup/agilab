Introduction
============

This page gives background and terminology.

If you are new to AGILab, do not start here. Start with :doc:`newcomer-guide`
and :doc:`quick-start`.

What AGILab is
--------------

AGILab turns experimental AI/ML notebooks and scripts into executable,
portable, evidence-backed applications. The codebase splits that path into the
published core/runtime packages under ``src/agilab/core`` and optional UI,
page, web, and packaged-app libraries under ``src/agilab/lib``.

You do not need a cluster to get that core value. The primary adoption path is
local: turn a notebook or script into a replayable app with evidence,
artifacts, analysis views, and a notebook or MLflow handoff. Cluster execution
is a scale-out option after the local proof works.

It is a framework and web UI for running Python data, ML, and RL projects
through one visible workflow: create the app, execute it under controlled
runtime choices, inspect artifacts and evidence, then export the result to a
notebook or MLflow handoff when needed.

The flagship loop is:

1. import or create a notebook, script, or app project;
2. run it through a controlled local environment first;
3. capture artifacts plus ``run_manifest.json`` evidence;
4. inspect and compare outputs in ANALYSIS, notebook export, MLflow handoff, or
   proof-pack tools;
5. promote the result only when the evidence, package contract, and release
   proof are coherent.

That loop is the practical boundary for AGILAB as an ML workbench: it makes
exploratory work replayable before a team chooses a heavier tracker, registry,
cluster, or production platform.

It has two primary entry points:

- ``agi-core``: the Python API you can call directly from code or notebooks.
- ``agilab``: the source checkout / packaged CLI and web UI that helps select
  projects, install them, run them, and inspect outputs.

The published package map in this checkout is:

- ``src/agilab/core/agi-core`` for the notebook/API runtime.
- ``src/agilab/core/agi-env`` for headless environment setup and shared runtime
  helpers.
- ``src/agilab/core/agi-node`` for worker/runtime packaging.
- ``src/agilab/core/agi-cluster`` for local and distributed execution.
- ``src/agilab/lib/agi-gui`` for the Streamlit UI dependency bundle and page
  helpers.
- ``src/agilab/lib/agi-pages`` for packaged page bundles.
- ``src/agilab/lib/agi-web`` for portable, evidence-backed rich web component
  payloads.
- ``src/agilab/lib/agi-apps`` plus ``src/agilab/lib/agi-app-*`` projects for
  packaged application distributions.

Historical note
---------------

AGILab started as a playground around ``agi-core``.

That is still visible in the product structure today:

- you can use the web UI for an app-oriented workflow
- or you can use ``agi-core`` directly when you only need the execution layer

Why the project is built this way
---------------------------------

The design goal is not to replace every MLOps or orchestration tool. The design
goal is to make experimentation easier to run, replay, and inspect before a
team commits to heavier platform choices.

The technical choices are driven by three practical goals:

- **Portability**: keep projects runnable across local machines and SSH-accessed
  workers without full VM or container infrastructure as a starting point
- **Simplicity**: keep environment setup, execution, and analysis visible in one
  workflow
- **Performance**: allow different execution modes such as pure Python, Cython,
  and local or distributed runs

Main dependencies
-----------------

AGILab relies on a small set of core technologies:

- `uv <https://docs.astral.sh/uv/>`_ for Python environment management
- `Streamlit <https://streamlit.io/>`_ for the web UI
- `Dask <https://www.dask.org/>`_ for distributed execution support
- `asyncssh <https://asyncssh.readthedocs.io/en/stable/>`_ for SSH-based remote execution
- `Cython <https://cython.org/>`_ for optional compiled execution paths

Optional helpers include OpenAI-compatible models and local assistants such as
Ollama and GPT-OSS when configured.

.. note::
   Native Windows is covered for the released package CLI first-proof smoke.
   Source-checkout installer scripts, cluster workflows, and some
   local-assistant features still work best through WSL2 or platform-specific
   setup while native parity continues.

What to read next
-----------------

- :doc:`newcomer-guide` for the first-proof path
- :doc:`quick-start` for the install and launch commands
- :doc:`features` for the current capability list
- :doc:`agilab-mlops-positioning` for toolchain fit and framework comparison
- :doc:`architecture` for the full stack overview
