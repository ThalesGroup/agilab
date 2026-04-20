FAQ
===

This page captures recurring questions about the AGILab tooling and runtime.

Missing worker packages during `AGI.run_*`
------------------------------------------
If a run fails with `ModuleNotFoundError` inside a worker virtual environment, rerun the
matching installer script (for example ``uv run --project src/agilab/core/agi-cluster python
src/agilab/examples/flight/AGI.install_flight.py``). The installer rebuilds the worker egg and
provisions its environment so the next ``AGI.run_*`` picks up the dependencies.

Why installers still build eggs
-------------------------------
The distributed upload path expects ``bdist_egg`` artifacts. Each app ships a ``build.py`` helper
that produces eggs and symlinks the required modules before they are sent to Dask. Moving to pure
wheels would break that upload contract, so eggs remain the canonical package format.

Do we already have DAG/task orchestration?
------------------------------------------
Yes. Managers hand ``WorkDispatcher`` a work plan and ``DagWorker`` executes it, enforcing
dependencies and parallelism across workers. The improvement areas are telemetry and richer
policies (retries, priorities), not building a brand-new planner.

Who manages multithreading when Dask is disabled?
-------------------------------------------------
``agi_dispatcher`` owns the local process and thread pools. Dask only coordinates execution when
you explicitly opt into distributed mode; otherwise, the dispatcher handles the orchestration end
to end.

Regenerating IDE run configurations
-----------------------------------
``pycharm/gen_app_script.py`` is the authoritative generator for JetBrains run configurations.
Wrap it (and ``setup_pycharm.py``) in a single helper command—e.g. ``just run-configs`` or ``make
run-configs``—so developers and CI regenerate configs consistently from the same entry point.

Using run configurations without PyCharm
----------------------------------------
For shell-only workflows, use the checked-in wrappers under
``tools/run_configs``. These wrappers mirror the bundled run configurations and
can be launched directly from a terminal without opening PyCharm.

Typical usage::

    bash tools/run_configs/agilab/agilab-run-dev.sh
    bash tools/run_configs/apps/builtin-mycode-run.sh

"VIRTUAL_ENV ... does not match the project environment" warning
----------------------------------------------------------------
``uv`` emits this when you launch a command from an activated shell whose
``$VIRTUAL_ENV`` differs from the target project’s ``.venv`` directory. The message is
informational—the command will still run using the project lock. AGILAB manages multiple
virtualenvs per app and per install (shared/local), so seeing this warning is normal when
you hop between them. If you truly want to reuse the activated environment, pass
``--active`` to ``uv``; otherwise you can safely ignore the warning.

Why does a run create ``distribution.json``?
--------------------------------------------
``WorkDispatcher`` caches the last work-plan in ``distribution.json`` inside each app
directory. On subsequent runs it reuses the plan if the workers layout and arguments
are unchanged; delete the file (or change args) to force a full repartition.

Switching the active app in the web interface
---------------------------------------------
Use the project selector in the left sidebar of the web interface. ``AgiEnv`` will
recreate symbolic links under ``~/wenv`` and adjust the virtual environment for the
chosen app. When you add a brand-new app under ``src/agilab/apps/``, restart the
web interface session so the selector picks it up.

Docs drift after touching core APIs
-----------------------------------
If you change ``BaseWorker`` or other primitives surfaced in the guides, rebuild the
reference documentation with ``uv run sphinx-build -n -q -b html docs/source docs/_build/html`` so
the published docs match the updated source. Update tracked diagrams, inventories, and directory trees
in ``docs/source/`` from a clean checkout when the repository layout or surfaced APIs change.

`AGI.install_*` fails looking for ``pyproject.toml``
----------------------------------------------------
Each worker must carry its own ``pyproject.toml`` (for example
``src/agilab/apps/builtin/flight_project/src/flight_worker/pyproject.toml``). If the installer raises
``FileNotFoundError`` for that path, add the file with the worker’s runtime
dependencies—typically mirroring the manager’s requirements plus the appropriate
``dag-worker``/``polars-worker`` extra.

Where are installer logs written?
---------------------------------
Every installer run streams output to the UI and also appends a timestamped log under
``$AGI_LOG_DIR/install_logs``. By default ``$AGI_LOG_DIR`` is ``~/log`` (see
``$HOME/.agilab/.env``), so you will find files like
``~/log/install_logs/install_20250921_072751.log_`` with the full transcript.

Why did my local coverage run not change the README badge?
----------------------------------------------------------
AGILAB coverage badges are generated artifacts, not live views of the last
local ``pytest --cov`` run. A local coverage command updates XML files such as
``coverage-agi-gui.xml`` or ``coverage-agilab.xml``, but the README still shows
the last committed SVG badge until you regenerate and commit it.

Typical refresh path::

    uv --preview-features extra-build-dependencies run python tools/generate_component_coverage_badges.py --components agi-gui

For the global badge, you also need the corresponding aggregate XML inputs
before regenerating ``badges/coverage-agilab.svg``.

Why can ``agi-gui`` be at 99% while global ``agilab`` coverage is lower?
-------------------------------------------------------------------------
The component badges and the global badge measure different scopes.

- ``agi-gui`` only measures the GUI/profile slice covered by the GUI workflow.
- ``agilab`` aggregates all tracked components together, including shared core
  modules such as ``agi-env``, ``agi-node``, and ``agi-cluster``.

So a component badge can legitimately reach ``99%`` or ``100%`` while the
global aggregate stays lower until the other components also move up.

Which docs repo should I edit?
------------------------------
The canonical editable documentation source is the sibling documentation
checkout under ``docs/source``. The public AGILAB Pages build still publishes
from the mirrored ``agilab/docs/source`` tree, so public docs changes need both
steps:

1. edit the canonical source in the sibling documentation checkout
2. mirror the touched files into ``agilab/docs/source``

Do not treat ``docs/html`` as editable source. It is generated output only.

What does ``tools/newcomer_first_proof.py`` actually prove?
-----------------------------------------------------------
It proves the recommended newcomer startup path is healthy. Specifically, it
checks that:

- the lightweight ``agi_env`` preinit smoke works
- the ``About`` page boots
- the ``ORCHESTRATE`` page boots against the built-in ``flight_project``

It does **not** replace the full first visible workflow proof. Passing
``tools/newcomer_first_proof.py`` means the source checkout and UI startup path
are sane; you still need the normal first run in the web interface to produce
fresh output under ``~/log/execute/flight/`` and complete the
``PROJECT -> ORCHESTRATE -> ANALYSIS`` story.
