# AGI Web

[![PyPI version](https://img.shields.io/pypi/v/agi-web.svg?cacheSeconds=300)](https://pypi.org/project/agi-web/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-web.svg)](https://pypi.org/project/agi-web/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-web)](https://opensource.org/licenses/BSD-3-Clause)

`agi-web` defines a portable component contract for AGILAB app-owned UI islands.
It lets an app describe a rich browser component once, attach deterministic
evidence hashes, and render it in Streamlit or static HTML today while keeping a
stable payload for richer adapters.
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
from agi_web import AgiWebComponent, AgiWebRendererSpec, render_streamlit

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

render_streamlit(component)
```

The contract is intentionally framework-neutral:

- The payload is normalized JSON, so Canvas2D, WebGL, Streamlit, notebook,
  static-report, and future React renderers can consume the same data.
- The evidence block records the renderer, payload hash, action hash, and asset
  hash, so visual proof artifacts can be compared deterministically.
- The package has no JavaScript build dependency. The current static renderer
  ships Canvas2D/WebGL paths; framework-specific adapters can be added beside
  the contract without forcing Node tooling into every AGILAB install.

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
