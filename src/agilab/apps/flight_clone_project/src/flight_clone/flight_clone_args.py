"""Argument management for Flight Trajectory project."""
from __future__ import annotations
from pathlib import Path
from typing import Any, TypedDict, Union
from pydantic import BaseModel, ConfigDict, Field
from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data, model_to_payload
from agi_node.agi_dispatcher.base_worker import BaseWorker


class FlightCloneArgs(BaseModel):
    model_config = ConfigDict(extra='ignore')
    num_flights: int = Field(default=1, ge=1)
    data_in: Path = Field(default_factory=lambda : Path(
        'flight_clone/dataset'))
    data_out: Path | None = None
    data_source: str = Field(default='file')
    beam_file: str = 'beams.csv'
    sat_file: str = 'satellites.csv'
    waypoints: str = 'waypoints.geojson'
    regenerate_waypoints: bool = False
    yaw_angular_speed: float = 1.0
    roll_angular_speed: float = 3.0
    pitch_angular_speed: float = 2.0
    vehicule_acceleration: float = 5.0
    max_speed: float = 900.0
    max_roll: float = 30.0
    max_pitch: float = 12.0
    target_climbup_pitch: float = 8.0
    pitch_enable_speed_ratio: float = 0.3
    altitude_loss_speed_threshold: float = 400.0
    landing_speed_target: float = 200.0
    descent_pitch_target: float = -3.0
    landing_pitch_target: float = 3.0
    cruising_pitch_max: float = 3.0
    descent_altitude_threshold_landing: int = 500
    max_speed_ratio_while_turining: float = 0.8
    enable_climb: bool = False
    enable_descent: bool = False
    default_alt_value: float = 4000.0
    plane_type: str = 'avions'
    dataset_format: str = 'csv'

    def to_toml_payload(self) -> dict[str, Any]:
        """Return a TOML-safe payload (Path/date → string)."""
        return model_to_payload(self)


class FlightCloneArgsTD(TypedDict, total=(False)):
    num_flights: int
    data_in: str
    data_out: str
    data_source: str
    beam_file: str
    sat_file: str
    waypoints: str
    regenerate_waypoints: bool
    yaw_angular_speed: float
    roll_angular_speed: float
    pitch_angular_speed: float
    vehicule_acceleration: float
    max_speed: float
    max_roll: float
    max_pitch: float
    target_climbup_pitch: float
    pitch_enable_speed_ratio: float
    altitude_loss_speed_threshold: float
    landing_speed_target: float
    descent_pitch_target: float
    landing_pitch_target: float
    cruising_pitch_max: float
    descent_altitude_threshold_landing: int
    max_speed_ratio_while_turining: float
    enable_climb: bool
    enable_descent: bool
    default_alt_value: float
    plane_type: str
    dataset_format: str


ArgsModel = FlightCloneArgs
ArgsOverrides = FlightCloneArgsTD


def load_args_from_toml(
    settings_path: str | Path,
    *,
    section: str = 'args',
) -> FlightCloneArgs:
    """Load arguments from TOML applying FlightClone defaults."""
    return load_model_from_toml(FlightCloneArgs, settings_path, section=section)


def apply_source_defaults(args: FlightCloneArgs, **kwargs: Any) -> FlightCloneArgs:
    """Backward-compatible alias that mirrors ``flight`` style helpers."""
    return ensure_defaults(args, **kwargs)


def load_args(settings_path: (str | Path), *, section: str='args'
    ) ->FlightCloneArgs:
    return load_model_from_toml(FlightCloneArgs, settings_path, section=section
        )


def merge_args(base: FlightCloneArgs, overrides: (FlightCloneArgsTD | None)
    =None) ->FlightCloneArgs:
    return merge_model_data(base, overrides)


def dump_args(args: FlightCloneArgs, settings_path: (str | Path), *,
    section: str='args', create_missing: bool=True) ->None:
    dump_model_to_toml(args, settings_path, section=section, create_missing
        =create_missing)


def resolve_data_in_for_env(env: Any, data_path: Union[str, Path]) ->Path:
    """Translate ``data_in`` into a writable dataset path using the shared framework."""
    return BaseWorker._resolve_data_dir(env, data_path)


def ensure_defaults(args: FlightCloneArgs, *, env: (Any | None)=None, **_: Any
    ) ->FlightCloneArgs:
    overrides: FlightCloneArgsTD = {}
    if not args.data_out:
        data_root = Path(args.data_in)
        overrides['data_out'] = data_root.parent / 'dataframe'
    return merge_args(args, overrides) if overrides else args


__all__ = ['ArgsModel', 'ArgsOverrides', 'FlightCloneArgs',
    'FlightCloneArgsTD', 'apply_source_defaults', 'dump_args',
    'ensure_defaults', 'load_args', 'load_args_from_toml', 'merge_args',
    'resolve_data_in_for_env']
