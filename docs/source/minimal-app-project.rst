Minimal App Project
===================

Overview
--------
- Minimal starter template you can copy to bootstrap a new AGILab application.
- Demonstrates the project layout expected by the platform (manager package,
  worker package, ``app_args`` definitions, Analysis configuration) with minimal
  business logic so you can focus on custom code.
- Ships with a small custom Streamlit argument form and an empty
  ``pre_prompt.json`` prompt seed so copied projects have explicit places for
  UI customisation and WORKFLOW prompts.

Scientific placeholders
-----------------------
The template is intentionally lightweight, but many AGILab workflows ultimately
fit the pattern of learning or calibrating a function :math:`f_\theta`:

.. math::

   \theta^* = \arg\min_{\theta} \; \frac{1}{N} \sum_{i=1}^{N} \ell\left(f_{\theta}(x_i), y_i\right)

where :math:`\ell` is a task-dependent loss (regression, classification,
imitation learning, etc.). You can use the Minimal App skeleton to prototype the
data loading, feature extraction, and artifact export around this core loop.

Manager (`minimal_app.minimal_app`)
-----------------------------------
- Lightweight ``BaseWorker`` subclass that prepares app-owned shared input and
  output directories through ``env.resolve_share_path``.
- Accepts validated ``MinimalAppArgs`` values, supports ``reset_target`` cleanup
  of the output directory, and keeps ``from_toml`` / ``to_toml`` helpers for the
  same settings round-trip used by richer apps.
- Leaves work distribution as a template hook: ``build_distribution`` currently
  returns empty placeholder structures until a copied project adds real stages.

Args (`minimal_app.app_args`)
-----------------------------
- Simple Pydantic model with defaults for ``data_in``, ``data_out``, ``files``,
  ``nfile``, ``nskip``, ``nread``, and ``reset_target``.
- ``src/app_settings.toml`` intentionally seeds an empty ``[args]`` table; the
  runtime loads model defaults, then persists concrete values only after the
  custom ``src/app_args_form.py`` edits them.
- The model still migrates legacy ``data_uri`` input into ``data_in`` so older
  snippets can be adapted without changing the scaffold shape first.

Worker (`minimal_app_worker.minimal_app_worker`)
------------------------------------------------
- Concrete ``MinimalAppWorker`` subclass of ``agi_node.polars_worker.PolarsWorker``.
- It intentionally adds no domain logic; the class exists so installers and
  worker deployment can discover a real worker package while copied projects
  replace the inherited placeholder behavior with domain-specific processing.

Reducer contract status
-----------------------
``minimal_app_project`` is template-only. It intentionally does not ship a
reducer contract because the manager distribution hook and worker behavior are
scaffold placeholders and no concrete merge output exists yet. This is an
explicit reducer exemption for the starter template, not a gap in a promoted
domain app.

When a cloned project starts producing durable worker summaries, add a
``reduction.py`` module, emit ``reduce_summary_worker_<id>.json`` artifacts, and
export a ``*_REDUCE_CONTRACT`` symbol from the manager package. That keeps custom
apps aligned with the shared ``agi_node`` reducer contract without treating the
starter template as an unfinished built-in app.

Assets & Tests
--------------
- ``README.md`` and ``pyproject.toml`` describe the installable project package
  and its runtime dependencies.
- ``src/app_settings.toml`` carries cluster defaults plus the intentionally
  empty ``[args]`` seed.
- ``src/app_args_form.py`` is the current custom ORCHESTRATE form for path and
  small run-control arguments; tailor it when you need additional validation or
  widgets.
- ``src/pre_prompt.json`` is currently an empty prompt list.
- Repo-level tests exercise the installer, clone path, runtime bootstrap, and
  minimal app environment behavior rather than project-local ``test/_test_*``
  files.

API Reference
-------------

.. figure:: diagrams/packages_minimal_app.svg
   :alt: minimal_app package diagram
   :align: center
   :class: diagram-panel diagram-standard

.. automodule:: minimal_app.minimal_app
   :members:
   :show-inheritance:

.. figure:: diagrams/classes_minimal_app.svg
   :alt: minimal_app class diagram
   :align: center
   :class: diagram-panel diagram-standard

.. automodule:: minimal_app.app_args
   :members:
   :show-inheritance:

.. figure:: diagrams/classes_minimal_app_args.svg
   :alt: minimal_app args class diagram
   :align: center
   :class: diagram-panel diagram-standard

.. figure:: diagrams/packages_minimal_app_worker.svg
   :alt: minimal_app worker package diagram
   :align: center
   :class: diagram-panel diagram-standard

.. automodule:: minimal_app_worker.minimal_app_worker
   :members:
   :show-inheritance:

.. figure:: diagrams/classes_minimal_app_worker.svg
   :alt: minimal_app worker class diagram
   :align: center
   :class: diagram-panel diagram-standard
