Introduction
============

This page gives background and terminology.

If you are new to AGILab, do not start here. Start with :doc:`newcomer-guide`
and :doc:`quick-start`.

What AGILab is
--------------

AGILab is a framework and web UI for running Python data, ML, and RL projects
through one visible workflow.

It has two main user interfaces:

- ``agi-core``: the Python API you can call directly from code or notebooks
- ``agilab``: the web UI that helps select projects, install them, run them,
  and inspect outputs

Shared components include:

- ``agi-env`` for environment setup
- ``agi-gui`` for Streamlit UI/page dependencies
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
   Windows support is still catching up. Some local-assistant features remain
   partial while that work continues.

What to read next
-----------------

- :doc:`newcomer-guide` for the first-proof path
- :doc:`quick-start` for the install and launch commands
- :doc:`features` for the current capability list
- :doc:`agilab-mlops-positioning` for toolchain fit and framework comparison
- :doc:`architecture` for the full stack overview
