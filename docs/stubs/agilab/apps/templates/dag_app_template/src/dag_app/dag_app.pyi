import logging
import warnings
from pathlib import Path
from typing import Any, List, Tuple
from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher
from .dag_app_args import (
    ArgsOverrides,
    DagAppArgs,
    dump_args,
    ensure_defaults,
    load_args,
    merge_args,
)

logger = logging.getLogger(__name__)

class DagApp(BaseWorker):
    def __init__(self, *args: Any, **kwargs: Any) -> Any: ...
    def from_toml(cls, *args: Any, **kwargs: Any) -> Any: ...
    def to_toml(self, *args: Any, **kwargs: Any) -> Any: ...
    def as_dict(self) -> Any: ...
    def pool_init(*args: Any, **kwargs: Any) -> Any: ...
    def build_distribution(self) -> Any: ...
