agi-web native runtime
======================

``agi_web`` supplies AGILAB's native React host, Python UI facade and portable
component contracts. It is used by the main interface, retained Python views
and notebook widgets, using the native React runtime and Python adapters.
For installation, callback examples and export boundaries, see
:doc:`agilab-native-react-ui-notebook-export`.

This page describes source APIs. Published package versions and hosted demos
remain tied to their release evidence until a new release is published.

Python view runtime
-------------------

Use ``from agi_web import python_ui as ui`` for Python controls, state, forms,
tables, charts and navigation. Run a Python file with::

   python -m agi_web.react_python_host VIEW.py --address 127.0.0.1 --no-browser

Constructing the HTTP server selects Matplotlib's non-interactive ``Agg``
backend before request threads create figures. Matplotlib stays optional.
Importing the host or using the notebook adapter preserves the notebook's
chosen backend. Supply ``alt`` text for scientific figures; the native image
renderer also honours ``width="stretch"``.

``agi_web.notebook_python_view.render_python_view`` renders the same file in
Jupyter through an AnyWidget. Each view has its Python session; callback events
rerender that session. Notebook styles remain local to the widget.

Plotly's SVG layers and modebar styles are also copied into each widget's
shadow root. Charts honour ``figure.layout.height`` or use a default height of
450 pixels. Available-width changes resize the chart; its own rendered height
does not trigger another resize. Multiple widgets keep independent styles.

``agi_web.portable_python_host.export_python_host`` copies the standard-library
host and bundled assets into a portable directory. It does not export the
app's scientific dependencies, models or datasets automatically.

Frontend responsiveness
-----------------------

Tables display up to 100 rows per page. Previous/Next controls expose all
supplied rows; selection indices remain absolute and selected rows remain
selected across pages. A smaller response clamps the current page to the new
range. Selectable tables reuse unchanged cell renders when controls enter the
busy state. Selection controls stay disabled until the Python response
arrives, and new response data still updates the cells. These optimisations
are shared by the native web host and notebook Python-view widgets.

The source-tree benchmark uses real Chromium and a navigation fixture with a
1,000-row table. Scientific page bodies are replaced by fixtures; scientific
execution requires separate app qualification. Run it from an environment
with the AGILAB runtime dependencies, Playwright and psutil installed::

   python tools/testing/agilab_native_web_low_power_benchmark.py \
     --output-dir reports/agilab-native-web-low-power-measurements \
     --repetitions 9 --cpu-rates 1 4 --js-heap-limit-mib 256

Use a new output directory for each run. ``--source-repo`` selects a checkout
for a baseline comparison. Receipts verify the loaded Python modules and the
JavaScript actually served, retain individual timing samples and capture
screenshots. Interaction timing starts at the browser's click event and ends
after the updated view has reached two animation frames.

CPU throttling simulates frontend pressure; it does not qualify a physical
low-power computer. The V8 heap setting limits JavaScript old-space, rather
than total machine memory. RSS values are samples of the benchmark's own
processes, not a continuously measured peak. Compare the same fixture,
dependencies and profiles, and report timings without generalising them to
all apps or scientific calculations.

Portable component contract
---------------------------

- ``AgiWebComponent`` describes an evidence-backed visual island with an ID,
  title, payload, renderer and optional actions/assets.
- ``AgiWebRendererSpec`` identifies the renderer and bundled resources.
- ``AgiWebAction`` and ``AgiWebAsset`` describe the component's actions and
  assets without moving app computations into the frontend.
- ``component_to_static_html`` exports an already computed visualisation.
- ``render_python`` renders a component through the native Python UI facade.
- ``render_notebook`` provides the component notebook adapter.
- ``coordinate_map_component`` and ``analysis_curves_component`` build the
  common React map and curves payloads; ``render_react_notebook`` in
  ``agi_web.react_analysis`` supplies their interactive notebook renderer.

React, Graphviz, Vega and mathematical rendering resources are bundled
locally, including their licence notices. Rendering does not require a CDN.
Specialised app renderers may have additional dependencies and external data
requirements; declare those in the app rather than in worker-only packages.

Compatibility names
-------------------

``render_streamlit(..., streamlit=...)`` remains a compatibility spelling for
``render_python`` with an explicit Python UI provider. Some page helpers and
older app configuration retain similar names. They use the native facade and
do not restore the former dependency or launch path. Prefer the native names
when writing new views.

.. seealso::

   :doc:`agilab-builtin-private-offline-qualification` describes source-pinned
   offline qualification for builtin and private apps, including the shared
   web and notebook validation boundary.

.. toctree::
   :hidden:

   agilab-builtin-private-offline-qualification
