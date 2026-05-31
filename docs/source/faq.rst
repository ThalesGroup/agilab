FAQ
===

This page answers recurring questions about AGILAB adoption, first proof,
notebook interop, runtime behavior, and maintenance. It is not a second quick
start: use :doc:`quick-start` for the executable path and
:doc:`troubleshooting` for a broader failure catalog.

Adoption and scope
------------------

What is AGILAB uniquely useful for?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

AGILAB is useful when a notebook or script has become important enough to need
repeatable install, execution, analysis, and handoff, but not yet important
enough to justify a full production MLOps platform. It turns exploratory work
into an app project with typed parameters, local or distributed execution,
artifacts, optional MLflow tracking, analysis pages, and a notebook exit path.

The key value is not only "run this code". The key value is preserving the work
as it moves between notebook exploration, controlled execution, team review,
and later reuse outside AGILAB if the project no longer needs the workbench.

When should I not use AGILAB?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Do not use AGILAB as-is for these cases:

- a public Streamlit service without external authentication, TLS, and network
  controls
- a sole production MLOps control plane for regulated serving, drift monitoring,
  model governance, or audit ownership
- multi-tenant or sensitive-data work without user isolation, quotas, secrets
  management, and environment-specific security review
- a one-off notebook where repeatability, packaging, and handoff do not matter

For shared or production-like evaluation, treat AGILAB as a controlled R&D
workbench and pair it with hardened platform controls. See
:doc:`security-adoption` and :doc:`agilab-mlops-positioning`.

Does AGILAB replace MLflow?
~~~~~~~~~~~~~~~~~~~~~~~~~~~

No. MLflow records experiments, metrics, artifacts, and model registry handoff.
AGILAB prepares and runs the work that produces those artifacts: project
structure, app parameters, worker environments, local or distributed execution,
workflow stages, and analysis pages. Use AGILAB and MLflow together when you
need both controlled execution and tracking.

Does public release evidence certify my environment?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

No. Release proof is bounded evidence for the documented public routes. It does
not certify every operating system, cloud account, GPU stack, network policy,
cluster topology, private app repository, or long-running production operation.
For a target environment, rerun the first proof, security check, supply-chain
scan, and any cluster/share checks on the exact release you plan to use.

What should I run first?
~~~~~~~~~~~~~~~~~~~~~~~~

Run one local first-proof lane before branching out:

- built-in lane: landing page -> ``1. INSTALL demo`` -> ``2. EXECUTE demo`` ->
  ``3. OPEN ANALYSIS`` for ``flight_telemetry_project``
- notebook lane: landing page -> ``Create from built-in notebook`` to create
  ``flight-telemetry-from-notebook-project``, then prove it with ORCHESTRATE
  ``INSTALL`` and ``EXECUTE``

Do not start with clusters, external apps, service mode, or broad tests. A small
known-good local proof gives you a baseline before you debug a larger topology.

Which packaged examples match the public docs?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The public docs should refer to the current packaged examples catalog, not old
internal aliases. The executable helper examples are:

- ``flight_telemetry`` -> ``flight_telemetry_project`` for the default first
  proof
- ``minimal_app`` -> ``minimal_app_project`` for the smallest worker template
- ``weather_forecast`` -> ``weather_forecast_project`` for the notebook
  migration app
- ``mission_decision`` -> ``mission_decision_project`` for the richer decision
  workflow

Read-only preview examples such as ``notebook_to_dask``,
``inter_project_dag``, ``service_mode``, ``mlflow_auto_tracking``,
``resilience_failure_injection``, and ``train_then_serve`` write deterministic
preview evidence; they do not replace the real ``AGI.install`` / ``AGI.run``
helpers. See the packaged catalog in ``src/agilab/examples/README.md`` when
updating demo or API documentation.

First proof and notebooks
-------------------------

Can I start from a notebook instead of the built-in app?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Yes. The landing page has a ``Create from built-in notebook`` lane. AGILAB
loads the packaged sample notebook directly, so there is no file to locate on
disk and no manual upload step for that sample. The created project is named
``flight-telemetry-from-notebook-project`` and is intended to be installed and
executed like the built-in flight telemetry project.

For your own notebook, use PROJECT -> ``Create`` -> ``From notebook``. Treat
that as a separate first-proof lane: prove either the built-in app or an
imported notebook project first, not both at the same time.

How does notebook import choose manager versus worker code?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

It does not silently make that decision as a hidden final authority. Notebook
metadata and AGILAB tags can prefill the role, but PROJECT still requires a
Manager or Worker choice for every runnable code cell before project creation
can proceed.

Use ``Manager`` for code that should run locally in the project manager runtime,
for example orchestration, lightweight transforms, and review snippets. Use
``Worker`` for code that should become an AGILAB worker-executed stage. If the
role review is incomplete, project creation is blocked with an explicit message.

What is notebook export, and why does it matter?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

WORKFLOW can export the saved pipeline as a runnable supervisor notebook. This
is the no-lock-in path: if you later decide AGILAB is no longer needed, the
stage order, code, runtime metadata, and helper calls remain available in a
normal notebook that can be opened, reviewed, adapted, and executed outside the
AGILAB UI.

The exported notebook is not promised to be a byte-for-byte reconstruction of
the original exploratory notebook. It is a runnable handoff artifact for the
current AGILAB workflow. Use it for review, audit, team handoff, and reuse when
the workbench is no longer the right home for the project.

What is the difference between notebook import and notebook export?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Notebook import turns an existing ``.ipynb`` into AGILAB project stages after
preflight checks and explicit role review. Notebook export takes an AGILAB
WORKFLOW pipeline and writes a runnable ``agi-core`` notebook that preserves
the saved stage contract. Import helps you enter AGILAB; export helps you leave
the UI or hand off the work without losing it, while still running on the
stable core runtime.

Packages, apps, and release evidence
------------------------------------

Which install surface should I choose?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Choose the smallest public surface that matches the task:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Need
     - Install surface
   * - Command shell only
     - ``agilab``
   * - CLI proof and compact runtime
     - ``agilab[core]``
   * - Local Streamlit UI with public app and page catalogs
     - ``agilab[ui]``
   * - Packaged examples and notebooks without the full UI profile
     - ``agilab[examples]``
   * - Page-bundle discovery for notebook/app handoff
     - ``agilab[pages]``
   * - Notebook/API-only use
     - ``agi-core``
   * - Optional MLflow, agents, or local LLM stacks
     - Add the matching optional extra only when that feature is used.

The base package is intentionally small compared with the full UI/demo stack:
it keeps the ``agilab`` command shell available without installing the core
runtime. Use ``agilab[core]`` when you want ``agilab dry-run`` or compact
``agi-core`` notebook/API checks, and use ``agilab[examples]`` for the packaged
first-proof demo assets. Installing core runtime packages does not mean the
first proof uses a remote cluster; cluster execution remains opt-in.

Why are apps and pages separate packages?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

AGILAB separates three concerns:

- the root ``agilab`` package exposes the top-level CLI and curated extras
- ``agi-apps`` and ``agi-pages`` expose catalog/provider surfaces
- ``agi-web`` exposes portable rich web component payload contracts
- ``agi-app-*`` and ``agi-page-*`` payload packages carry individual apps or
  reusable analysis page bundles

This keeps the top-level package from embedding every demo, page, notebook, and
UI asset directly. It also lets a promoted app or page be published, inspected,
installed, updated, or removed without requiring a full AGILAB runtime release
when the runtime did not change.

Page bundles must stay app-agnostic. A page package should describe the
generic analysis capability it provides, not the first project that used it.
That is why page names such as ``agi-page-training-report`` or
``agi-page-feature-attribution`` are preferred over project-specific names.

Do app and page versions always match the AGILAB version?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

No. Runtime components, bundle packages, and payload packages have different
versioning responsibilities:

- runtime components such as ``agi-env``, ``agi-node``, ``agi-cluster``,
  ``agi-gui``, and ``agi-web`` version the implementation they carry
- bundle packages such as ``agilab``, ``agi-core``, ``agi-apps``, and
  ``agi-pages`` version the curated dependency graph they expose
- app and page payload packages version the payload they carry
- built-in source app manifests in ``src/agilab/apps/builtin`` can carry
  independent versions to reflect local seed updates

Bundle packages exact-pin the curated component graph for reproducible
installs. Payload packages should normally declare compatible AGILAB runtime
ranges so an unchanged app or page does not need to be republished for every
runtime patch. Release proof ties the selected public packages back to one
documented release decision.

What does a proof pack mean today?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The shipped proof-pack layer is JSON-first. It starts from
``run_manifest.json`` and related evidence files, then uses commands such as
``agilab prove``, ``verify``, ``replay``, ``export-lineage``,
``policy-check``, ``cards``, and ``metadata-store`` to make the run evidence
inspectable and replayable.

Hash-verifiable ``.agipack`` archives and optional detached Ed25519 signatures
are part of the shipped proof-capsule layer. Stronger third-party attestations,
such as external Sigstore/SLSA binding, remain roadmap work unless a release
proof explicitly links the shipped implementation. Treat current proof-pack
evidence as structured local/release evidence, not as independent external
certification.

Why does PyPI sometimes show several AGILAB packages for one release?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

AGILAB publishes a package family because app workers, notebooks, the web UI,
page bundles, and release validation need to resolve the same public dependency
graph outside a source checkout. The user-facing entry points remain
``agilab`` and ``agi-core``; the other public packages make that graph
reproducible for workers, UI pages, app payloads, and release evidence.

Runtime and cluster behavior
----------------------------

Do I need PyCharm?
~~~~~~~~~~~~~~~~~~

No. PyCharm run configurations are contributor conveniences for debugging. The
product path is the web UI and CLI commands. Shell-only users can use the
checked-in wrappers under ``tools/run_configs``.

Typical usage::

   bash tools/run_configs/agilab/agilab-run-dev.sh
   bash tools/run_configs/apps/builtin-minimal_app-run.sh

Do I need a cluster or shared folder for the first proof?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

No. The first proof is local by design. Cluster mode is a later validation
step.

AGILAB's core adoption value is still available without cluster mode: local
reproducible execution, app/page handoff, proof artifacts, and notebook or
MLflow export.

If cluster mode is requested, AGILAB requires an explicit usable cluster share
that is distinct from the local share. It should fail fast instead of silently
falling back to ``localshare``. Validate a cluster share before a full run with
the doctor share check documented in :doc:`distributed-workers`.

What limits AGILAB when scaling compute?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The limit is not that AGILAB cannot run distributed work. It can run local,
pool, Dask, and SSH-backed worker flows. The current scale boundary is the
production-grade orchestration layer around those workers.

Today, AGILAB is a controlled distributed workbench: it packages worker
environments, starts or connects workers, validates shared storage, and records
evidence. It is not yet a full compute platform with automatic worker
provisioning, elastic scale-up and scale-down, per-project quotas, GPU/CPU/memory
scheduling, queue priorities, retry and resume policies, node-failure recovery,
data-locality planning, and centralized logs or metrics.

Use AGILAB cluster mode when you need repeatable distributed experiments and
reviewable evidence. Pair it with Kubernetes, HPC, cloud batch, or an internal
platform when you need production-grade fleet orchestration across many users,
many jobs, or changing resource pools.

Can I run Dask again inside one AGILAB worker and see it in the outer dashboard?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Not as a supported first-class pattern. AGILAB uses Dask as the outer scheduler
boundary. The outer scheduler sees one coarse AGILAB task per worker; code
inside the worker's ``works(...)`` method is opaque to the outer dashboard.

Nested Dask may run technically, but AGILAB health, capacity, and service
telemetry remain at the outer worker level. If you need AGILAB and the outer
Dask dashboard to see the parallel work, express that work as AGILAB work-plan
tasks instead of starting a second scheduler inside one worker.

Who manages parallelism when Dask is disabled?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``agi_dispatcher`` owns the local process and thread pools. Dask coordinates
execution only when you explicitly opt into distributed mode; otherwise, the
dispatcher handles orchestration end to end.

Do we already have DAG/task orchestration?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Yes. Managers hand ``WorkDispatcher`` a work plan and ``DagWorker`` executes it,
enforcing dependencies and parallelism across workers. Current improvement areas
are richer telemetry and policies such as retries, priorities, and operator
readiness messages, not inventing a separate planner from scratch.

Why does a run create ``distribution.json``?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``WorkDispatcher`` caches the last work plan in ``distribution.json`` inside
each app directory. On later runs it reuses the plan if the worker layout and
arguments are unchanged. Delete the file, or change the run arguments, to force
a fresh repartition.

Install, dependencies, and logs
-------------------------------

Missing worker packages during a run
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If a worker virtual environment fails with ``ModuleNotFoundError``, rerun the
matching ORCHESTRATE ``INSTALL`` path for the selected project. For source
debugging, check both dependency scopes:

- manager dependencies in the app project ``pyproject.toml``
- worker dependencies in the worker package ``pyproject.toml``

For example, the built-in flight telemetry worker manifest lives under
``src/agilab/apps/builtin/flight_telemetry_project/src/flight_telemetry_worker/pyproject.toml``.

Why do installers still build eggs?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Some distributed worker upload paths still consume ``bdist_egg`` artifacts.
That is an internal deployment artifact for worker dispatch, not the public
packaging format. Shared build tooling now routes through
``python -m agi_node.agi_dispatcher.build --app-path ...``; per-app
``build.py`` helpers are deprecated and should not be reintroduced.

Do I need to run tests during install?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

No. The default installer path is intentionally fast and keeps tests opt-in.
Use ``--test-root``, ``--test-apps``, or ``--test-core`` only when you want the
installer to perform validation during setup. For a first proof, run the narrow
``flight_telemetry_project`` path first and add tests after it works once.

Where are installer logs written?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Every installer run streams output to the UI and appends a timestamped log under
``$AGI_LOG_DIR/install_logs``. By default ``$AGI_LOG_DIR`` is ``~/log`` (see
``$HOME/.agilab/.env``), so the usual location is ``~/log/install_logs``.

What does the ``VIRTUAL_ENV`` warning mean?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``uv`` emits this warning when you launch a command from an activated shell
whose ``$VIRTUAL_ENV`` differs from the target project's ``.venv`` directory.
The command still uses the project lock. AGILAB-managed PyCharm configs and
launch wrappers clear ``VIRTUAL_ENV`` before invoking ``uv``. If you still see
the warning, run the matching ``tools/run_configs`` wrapper or unset
``VIRTUAL_ENV`` first. Avoid ``--active`` for normal AGILAB launches because it
intentionally reuses the currently activated environment.

Why did my local coverage run not change the README badge?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

AGILAB coverage badges are generated artifacts, not live views of the last
local ``pytest --cov`` run. A local coverage command updates XML files such as
``coverage-agi-gui.xml`` or ``coverage-agilab.xml``, but the README still shows
the last committed SVG badge until you regenerate and commit it.

Typical refresh path::

   uv --preview-features extra-build-dependencies run python tools/generate_component_coverage_badges.py --components agi-gui

For the global badge, you also need the corresponding aggregate XML inputs
before regenerating ``badges/coverage-agilab.svg``.

Why can ``agi-gui`` be at 99% while global ``agilab`` coverage is lower?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The component badges and the global badge measure different scopes.
``agi-gui`` only measures the GUI/profile slice covered by the GUI workflow.
The global ``agilab`` badge aggregates all tracked components together,
including shared core modules such as ``agi-env``, ``agi-node``, and
``agi-cluster``. A component can therefore reach 99% or 100% while the global
aggregate stays lower.

Contributor and documentation maintenance
-----------------------------------------

Which local tool should I run when?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use the smallest tool that proves the change you made. The usual choices are:

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Need
     - Tool
   * - Understand what a diff requires
     - ``./dev impact`` or
       ``uv --preview-features extra-build-dependencies run python tools/impact_validate.py --staged``
   * - Normal bug-fix validation before push
     - ``./dev bugfix``
   * - Targeted tests
     - ``./dev test -- <pytest args>`` or direct ``pytest -q <target>``
   * - Likely regression subset
     - ``./dev regress``
   * - Match a GitHub workflow locally
     - ``./dev flow -- <profile>`` or
       ``uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile <profile>``
   * - Docs mirror and stamp alignment
     - ``./dev docs`` or
       ``uv --preview-features extra-build-dependencies run python tools/sync_docs_source.py --apply --delete``
   * - Coverage badge refresh
     - ``./dev badge`` or the relevant coverage-badge generator
   * - Pre-release local guardrails
     - ``./dev release``
   * - IDE wrapper regeneration
     - ``uv --preview-features extra-build-dependencies run python tools/generate_runconfig_scripts.py``
   * - Newcomer UI startup smoke
     - ``uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py``

Do not start with the broadest check by default. Run ``impact`` first when the
blast radius is unclear, then run the narrow command it recommends. Use the
docs profile or release profile when a public docs page, badge, release proof,
or publication contract is part of the change.

Which docs repo should I edit?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Edit the canonical documentation source in the sibling documentation checkout:
``../thales_agilab/docs/source`` relative to the AGILAB source checkout. The
public Pages workflow publishes from the mirrored ``agilab/docs/source`` tree,
so public docs changes need two steps:

1. edit the canonical source in the sibling documentation checkout
2. sync the public mirror with ``tools/sync_docs_source.py``

Do not edit ``docs/html``. It is generated output only.

Docs drift after touching core APIs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you change ``BaseWorker`` or other primitives surfaced in the guides,
rebuild or validate the docs so the published pages match the updated source.
Update tracked diagrams, inventories, and directory trees from a clean checkout
when repository layout or surfaced APIs change.

Switching PyCharm to another source checkout
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

PyCharm uses a global JetBrains SDK named ``uv (agilab)`` for AGILAB source
runs. That SDK can point to only one source checkout at a time. If you installed
or configured AGILAB from one checkout and then open another checkout, do not
let PyCharm mix ``src/agilab`` from one tree with ``.venv`` from the other.

To intentionally move PyCharm execution to another checkout, run the command for
your shell from the target checkout.

macOS/Linux:

.. code-block:: bash

   uv sync
   AGILAB_PYCHARM_ALLOW_SDK_REBIND=1 uv --preview-features extra-build-dependencies run python pycharm/setup_pycharm.py

Windows PowerShell:

.. code-block:: powershell

   uv sync
   $env:AGILAB_PYCHARM_ALLOW_SDK_REBIND = "1"
   uv --preview-features extra-build-dependencies run python pycharm/setup_pycharm.py

The override is intentionally explicit. Without it, ``setup_pycharm.py``
refuses to rebind ``uv (agilab)`` when it detects that the SDK already points to
another AGILAB source root. Rerun full ``install.sh`` only when you also need
installer side effects such as app installation, ``.agilab-path`` updates,
dataset seeding, or install-time tests.

Regenerating IDE run configurations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``.idea/runConfigurations`` is the source for checked-in CLI wrappers. After
editing a JetBrains run configuration, regenerate the wrappers with:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/generate_runconfig_scripts.py

Commit the updated files under ``tools/run_configs`` with the run-configuration
change.

What does ``tools/newcomer_first_proof.py`` actually prove?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

It proves the recommended newcomer startup path is healthy. Specifically, it
checks that the lightweight ``agi_env`` preinit smoke works, the main page
boots, and the ``ORCHESTRATE`` page boots against the built-in
``flight_telemetry_project``.

It does not replace the full visible workflow proof. Passing
``tools/newcomer_first_proof.py`` means the source checkout and UI startup path
are sane; you still need the normal first run in the web interface to produce
fresh output under ``~/log/execute/flight_telemetry/`` and complete the
PROJECT -> ORCHESTRATE -> ANALYSIS story.
