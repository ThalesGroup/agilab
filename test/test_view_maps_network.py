from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


PAGE = "src/agilab/apps-pages/view_maps_network/src/view_maps_network/view_maps_network.py"


def test_view_maps_network_uses_page_defaults_for_builtin_flight() -> None:
    active_app = Path("src/agilab/apps/builtin/flight_project").resolve()
    argv = [Path(PAGE).name, "--active-app", str(active_app)]

    with patch("sys.argv", argv):
        at = AppTest.from_file(PAGE, default_timeout=20)
        at.run(timeout=20)

    assert not at.exception
    state = at.session_state.filtered_state
    assert state.get("base_dir_choice") == "AGI_SHARE_DIR"
    assert state.get("datadir_rel") == "flight/dataframe"
    assert str(state.get("datadir", "")).endswith("/flight/dataframe")
