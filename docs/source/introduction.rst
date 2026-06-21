Introduction
============

This page gives background and terminology.

If you are new to AGILab, do not start here. Start with :doc:`newcomer-guide`
and :doc:`quick-start`.

What AGILab is
--------------

AGILab turns experimental AI/ML notebooks and scripts into executable,
portable, evidence-backed applications that can run locally or on distributed
workers, while keeping a handoff path to runnable ``agi-core`` notebooks and
MLflow tracking evidence.

You do not need a cluster to get that core value. The primary adoption path is
local: turn a notebook or script into a replayable app with evidence,
artifacts, analysis views, and a notebook or MLflow handoff. Cluster execution
is a scale-out option after the local proof works.

It is a framework and web UI for running Python data, ML, and RL projects
through one visible workflow: create the app, execute it under controlled
runtime choices, inspect artifacts and evidence, then export the result to a
notebook or MLflow handoff when needed.

It has two main user interfaces:

- ``agi-core``: the Python API you can call directly from code or notebooks
- ``agilab``: the web UI that helps select projects, install them, run them,
  and inspect outputs

Shared components include:

- ``agi-env`` for headless environment setup
- ``agi-gui`` for the Streamlit UI dependency bundle and page helpers
- ``agi-web`` for portable, evidence-backed rich web component payloads
- ``agi-node`` for worker/runtime packaging
- ``agi-cluster`` for local and distributed execution

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
