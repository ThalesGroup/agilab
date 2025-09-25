import logging
import warnings
from pathlib import Path
from typing import Any, List, Tuple

from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher

from .dag_app_args import (
    DagAppArgs,
)

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")


class DagApp(BaseWorker):
    """Minimal DAG app wiring with centralised argument handling."""

    worker_vars: dict[str, Any] = {}

    def __init__(
        self,
        env,
        args: DagAppArgs,
    ) -> None:
        super().__init__()
        self.env = env

        self.setup_args(args, env=env, error="DagApp requires an initialized DagAppArgs instance")

        data_uri = Path(self.args.data_uri).expanduser()

        self.path_rel = str(data_uri)
        self.dir_path = data_uri
        data_uri.mkdir(parents=True, exist_ok=True)

        payload = self.args.model_dump(mode="json")
        payload["dir_path"] = str(data_uri)
        WorkDispatcher.args = payload

    def _extend_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload["dir_path"] = str(self.dir_path)
        return payload

    @staticmethod
    def pool_init(vars: dict[str, Any]) -> None:
        DagApp.worker_vars = vars

    def build_distribution(
        self,
    ) -> Tuple[List[List], List[List[Tuple[int, int]]], str, str, str]:  # pragma: no cover - template hook
        return [], [], "id", "nb_fct", ""
