Quick-Start
===========

If you are new to AGILab, this page owns one thing only: the exact commands for
the recommended first proof.

That first proof is the built-in ``flight_project`` run locally from the web
UI. If it works once from end to end, then branch into notebooks, package mode,
or cluster mode. If it fails, use :doc:`newcomer-troubleshooting`.

Fast adoption path:

.. list-table::
   :header-rows: 1

   * - Step
     - Action
     - Stop when
   * - 1. Preview
     - Open :doc:`agilab-demo` for the hosted public UI.
     - The Space opens the lightweight ``flight_project`` path.
   * - 2. Prove locally
     - Run the source-checkout commands below and stay on the built-in demo.
     - ``PROJECT`` -> ``ORCHESTRATE`` -> ``PIPELINE`` -> ``ANALYSIS`` works
       locally.
   * - 3. Record evidence
     - Run ``uv --preview-features extra-build-dependencies run agilab first-proof --json``.
     - ``~/log/execute/flight/run_manifest.json`` reports ``status: pass``.
   * - 4. Expand
     - Choose notebook, package, private app, or cluster routes only after the
       local proof passes once.
     - You have one known-good baseline to compare against.

Prerequisites
-------------

- Python 3.11+ with `uv <https://docs.astral.sh/uv/>`_ installed
  (``curl -LsSf https://astral.sh/uv/install.sh | sh``).
- macOS or Linux shell (use WSL2 on Windows until native support lands).
- PyCharm is optional. The first proof below uses only a shell and the web UI;
  IDE run configurations are contributor conveniences, not an installation
  requirement.
- If you plan to explore remote workers later, keep SSH access for that later
  step; it is not needed for the first proof path.

Upgrade or first 10 minutes
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use one lane and stop when the first-proof manifest passes. Do not mix source,
package, private-app, and cluster variables during the first 10 minutes.

**Source checkout, including upgrades after a new release**::

   git pull --ff-only
   ./install.sh --install-apps
   uv --preview-features extra-build-dependencies run agilab first-proof --json

**Published package install or upgrade**::

   uv --preview-features extra-build-dependencies tool upgrade agilab
   agilab first-proof --json

If you installed AGILAB inside an activated project environment instead of as a
``uv`` tool, upgrade that environment explicitly::

   uv pip install --upgrade agilab
   agilab first-proof --json

The adoption checkpoint is always the same: ``run_manifest.json`` reports
``status: pass`` and the default ``flight_project`` analysis view opens. If it
does not pass, stay on this lane and use :doc:`newcomer-troubleshooting`
before changing install route.

Recommended first proof path
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use this path exactly once before trying anything broader. It is the shortest
local path that exercises install, execution, visible analysis, and a
machine-readable proof record.

1. **Clone the repository and install the built-in apps**::

       CHECKOUT="${AGILAB_CHECKOUT:-$HOME/agilab-src}"
       git clone https://github.com/ThalesGroup/agilab.git "$CHECKOUT"
       cd "$CHECKOUT"
       ./install.sh --install-apps

   This is the narrow source-checkout path. It installs the public built-in
   apps and keeps root/app/core test suites opt-in so a first proof does not
   become a full CI run.

   If you also want AGILAB to bootstrap local Ollama-backed models, rerun the
   installer with the model families you want::

      ./install.sh --install-apps --install-local-models gpt-oss,qwen3-coder,ministral,phi4-mini

   Supported values are ``gpt-oss``, ``qwen``, ``deepseek``, ``qwen3``,
   ``qwen3-coder``, ``ministral``, and ``phi4-mini``.

2. **Run the first-proof CLI**::

       uv --preview-features extra-build-dependencies run agilab first-proof --json

   This is the public first-proof entry point. It checks that AGILAB imports,
   boots the About and ORCHESTRATE pages against the built-in ``flight_project``,
   and writes ``~/log/execute/flight/run_manifest.json`` with command,
   environment, timing, artifact references, and validation status.
   The source-checkout developer evidence command is the same contract through
   ``tools/newcomer_first_proof.py --json``.

3. **Launch the web interface**::

       uv --preview-features extra-build-dependencies run streamlit run src/agilab/main_page.py

4. **Keep the first run local and use the built-in flight demo**

   The landing page first-proof wizard points to this same validated path. In
   the UI, use:

   - ``PROJECT`` -> select ``src/agilab/apps/builtin/flight_project``
   - ``ORCHESTRATE`` -> click ``INSTALL``, then ``EXECUTE``
   - ``PIPELINE`` -> inspect the packaged recipe context
   - ``ANALYSIS`` -> open the default built-in view and, when output exists,
     the optional ``view_maps_network`` route

5. **Check the first proof outcome**

   You are past the newcomer hurdle when these are true:

   - ``~/log/execute/flight/run_manifest.json`` has ``status: pass``
   - fresh output exists under ``~/log/execute/flight/``
   - you can open the default ``ANALYSIS`` view for ``flight_project`` and see
     the bundled network view as an available route

6. **Only after that, branch into alternative paths**

   Do not switch to packaged install, notebook-first, or cluster setup before
   this local proof works once from end to end.

Why this path avoids common adoption friction
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

- **No PyCharm dependency**: PyCharm run configurations are generated mirrors
  for IDE debugging. Shell users can run the same flows from the commands on
  this page or from ``tools/run_configs``.
- **No cluster dependency**: SSH keys, shared cluster paths, and remote workers
  are intentionally outside the first proof.
- **No private app dependency**: the first proof uses only public built-in apps
  under ``src/agilab/apps/builtin``.
- **No mandatory test marathon**: installer-managed root, app/page, and core
  tests are available, but only run when you pass explicit test flags.
- **One failure lane**: if it fails, stay on ``flight_project`` and use
  :doc:`newcomer-troubleshooting` before changing install route.

If the first proof fails
^^^^^^^^^^^^^^^^^^^^^^^^

Do not broaden the problem immediately. Stay on the built-in local path.
Use :doc:`newcomer-troubleshooting` first.
The landing page wizard reads ``run_manifest.json``; if it is missing,
invalid, incomplete, or failing, it shows a recovery checklist plus the exact
first-proof and compatibility-report commands to rerun.

If you want the preflight to also check the built-in installer and seeded helper
scripts::

    uv --preview-features extra-build-dependencies run agilab first-proof --with-install

The troubleshooting page covers the common first-run failures:

- missing ``uv``
- installer failure
- built-in app path not found
- About / ORCHESTRATE startup failure
- no fresh output under ``~/log/execute/flight/``

If you want the current public support picture before branching into other
routes, use :doc:`compatibility-matrix`. It makes the current validated slices
explicit and separates them from routes that are documented but not the
recommended newcomer proof.

Alternative install routes
^^^^^^^^^^^^^^^^^^^^^^^^^^

Use these only after the local ``flight_project`` proof works once.

.. _hosted-agilab-demo:
.. _lightning-studio-ui-demo:

**AGILAB demo**:

.. image:: https://img.shields.io/badge/AGILAB-demo-0F766E?style=for-the-badge
   :target: https://huggingface.co/spaces/jpmorard/agilab
   :alt: AGILAB demo

Self-serve public AGILAB demo hosted on Hugging Face Spaces.
The dedicated docs page for this route is :doc:`agilab-demo`.

**Published package route** (fastest install, less representative of the full product path)::

    mkdir ~/agi-workspace && cd ~/agi-workspace
    uv venv
    source .venv/bin/activate
    uv pip install agilab
    agilab first-proof --json
    uv run agilab

Optional feature stacks stay out of the base package install. Add
``agilab[ai]`` for AI assistant features such as OpenAI, Mistral, and
OpenAI-compatible endpoints like vLLM, and ``agilab[viz]`` for optional
Plotly/matplotlib visualizations::

    uv pip install "agilab[ai,viz]"

**agi-core demo**:

- Use :doc:`notebook-quickstart` when you intentionally want the notebook-first
  runtime path before the web UI.

Validation commands
^^^^^^^^^^^^^^^^^^^

The installer keeps test suites opt-in so the default first proof stays fast.
Use these commands when you explicitly want validation during install.

For public built-in apps plus installer-managed root, app/page, and core tests::

    ./install.sh --non-interactive --install-apps builtin --test-root --test-apps --test-core

For an external apps repository available on your machine::

    ./install.sh --non-interactive \
      --apps-repository /path/to/apps-repository \
      --install-apps all \
      --test-root \
      --test-apps \
      --test-core

Clean source-validation runs should keep their disposable checkout and fake
``HOME`` outside the normal home directory. Use a cache-backed workspace so
failed validation can still be inspected without polluting ``$HOME``::

    cache_root="${XDG_CACHE_HOME:-$HOME/.cache}/agilab/source_validate"
    root="$cache_root/agilab_source_validate_clean_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$root/home" "$root/checkouts"
    HOME="$root/home" git clone https://github.com/ThalesGroup/agilab.git "$root/checkouts/source"

This workspace is separate from a normal install. A normal installer run uses
the real ``$HOME`` and creates worker environments under ``~/wenv``; a clean
source-validation run creates its own ``home/wenv`` under the validation root.

Rerunning the installer refreshes repository app/page links. If a selected
repository app or page already exists locally as a real directory, the installer
moves it to ``<name>.previous.<timestamp>`` and links the repository copy so app
updates are picked up.

``--test-root`` runs the installer-managed AGILAB package tests. For the full
repository pytest suite from a source checkout, run it separately::

    uv --preview-features extra-build-dependencies run pytest

Fast UI robot contract tests are normal developer tests::

    uv --preview-features extra-build-dependencies run pytest -q test/test_agilab_widget_robot.py test/test_agilab_web_robot.py

The full browser UI robot sweep is intentionally opt-in because it launches
Streamlit and Playwright. Run it from a source checkout so the ``test/`` tree is
present::

    REPO_ROOT="$(git rev-parse --show-toplevel)"
    cd "$REPO_ROOT"
    AGILAB_RUN_FULL_UI_ROBOT=1 \
    uv --preview-features extra-build-dependencies run --with playwright pytest -q -o addopts='' -m ui_robot "$REPO_ROOT/test/test_agilab_widget_robot_full.py"

To run the same robot against the public Hugging Face Space instead of a local
server::

    REPO_ROOT="$(git rev-parse --show-toplevel)"
    cd "$REPO_ROOT"
    AGILAB_RUN_FULL_UI_ROBOT=1 \
    AGILAB_WIDGET_ROBOT_URL=https://huggingface.co/spaces/jpmorard/agilab \
    AGILAB_WIDGET_ROBOT_APPS=flight_project \
    AGILAB_WIDGET_ROBOT_PAGES=HOME \
    AGILAB_WIDGET_ROBOT_APPS_PAGES=configured \
    uv --preview-features extra-build-dependencies run --with playwright pytest -q -o addopts='' -m ui_robot "$REPO_ROOT/test/test_agilab_widget_robot_full.py"

Private apps or framework contributor setup
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Only do this after the public built-in proof path is working.

Before working on private apps that depend on the public AGILab framework,
initialise the pinned submodule::

    git submodule update --init --recursive

Cluster installs
^^^^^^^^^^^^^^^^

If you want to install on a cluster, the installer must have SSH key access or
credentials with permission to deploy workers. See :doc:`cluster` for the full
workflow. ``pycharm/setup_pycharm.py`` mirrors web interface run configurations
to ``~/log/execute/<app>/AGI_*.py`` for IDE users, while shell users can keep
using generated snippets and ``tools/run_configs`` directly.

Next steps
^^^^^^^^^^

- :doc:`demos` if you want browser-first entry points instead of the local
  first proof.
- :doc:`notebook-quickstart` if you intentionally want the ``agi-core``
  notebook path.
- :doc:`agent-workflows` if you are working inside the AGILAB repository and
  want the prepared Codex, Claude, Aider, or OpenCode developer paths.
- :doc:`cluster` only after the local proof works and you are ready for SSH or
  multi-node execution.

Support
^^^^^^^

Support: open an issue on GitHub

License
^^^^^^^

New BSD. See :doc:`License File <license>`.
