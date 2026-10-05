"""Published demo downloads must not advertise their retired interface."""
import importlib
from io import BytesIO
from pathlib import Path
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "src/agilab/demos/resources"
DEMOS = (
    ("notebook_agent_demo", "notebook_showcase", {}),
    ("notebook_agent_local_demo", "notebook_showcase", {}),
    ("notebook_agent_rtx_demo", "notebook_showcase", {}),
    *((name + suffix, module, options)
      for name, module in (
          ("text_notebook_demo", "text_showcase"),
          ("forecast_notebook_demo", "forecast_showcase"),
          ("free_threading_demo", "free_threading_showcase"),
          ("milp_energy_demo", "milp_energy_showcase"))
      for suffix, options in (("", {}), ("_astra", {"astra": True}), ("_rtx", {"rtx": True}))),
)


@pytest.mark.parametrize("resource,module,options", DEMOS, ids=[demo[0] for demo in DEMOS])
def test_verified_download_has_current_interface_instructions(resource, module, options, monkeypatch):
    showcase = importlib.import_module("agilab.demos." + module)
    if module == "notebook_showcase":
        payload = showcase.download_bundle(RESOURCES / resource)
    else:
        suffix = "_astra" if options.get("astra") else "_rtx" if options.get("rtx") else ""
        base = resource.removesuffix(suffix) if suffix else resource
        monkeypatch.setattr(showcase, "DEMO_ROOT", RESOURCES / base)
        monkeypatch.setattr(showcase, "ASTRA_DEMO_ROOT", RESOURCES / (base + "_astra"))
        monkeypatch.setattr(showcase, "RTX_DEMO_ROOT", RESOURCES / (base + "_rtx"))
        payload = showcase.download_bundle(**options)
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        assert archive.testzip() is None
        assert {"app.py", "solution.ipynb", "lab_stages.toml"}.issubset(archive.namelist())
        for name in archive.namelist():
            if name.endswith((".py", ".ipynb", ".toml", ".txt", ".md")) or name == "NOTICE":
                assert "streamlit" not in archive.read(name).decode("utf-8").lower(), (resource, name)
