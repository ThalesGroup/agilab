# AGI Web

[![PyPI version](https://img.shields.io/pypi/v/agi-web.svg?cacheSeconds=300)](https://pypi.org/project/agi-web/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-web.svg)](https://pypi.org/project/agi-web/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-web)](https://opensource.org/licenses/BSD-3-Clause)

`agi-web` defines a portable component contract for AGILAB app-owned UI islands.
It lets an app describe a rich browser component once, attach deterministic
evidence hashes, and render it in the native React host, Jupyter or static HTML.
Coordinate maps and analysis curves use the same bundled React views in both hosts.
The bundled static adapter can render a WebGL decision-surface heatmap with a
Canvas2D overlay/fallback for local replay/scrub controls, clickable timelines,
keyboard scrubbing, confidence badges, uncertainty-contour glow, and hover
readouts when the payload includes boundary snapshots.

## Quick Install

```bash
pip install agi-web
```

Most users get it through the AGILAB UI profile:

```bash
pip install "agilab[ui]"
```

## Component Contract

```python
from agi_web import AgiWebComponent, AgiWebRendererSpec, render_python

component = AgiWebComponent(
    component_id="playground-boundary",
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

render_python(component)
```

The contract is intentionally framework-neutral:

- The payload is normalized JSON, so Canvas2D, WebGL, native Python views, notebook,
  static-report, and React renderers can consume the same data.
- The evidence block records the renderer, payload hash, action hash, and asset
  hash, so visual proof artifacts can be compared deterministically.
- The package has no JavaScript build dependency. The current static renderer
  ships Canvas2D/WebGL paths; React assets are also bundled in the wheel. Adapters sit beside
  the contract without forcing Node tooling into every AGILAB install.

## Shared React Analysis Views

Install `agi-web[notebook]` in the notebook kernel environment and enable Jupyter
widgets in the frontend. Python views use the bundled native component protocol.
The coordinate view plots longitude/latitude without external tiles; the existing
AGILAB geographic map remains a separate display option. Curves support numeric
or UTC datetime axes, series visibility, range controls and missing-value gaps.

```python
from agi_web import coordinate_map_component, analysis_curves_component
from agi_web import render_notebook, render_python

positions = coordinate_map_component(
    [{"latitude": 48, "longitude": 2, "flight": "001"}],
    label="flight", group="flight", component_id="flight-positions",
)
curves = analysis_curves_component(
    [{"date": "2026-01-01", "observed": 10, "predicted": 11}],
    x="date", series=("observed", "predicted"), component_id="flight-curves",
)

# In Jupyter, display the returned widgets in a cell.
widget = render_notebook(positions)
display(widget)
# Point clicks synchronize widget.selection back to Python.

# In a native Python view, the result exposes selection and triggers rerenders.
result = render_python(curves)
```

Use distinct `component_id` values for simultaneous views. The constructors
exclude invalid coordinates/dates, preserve original row identifiers and report
chart truncation (20,000 rows by default). They leave full source data intact.
React views require a live widget frontend; the static HTML adapter remains for
the existing Canvas2D/WebGL components. Notebook page exports always retain
native tables and diagnose missing Python widget dependencies before using Plotly.

Maintainers rebuild assets with `npm ci --ignore-scripts` then `npm run build`
in `frontend/`. The committed bundles contain React and its license, require no
CDN downloads, and ship with deterministic SHA-256 integrity metadata.

Run the real-host browser smoke (with Chromium installed for Playwright):

```bash
UV_PROJECT_ENVIRONMENT=.venv-dev uv --preview-features extra-build-dependencies run \
  --no-sync --with playwright --with jupyterlab --with anywidget --with ipywidgets \
  python tools/testing/agilab_react_analysis_browser_smoke.py
```

The smoke checks point selections in Python, filters, range/reset controls,
instance isolation, browser console/network errors and external requests. Its
temporary loopback servers and kernel are stopped after the run.

## React main interface

The main AGILAB entrypoint now uses a React workspace header, project picker,
navigation, home cards, the PROJECT overview and ANALYSIS selection controls.
The native Python session owns registered routes and
deep links; the component emits one-shot actions validated against server-side
projects and routes. Project changes reuse the URL/bootstrap lifecycle and clear
project-specific inputs after the new environment loads, before widgets render.
The PROJECT overview displays the existing Python environment-health model and
links to execution, analysis/notebook export, pipeline and project editing.
Workspace actions also validate the canonical project path so a stale action
cannot cross between projects with the same name in different directories.
Detailed diagnostics and project metrics keep their native Python renderers.
The ANALYSIS overview uses the existing artifact summary, discovered views and
notebooks. A saved selection follows the existing Python settings persistence;
queued actions validate the project path and current selection/discovery context.
An unsuccessful settings write keeps a separate draft and an enabled retry;
the interface confirms a saved selection after the write succeeds.
Opening a saved view or notebook uses its server-resolved route. The notebook
export button opens the existing Python WORKFLOW export controls, including their
protection of edited exports. Child views keep their Python launchers.

Pipeline editing, specialized geographic views, project operations and settings
continue in Python. Standalone Python pages retain their native project picker.
Notebook exports continue to use the independent shared map/curve renderers.
The source dependency graph and native host no longer require Streamlit.
Notebook exports render retained Python views through the same React host bundle
and a Jupyter widget bridge. Maps and curves also retain their dedicated widgets.
`render_streamlit(..., streamlit=...)` remains a compatibility spelling for
`render_python`; its default provider is `agi_web.python_ui`.
The frontend ships in the `agi-web` wheel and uses the same `npm run build` step;
end users do not need Node or a CDN.

Validate the main-page boundary in a real browser:

```bash
UV_PROJECT_ENVIRONMENT=.venv-dev uv --preview-features extra-build-dependencies run \
  --no-sync --with playwright python tools/testing/agilab_react_main_interface_browser_smoke.py
```

The fixture uses the real main navigation with isolated project and Python page
bodies and health facts; page-specific AppTests cover the retained Python tools. Browser evidence
includes saved/empty analysis selections, Python view/notebook routes, the Workflow
export entry, cold project changes, native widget reruns, direct URLs,
session isolation, responsive layout, console/network results and screenshots.

## Visual Guard

The repository ships a deterministic browser fixture for this adapter:

```bash
uv --preview-features extra-build-dependencies run --with playwright --with pillow \
  python tools/agi_web_visual_regression.py --browser chromium --max-render-ms 2500 --json
```

The `agi-web-visual` workflow parity profile compares Chromium output against
the committed `docs/source/_static/agi-web-visual-baseline` screenshot baseline
and records per-browser render timing. Pass repeated `--browser` options for
manual Firefox/WebKit smoke checks.

## Repository

- Source: https://github.com/ThalesGroup/agilab/tree/main/src/agilab/lib/agi-web
- Docs: https://thalesgroup.github.io/agilab/agi-web.html
- Issues: https://github.com/ThalesGroup/agilab/issues
