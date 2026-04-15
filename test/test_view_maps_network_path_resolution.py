from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

from agi_env import AgiEnv


MODULE_PATH = Path(
    "src/agilab/apps-pages/view_maps_network/src/view_maps_network/view_maps_network.py"
)


def _load_view_maps_network_module() -> object:
    spec = importlib.util.spec_from_file_location("view_maps_network_path_resolution_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    active_app = Path("/Users/agi/PycharmProjects/thales_agilab/apps/sb3_trainer_project")
    argv = [MODULE_PATH.name, "--active-app", str(active_app)]
    AgiEnv.reset()
    with patch("sys.argv", argv):
        spec.loader.exec_module(module)
    return module


def test_view_maps_network_choose_existing_declared_path_resolves_selected_base_relative_file(
    tmp_path: Path,
) -> None:
    module = _load_view_maps_network_module()

    share_root = tmp_path / "clustershare"
    cloud_path = share_root / "flight_trajectory" / "dataset" / "CloudMapSat.npz"
    cloud_path.parent.mkdir(parents=True)
    cloud_path.write_bytes(b"npz")

    chosen = module._choose_existing_declared_path(
        "flight_trajectory/dataset/CloudMapSat.npz",
        "",
        [share_root / "flight_trajectory", share_root],
    )

    assert chosen == str(cloud_path)


def test_view_maps_network_choose_existing_declared_path_falls_back_to_valid_default(
    tmp_path: Path,
) -> None:
    module = _load_view_maps_network_module()

    share_root = tmp_path / "clustershare"
    cloud_path = share_root / "flight_trajectory" / "dataset" / "CloudMapIvdl.npz"
    cloud_path.parent.mkdir(parents=True)
    cloud_path.write_bytes(b"npz")

    chosen = module._choose_existing_declared_path(
        "missing/CloudMapIvdl.npz",
        "flight_trajectory/dataset/CloudMapIvdl.npz",
        [share_root / "flight_trajectory", share_root],
    )

    assert chosen == str(cloud_path)


def test_view_maps_network_allocation_search_roots_prefer_selected_base_target_root(
    tmp_path: Path,
) -> None:
    module = _load_view_maps_network_module()

    base_path = tmp_path / "clustershare"
    datadir_path = base_path / "flight_trajectory"
    export_base = tmp_path / "export"
    local_share_root = tmp_path / "localshare"

    target_root, roots = module._allocation_search_roots(
        base_path=base_path,
        datadir_path=datadir_path,
        export_base=export_base,
        local_share_root=local_share_root,
        target_name="sb3_trainer",
    )

    assert target_root == base_path / "sb3_trainer"
    assert base_path / "sb3_trainer" in roots
    assert base_path / "sb3_trainer" / "pipeline" in roots
    assert local_share_root / "sb3_trainer" in roots
