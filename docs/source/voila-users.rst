AGILAB for Voila users
======================

Voila users do not need a platform migration pitch first. The useful first
question is smaller:

   Can I keep a notebook dashboard as the familiar interface, then add app
   boundaries, replay, and evidence when the workflow becomes important?

AGILAB's current answer is a lightweight bridge: a Voila-shaped notebook,
widget-to-argument mapping, a hide-code manifest, an app-view plan, and explicit
evidence. This is not a full Voila server integration and it is not yet an
``agilab[voila]`` runtime extra.

What ships now
--------------

The packaged ``voila_notebook_proof`` preview creates a notebook-dashboard proof
without adding Voila or ipywidgets as required dependencies:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python src/agilab/examples/voila_notebook_proof/preview_voila_notebook_proof.py

It writes:

.. code-block:: text

   ~/log/execute/voila_notebook_proof/dashboard.ipynb
   ~/log/execute/voila_notebook_proof/widget_to_args.json
   ~/log/execute/voila_notebook_proof/hidden_code_manifest.json
   ~/log/execute/voila_notebook_proof/agilab_app_view_plan.json
   ~/log/execute/voila_notebook_proof/dashboard_app_preview.html
   ~/log/execute/voila_notebook_proof/voila_notebook_evidence.json

Open ``dashboard_app_preview.html`` to inspect the static adoption plan. Open
``dashboard.ipynb`` to see the notebook shape that a future Voila runtime could
serve.

Why this is the right first bridge
----------------------------------

Voila already gives notebook users a direct path from notebooks to dashboards.
AGILAB should not replace that habit. It should add the missing engineering
boundary only when the notebook becomes a reusable application.

The bridge keeps the responsibilities clear:

.. list-table::
   :header-rows: 1

   * - User concern
     - AGILAB response
   * - I already have a notebook dashboard.
     - Keep the notebook as an app-owned asset.
   * - I want user controls.
     - Map stable widgets to explicit app arguments.
   * - I want cleaner presentation.
     - Record a hide-code manifest as data.
   * - I need reproducibility.
     - Hash the notebook, sidecars, and evidence bundle.
   * - I do not want a new deployment story yet.
     - Use files first; keep Voila serving as an optional later runtime.

Product direction
-----------------

The next product step is a focused command and UI path:

.. code-block:: bash

   agilab notebook-proof dashboard.ipynb --app-name sales_dashboard

That should:

- read a user-selected notebook;
- extract stable widget defaults into app arguments;
- preserve app-specific notebook and UI code inside the app folder;
- write an app-view plan and evidence bundle;
- optionally serve through Voila only when the user installs the Voila extra.

The positioning is intentionally narrow:

   Voila turns notebooks into apps. AGILAB turns notebook apps into
   reproducible, evidence-backed workflows.

What remains roadmap
--------------------

The preview does not yet claim:

- a running Voila server from the AGILAB web UI;
- an ``agilab[voila]`` extra;
- automatic arbitrary notebook import into a full app project;
- ipywidgets execution during preview generation;
- multi-user dashboard deployment.

Those are useful later only if notebook-dashboard users care about the bridge.
For now, the adoption message should stay simple:

   Keep the notebook dashboard. Use AGILAB to make the workflow replayable,
   auditable, and easier to promote into an app.
