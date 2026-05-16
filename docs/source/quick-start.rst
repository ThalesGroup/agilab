Quick-Start
===========

If you are new to AGILab, this page owns one thing only: the exact commands for
the recommended first proof.

That first proof is the built-in ``flight_telemetry_project`` run locally from the web
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
     - The Space opens the lightweight ``flight_telemetry_project`` path.
   * - 2. Prove locally
     - Run the source-checkout commands below and stay on the built-in demo.
     - ``PROJECT`` -> ``ORCHESTRATE`` -> ``WORKFLOW`` -> ``ANALYSIS`` works
       locally.
   * - 3. Record evidence
     - Start the app with ``agilab`` and verify the built-in flow.
       If startup fails, run ``agilab dry-run`` then
       ``uv --preview-features extra-build-dependencies run agilab first-proof --json --with-ui``.
     - ``~/log/execute/flight_telemetry/run_manifest.json`` reports ``status: pass``.
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
   uv --preview-features extra-build-dependencies run agilab

If startup fails, run a local fallback first:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run agilab dry-run
   uv --preview-features extra-build-dependencies run agilab first-proof --json --with-ui

**Published package install or upgrade, CLI proof only**::

   uv --preview-features extra-build-dependencies tool install --upgrade "agilab[examples]"
   agilab first-proof --json

The ``examples`` extra installs the ``agi-apps`` umbrella, which depends on the
per-app package that contains the public built-in ``flight_telemetry_project`` used by
the proof.

Use the UI profile when you want the local Streamlit pages from the
published package::

   uv --preview-features extra-build-dependencies tool install --upgrade "agilab[ui]"
   agilab

The ``ui`` extra installs ``agi-apps`` and its per-app project packages for
public built-in projects, plus ``agi-pages`` for packaged ANALYSIS page
bundles. A base ``agilab`` install stays CLI/core-only; run ``agilab dry-run``
there when you only need the lightweight import/runtime smoke.

If you installed AGILAB inside an activated project environment instead of as a
``uv`` tool, upgrade that environment explicitly::

   uv pip install --upgrade "agilab[examples]"
   agilab first-proof --json

The adoption checkpoint is always the same: ``run_manifest.json`` reports
``status: pass`` and the default ``flight_telemetry_project`` analysis view opens. If it
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

   For hardened workstations where downloaded shell installers must not run,
   add ``--no-remote-installers``. The installer will refuse remote bootstrap
   scripts such as Ollama or Homebrew installers and leave those prerequisites
   for your managed package baseline.

   Supported values are ``gpt-oss``, ``qwen``, ``deepseek``, ``qwen3``,
   ``qwen3-coder``, ``ministral``, and ``phi4-mini``. The first family in the
   list becomes the default WORKFLOW local assistant. For example, ``gpt-oss``
   selects the Ollama-backed ``gpt-oss:20b`` model and writes the matching
   ``LAB_LLM_PROVIDER``, ``UOAIC_MODEL``, and ``AGILAB_LLM_*`` values into the
   AGILAB environment file.

2. **Launch the app**::

       uv --preview-features extra-build-dependencies run agilab

   This starts the app from the source checkout.
   The source-checkout developer evidence command is the same contract through
   ``tools/newcomer_first_proof.py --json``.

3. **Run the first-proof manifest check**:

   If the app fails to start, use:

   .. code-block:: bash

      uv --preview-features extra-build-dependencies run agilab dry-run
      uv --preview-features extra-build-dependencies run agilab first-proof --json --with-ui

   Then rerun:

   .. code-block:: bash

      uv --preview-features extra-build-dependencies run agilab

   The app and all core pages can also be started directly with:

   .. code-block:: bash

      uv --preview-features extra-build-dependencies run streamlit run src/agilab/main_page.py

   Local UI is intended to stay on loopback. If you intentionally expose it through
   a reverse proxy, set ``AGILAB_PUBLIC_BIND_OK=1`` plus a real protection
   indicator such as ``AGILAB_TLS_TERMINATED=1`` before using
   ``--server.address 0.0.0.0``.

4. **Use the landing-page first-proof wizard**

   The ABOUT landing page exposes the current first-proof path directly:

   - click ``1. INSTALL demo`` to select ``flight_telemetry_project`` and run
     the ORCHESTRATE install
   - click ``2. EXECUTE demo`` to start the local ORCHESTRATE execution with
     cluster, benchmark, and service mode off
   - click ``3. OPEN ANALYSIS`` after evidence exists to open the built-in
     analysis route

   If you want to start from a notebook, use the same wizard's
   ``Create from built-in notebook`` button for AGILAB's packaged sample; there
   is no notebook file to locate or upload. The wizard opens ``PROJECT`` ->
   ``Create`` -> ``From notebook`` with the bundled sample already selected;
   then you click PROJECT ``Create`` and prove the imported project with
   ORCHESTRATE ``INSTALL`` and ``EXECUTE``. For your own local notebook, use
   PROJECT -> ``Create`` -> ``From notebook`` instead of the first-proof wizard.
   Treat that as a separate starting lane: prove either the built-in flight
   project or a notebook-imported project first, not both at the same time.

5. **Check the first proof outcome**

   You are past the newcomer hurdle when these are true:

   - ``~/log/execute/flight_telemetry/run_manifest.json`` has ``status: pass``
   - fresh output exists under ``~/log/execute/flight_telemetry/``
   - you can open the default ``ANALYSIS`` view for ``flight_telemetry_project`` and see
     the bundled network view as an available route

6. **Only after one lane passes, branch into broader paths**

   Do not switch to packaged install, external apps, or cluster setup before
   either the built-in flight proof or your notebook-import proof works once
   from end to end.

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
- **One failure lane**: if it fails, stay on ``flight_telemetry_project`` and use
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

    uv --preview-features extra-build-dependencies run agilab first-proof --json --with-ui --with-install

``agilab dry-run`` is the fast alias for ``agilab first-proof --dry-run`` and
checks only CLI/core readiness.

Use ``--dry-run`` when startup or import errors appear before you need a full UI
proof contract.

The troubleshooting page covers the common first-run failures:

- missing ``uv``
- installer failure
- built-in app path not found
- Main page / ORCHESTRATE startup failure
- no fresh output under ``~/log/execute/flight_telemetry/``

If you want the current public support picture before branching into other
routes, use :doc:`compatibility-matrix`. It makes the current validated slices
explicit and separates them from routes that are documented but not the
recommended newcomer proof.

Alternative install routes
^^^^^^^^^^^^^^^^^^^^^^^^^^

Use these only after the local ``flight_telemetry_project`` proof works once.

.. _hosted-agilab-demo:
.. _lightning-studio-ui-demo:

**AGILAB demo**:

.. image:: https://img.shields.io/badge/AGILAB-demo-0F766E?style=for-the-badge
   :target: https://huggingface.co/spaces/jpmorard/agilab
   :alt: AGILAB demo

Self-serve public AGILAB demo hosted on Hugging Face Spaces.
The dedicated docs page for this route is :doc:`agilab-demo`.

**Published package route** (fastest install, less representative of the full product path)::

    uv --preview-features extra-build-dependencies tool install --upgrade agilab
    agilab first-proof --json --max-seconds 60

The base package install is intentionally CLI/core only. Install the UI profile
before launching the local Streamlit app::

    uv --preview-features extra-build-dependencies tool install --upgrade "agilab[ui]"
    agilab

If startup fails, or if you also want a one-command onboarding manifest in this
profile, run:

.. code-block:: bash

   agilab dry-run
   agilab first-proof --json --with-ui

Optional feature stacks stay out of the base package install. Add
``agilab[ui]`` for the local Streamlit app, ``agilab[pages]`` for analysis
page bundles without the full UI profile, ``agilab[ai]`` for AI assistant
features such as OpenAI, Mistral, and OpenAI-compatible endpoints like vLLM,
``agilab[agents]`` for the packaged agent workflow client dependencies,
``agilab[examples]`` for notebook/demo helper dependencies, ``agilab[mlflow]``
for tracking, ``agilab[local-llm]`` for local model helpers,
``agilab[viz]`` for optional Plotly/matplotlib visualizations, and
``agilab[dev]`` for contributor-only test/build tooling::

    uv --preview-features extra-build-dependencies tool install --upgrade "agilab[ui,agents,examples,viz,mlflow,local-llm]"

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

Shared or team adoption check
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Before moving from a single-user proof to a shared team workstation, internal
cluster, public UI, or external apps repository, archive a profile-specific
security-check report::

    uv --preview-features extra-build-dependencies run agilab security-check --profile shared --json > security-check.json

The default ``local`` profile stays advisory so first proof and local
experimentation stay fast. The ``shared``, ``cluster``, and ``public-ui``
profiles promote deployment-boundary issues to failures so ``--strict`` can be
used as a real gate. The report checks floating or unallowlisted
``APPS_REPOSITORY`` checkouts, likely plaintext secrets in
``~/.agilab/.env``, public UI bind addresses, cluster-share isolation,
generated-code execution boundaries, optional local-model profiles, and missing
SBOM / ``pip-audit`` evidence.

For the private vulnerability-reporting channel, go/no-go adoption boundary,
and shared-use hardening checklist, see :doc:`security-adoption`. Public GitHub
issues are not a vulnerability intake channel.

To generate per-profile scan evidence instead of a single generic artifact::

    uv --preview-features extra-build-dependencies run python tools/profile_supply_chain_scan.py --profile all --run

This writes ``requirements.txt``, ``pip-audit.json``, and
``sbom-cyclonedx.json`` under ``test-results/supply-chain/<profile>/`` for the
base, UI, pages, AI, agents, examples, MLflow, local-LLM, offline, and dev
install profiles.

Maintainers can produce the same artifact from the repo workflow-parity helper::

    uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile security-adoption

Use strict mode only for an explicit release or team gate where warnings should
fail the job::

    AGILAB_SECURITY_CHECK_STRICT=1 \
    uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile security-adoption

External app repositories must be pinned and allowlisted before shared use.
Set ``AGILAB_APPS_REPOSITORY_ALLOWLIST`` to the exact reviewed origin URL, or
set ``AGILAB_APPS_REPOSITORY_ALLOWLIST_FILE`` to a newline-separated allowlist.

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
    AGILAB_WIDGET_ROBOT_APPS=flight_telemetry_project \
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
