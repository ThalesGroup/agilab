import os
import traceback
import logging
import shutil
import warnings
from pathlib import Path
from typing import Any
import py7zr
import polars as pl
from pydantic import ValidationError
from agi_env import AgiEnv, normalize_path
from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher
from .flight_args import (
    FlightArgs,
    FlightArgsTD,
    dump_args_to_toml,
    load_args_from_toml,
    merge_args,
)

logger = logging.getLogger(__name__)

class Flight(BaseWorker):
    def __init__(self, *args: Any, **kwargs: Any) -> Any: ...
    def from_toml(cls, *args: Any, **kwargs: Any) -> Any: ...
    def to_toml(self, *args: Any, **kwargs: Any) -> Any: ...
    def as_dict(self, *args: Any, **kwargs: Any) -> Any: ...
    def build_distribution(self, *args: Any, **kwargs: Any) -> Any: ...
    def get_data_from_hawk(self) -> Any: ...
    def extract_plane_from_file_name(*args: Any, **kwargs: Any) -> Any: ...
    def get_data_from_files(self) -> Any: ...
    def get_partition_by_planes(self, *args: Any, **kwargs: Any) -> Any: ...
