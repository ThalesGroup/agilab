import logging
import warnings
from pathlib import Path
from typing import Any, List, Tuple
from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher
from .dag_app_args import (
    ArgsOverrides,
    DagAppArgs,
)

logger = logging.getLogger(__name__)

class DagApp(BaseWorker):
    def __init__(self, *args: Any, **kwargs: Any) -> Any: ...
    def _extend_payload(self, *args: Any, **kwargs: Any) -> Any: ...
    def pool_init(*args: Any, **kwargs: Any) -> Any: ...
    def build_distribution(self) -> Any: ...
