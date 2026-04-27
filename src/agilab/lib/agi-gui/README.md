# AGI-GUI

[![PyPI version](https://img.shields.io/pypi/v/agi-gui.svg?cacheSeconds=300)](https://pypi.org/project/agi-gui/)
[![Python versions](https://img.shields.io/pypi/pyversions/agi-gui.svg)](https://pypi.org/project/agi-gui/)
[![License: BSD 3-Clause](https://img.shields.io/pypi/l/agi-gui)](https://opensource.org/licenses/BSD-3-Clause)
[![docs](https://img.shields.io/badge/docs-agilab-brightgreen.svg)](https://thalesgroup.github.io/agilab)

`agi-gui` provides the AGILAB UI dependency bundle for Streamlit pages. It depends on the headless `agi-env` runtime and adds the UI packages needed by AGILAB pages.

## Quick Install

```bash
pip install agi-gui
```

Use `agi-env` for worker/headless runtimes. Use `agi-gui` for Streamlit pages and local AGILAB UI sessions.

## File Picker

`agi_gui.file_picker` provides a reusable Streamlit popover picker for AGILAB pages that need server-side path selection without exposing arbitrary filesystem access.

```python
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

`agi_gui.ux_widgets` provides small compatibility wrappers for newer Streamlit primitives. Pages can adopt modern controls while still running on older UI runtimes.

```python
from agi_gui.ux_widgets import compact_choice, status_container, toast

selected = compact_choice(
    st.sidebar,
    "Steps file",
    available_steps_files,
    key="index_page",
    default=available_steps_files[0],
)

with status_container(st, "Running pipeline...", state="running") as status:
    run_pipeline()
    status.update(label="Pipeline completed", state="complete")
    toast(st, "Pipeline completed", state="success")
```

`compact_choice` uses `st.segmented_control` or `st.pills` when available and falls back to `selectbox` for long lists or older Streamlit versions.

## Repository

- Source: https://github.com/ThalesGroup/agilab/tree/main/src/agilab/lib/agi-gui
- Docs: https://thalesgroup.github.io/agilab
- Issues: https://github.com/ThalesGroup/agilab/issues
