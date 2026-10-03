# AGI-GUI

[![PyPI version](https://img.shields.io/pypi/v/agi-gui.svg?cacheSeconds=300)](https://pypi.org/project/agi-gui/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-gui.svg)](https://pypi.org/project/agi-gui/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-gui)](https://opensource.org/licenses/BSD-3-Clause)
[![API docs](https://img.shields.io/badge/docs-agi--gui-brightgreen.svg)](https://thalesgroup.github.io/agilab/agi-gui.html)

`agi-gui` provides the UI dependency bundle for native Python UI pages. It depends on the headless `agi-env` runtime
and adds reusable page helpers and UI packages.

> The native UI described here is the current source implementation. Previously
> published PyPI packages may still use the former provider; the commands below
> install their published release, not this source migration. From an AGILAB
> source checkout, use `uv sync --extra ui --extra notebook` to install the native
> interface and notebook widget. Local validation does not publish those changes.

## Quick Install

```bash
pip install agi-gui
```

Use `agi-env` for worker/headless runtimes. Use `agi-gui` for native Python UI pages and local UI sessions.

## File Picker

`agi_gui.file_picker` provides a reusable native Python UI popover picker for pages that need server-side path selection
without exposing arbitrary filesystem access.

```python
from agi_web import python_ui as st
from agi_gui.file_picker import agi_file_picker

selected_path = agi_file_picker(
    "Browse dataframe",
    roots={"Project": active_app_export_dir},
    key=f"{project_name}:dataframe_picker",
    patterns=["*.csv", "*.parquet", "*.json"],
    container=st.sidebar,
)
```

The picker validates manual paths and dataframe selections against the configured roots, keeps widget keys namespaced, and can optionally save uploaded files when the caller provides an explicit `upload_dir`.

## UX Widgets

`agi_gui.ux_widgets` provides small compatibility wrappers for the native Python UI primitives. Pages can adopt modern controls while still running on older UI runtimes.

```python
from agi_gui.ux_widgets import compact_choice, status_container, toast

selected = compact_choice(
    st.sidebar,
    "Stages file",
    available_stages_files,
    key="index_page",
    default=available_stages_files[0],
)

with status_container(st, "Running pipeline...", state="running") as status:
    run_pipeline()
    status.update(label="Pipeline completed", state="complete")
    toast(st, "Pipeline completed", state="success")
```

`compact_choice` uses `st.segmented_control` or `st.pills` when available and falls back to `selectbox` for long lists or earlier UI providers.

## Widget Registry

`agi_gui.widget_registry` provides a typed registry for reusable widgets. It gives pages and docs a single discovery point without breaking direct imports from `agi_gui.file_picker` or `agi_gui.ux_widgets`.

```python
from agi_gui import default_widget_registry, get_widget

registry = default_widget_registry()
rows = registry.as_rows()
file_picker = get_widget("file_picker")
same_picker = get_widget("agi_file_picker")
```

The default registry includes file selection, compact choice, action buttons, confirmation, status, empty-state, notice, and toast widgets.

## Repository

- Source: https://github.com/ThalesGroup/agilab/tree/main/src/agilab/lib/agi-gui
- Docs: https://thalesgroup.github.io/agilab/agi-gui.html
- Issues: https://github.com/ThalesGroup/agilab/issues
