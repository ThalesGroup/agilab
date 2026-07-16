from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


MANAGER_PATHS = (
    Path(
        "src/agilab/apps/builtin/flight_telemetry_project/src/"
        "flight_telemetry/flight_telemetry.py"
    ),
    Path(
        "src/agilab/lib/agi-app-flight-telemetry/src/agi_app_flight_telemetry/"
        "project/flight_telemetry_project/src/flight_telemetry/flight_telemetry.py"
    ),
    Path(
        "src/agilab/apps/builtin/minimal_app_project/src/minimal_app/minimal_app.py"
    ),
    Path("src/agilab/apps/builtin/execution_pandas_project/src/execution_pandas/execution_pandas.py"),
    Path("src/agilab/apps/builtin/execution_polars_project/src/execution_polars/execution_polars.py"),
    Path("src/agilab/apps/builtin/mission_decision_project/src/mission_decision/mission_decision.py"),
    Path(
        "src/agilab/apps/builtin/pytorch_playground_project/src/"
        "pytorch_playground/runtime/pytorch_playground.py"
    ),
    Path("src/agilab/apps/builtin/r_runtime_bridge_project/src/r_runtime_bridge/r_runtime_bridge.py"),
    Path(
        "src/agilab/apps/builtin/tescia_diagnostic_project/src/"
        "tescia_diagnostic/runtime/tescia_diagnostic.py"
    ),
    Path("src/agilab/apps/builtin/uav_queue_project/src/uav_queue/uav_queue.py"),
    Path(
        "src/agilab/apps/builtin/uav_relay_queue_project/src/"
        "uav_relay_queue/uav_relay_queue.py"
    ),
    Path(
        "src/agilab/apps/builtin/weather_forecast_legacy_project/src/"
        "weather_forecast_legacy/weather_forecast_legacy.py"
    ),
    Path(
        "src/agilab/apps/builtin/weather_forecast_project/src/"
        "weather_forecast/weather_forecast.py"
    ),
)


@pytest.mark.parametrize("manager_path", MANAGER_PATHS, ids=lambda path: path.parent.name)
def test_manager_data_out_reset_uses_shared_confinement_guard(
    manager_path: Path,
) -> None:
    source = manager_path.read_text(encoding="utf-8")

    assert "_safe_share_reset_path(" in source
    assert "self.data_out" in source
    assert "shutil.rmtree(self.data_out" not in source


def test_flight_telemetry_manager_mirror_stays_in_lockstep() -> None:
    builtin, packaged = MANAGER_PATHS[:2]

    assert builtin.read_bytes() == packaged.read_bytes()


def test_uav_relay_worker_mirror_stays_in_lockstep() -> None:
    builtin = Path(
        "src/agilab/apps/builtin/uav_relay_queue_project/src/"
        "uav_relay_queue_worker/uav_relay_queue_worker.py"
    )
    packaged = Path(
        "src/agilab/lib/agi-app-uav-relay-queue/src/agi_app_uav_relay_queue/"
        "project/uav_relay_queue_project/src/uav_relay_queue_worker/"
        "uav_relay_queue_worker.py"
    )

    assert builtin.read_bytes() == packaged.read_bytes()


def test_minimal_manager_rejects_share_root_reset(monkeypatch, tmp_path) -> None:
    app_src = Path(
        "src/agilab/apps/builtin/minimal_app_project/src"
    ).resolve()
    monkeypatch.syspath_prepend(str(app_src))
    from minimal_app import MinimalApp

    share_root = tmp_path / "share"
    share_root.mkdir()
    marker = share_root / "important.txt"
    marker.write_text("keep", encoding="utf-8")

    def _resolve_share_path(value: Path | str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else share_root / path

    env = SimpleNamespace(
        verbose=0,
        _is_managed_pc=False,
        home_abs=tmp_path,
        agi_share_path=share_root,
        agi_share_path_abs=share_root,
        resolve_share_path=_resolve_share_path,
        share_root_path=lambda: share_root,
    )

    with pytest.raises(ValueError, match="confinement root"):
        MinimalApp(
            env,
            data_in="minimal_app/dataset",
            data_out=".",
            reset_target=True,
        )

    assert marker.read_text(encoding="utf-8") == "keep"
