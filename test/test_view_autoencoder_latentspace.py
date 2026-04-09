from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


MODULE_PATH = Path(
    "src/agilab/apps-pages/view_autoencoder_latenspace/src/view_autoencoder_latentspace/autoencoder_latentspace.py"
)


def _load_module():
    fake_barviz = ModuleType("barviz")
    fake_barviz.Simplex = type("Simplex", (), {})
    fake_barviz.Collection = type("Collection", (), {})
    fake_barviz.Scrawler = type("Scrawler", (), {})
    fake_barviz.Attributes = type("Attributes", (), {})

    spec = importlib.util.spec_from_file_location("view_autoencoder_latentspace_test_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"barviz": fake_barviz}):
        spec.loader.exec_module(module)
    return module


def test_update_datadir_clears_selected_file_state(monkeypatch) -> None:
    module = _load_module()
    session_state = {
        "df_file": "obsolete.csv",
        "csv_files": ["obsolete.csv"],
        "input_datadir": "/tmp/new-data",
    }
    initialize_calls: list[str] = []

    monkeypatch.setattr(module, "st", SimpleNamespace(session_state=session_state))
    monkeypatch.setattr(module, "initialize_csv_files", lambda: initialize_calls.append("called"))

    module.update_datadir("datadir", "input_datadir")

    assert "df_file" not in session_state
    assert "csv_files" not in session_state
    assert session_state["datadir"] == "/tmp/new-data"
    assert initialize_calls == ["called"]
