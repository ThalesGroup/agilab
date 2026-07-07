from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


PAGE_PATH = Path(
    "src/agilab/apps-pages/view_tri_gtia/src/view_tri_gtia/view_tri_gtia.py"
)


def _load_bundle(*, call_log: list[bool]) -> object:
    fake_network_sim = types.ModuleType("network_sim")
    fake_bundle = types.ModuleType("network_sim.tri_gtia_view")

    def _main() -> None:
        call_log.append(True)

    fake_bundle.main = _main
    fake_network_sim.tri_gtia_view = fake_bundle
    sys.modules["network_sim"] = fake_network_sim
    sys.modules["network_sim.tri_gtia_view"] = fake_bundle

    spec = importlib.util.spec_from_file_location(
        "view_tri_gtia_test_module", PAGE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_view_tri_gtia_launches_network_sim_entrypoint() -> None:
    call_log: list[bool] = []
    try:
        module = _load_bundle(call_log=call_log)
        module.main()
        assert call_log == [True]
    finally:
        sys.modules.pop("network_sim", None)
        sys.modules.pop("network_sim.tri_gtia_view", None)
