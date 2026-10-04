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

``agi_web.notebook_python_view.render_python_view`` renders the same file in
Jupyter through an AnyWidget. Each view has its Python session; callback events
rerender that session. Notebook styles remain local to the widget.

``agi_web.portable_python_host.export_python_host`` copies the standard-library
host and bundled assets into a portable directory. It does not export the
app's scientific dependencies, models or datasets automatically.

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
