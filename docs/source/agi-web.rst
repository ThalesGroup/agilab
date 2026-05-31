agi-web API
===========

``agi-web`` is the portable AGILAB web component contract. It is not a second
application framework and it does not make AGILAB depend on a JavaScript build
pipeline. It gives apps a stable, JSON-normalized payload and evidence hash so
the same UI island can render in Streamlit/static HTML today and later move to
other adapters without changing the app-side contract.

Use ``agi-web`` when a view needs browser-level fluidity, for example a
training playground, a simulation cockpit, or an interactive digital twin view.
Keep normal forms, tables, and operator controls in ``agi-gui`` / Streamlit.
The default static renderer can use WebGL for the decision-surface heatmap and
Canvas2D for the overlay/fallback. It supports local frame replay, scrubbing,
clickable timelines, keyboard controls, confidence badges, uncertainty-contour
glow, and hover readouts for payloads that expose ``samples``, ``grid``,
``snapshots``, and ``history`` records.

Contract
--------

The public Python surface is intentionally small:

- ``AgiWebComponent``: component id, title, renderer spec, payload, actions,
  fallback HTML, and deterministic evidence.
- ``AgiWebRendererSpec``: renderer id, technology label, entrypoint, assets, and
  declared capabilities.
- ``AgiWebAction`` and ``AgiWebAsset``: optional action/asset metadata for
  adapters that support richer browser interaction.
- ``component_to_static_html`` and ``render_streamlit``: build-free renderers
  for current AGILAB pages.
- ``records_from_data`` and ``normalize_json_value``: deterministic conversion
  helpers for dataframe-like payloads.

Example
-------

.. code-block:: python

   from agi_web import AgiWebComponent, AgiWebRendererSpec, render_streamlit

   component = AgiWebComponent(
       component_id="decision-boundary",
       title="Decision boundary",
       renderer=AgiWebRendererSpec(
           renderer_id="pytorch-boundary-webgl",
           technology="webgl",
           capabilities=("decision-boundary", "learning-replay", "gpu-heatmap"),
       ),
       payload={
           "samples": [{"x1": -0.4, "x2": 0.2, "target": 1}],
           "grid": [{"x1": -0.5, "x2": 0.0, "probability": 0.72}],
           "snapshots": [
               {"epoch": 0, "x1": -0.5, "x2": 0.0, "probability": 0.51},
               {"epoch": 8, "x1": -0.5, "x2": 0.0, "probability": 0.72},
           ],
       },
   )

   render_streamlit(component)

Current boundary
----------------

The shipped renderer is a build-free static/Streamlit adapter with a WebGL
heatmap path and Canvas2D overlay/fallback: timeline chips, play/pause,
arrow-key scrubbing, confidence HUD, uncertainty contour, and pointer
inspection. React is supported as a contract technology but is not a bundled
runtime adapter yet. That distinction is deliberate: AGILAB apps should first
own a stable payload/evidence contract, then add heavier frontend adapters only
where the UX requires them.

Visual guard
------------

``tools/agi_web_visual_regression.py`` renders a deterministic WebGL fixture in
Chromium, asserts that the WebGL renderer activates when available, captures a
screenshot, and writes a screenshot manifest. The matching workflow parity
profile is ``agi-web-visual``. That profile compares the Chromium screenshot
against ``docs/source/_static/agi-web-visual-baseline`` and enforces a render
budget so a polished canvas does not regress into a slow one.

Use explicit browsers when validating adapter portability:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run --with playwright --with pillow \
     python tools/agi_web_visual_regression.py \
       --browser chromium --browser firefox --browser webkit \
       --allow-canvas-fallback \
       --max-render-ms 2500 \
       --json

The same check is also exposed as the opt-in ``agi-web-cross-browser`` profile.
That profile installs Chromium/Firefox/WebKit Playwright browsers and runs the
fixture with Canvas fallback allowed. It is intentionally separate from the
default profile because browser downloads and headless WebGL behavior are
environment-dependent. Chromium remains the strict WebGL visual baseline.
