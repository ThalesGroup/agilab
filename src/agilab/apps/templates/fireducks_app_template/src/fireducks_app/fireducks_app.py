import logging
import warnings
from pathlib import Path
from typing import Any, List, Tuple

import py7zr

from agi_cluster.agi_distributor import AGI
from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher

from .fireducks_app_args import (
    FireducksAppArgs,
)

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")


class FireducksApp(BaseWorker):
    """Minimal worker wiring for the FireDucks app template."""

    worker_vars: dict[str, Any] = {}

    def __init__(
        self,
        env,
        args: FireducksAppArgs,
    ) -> None:
        super().__init__()
        self.env = env

        self.setup_args(args, env=env, error="FireducksApp requires an initialized FireducksAppArgs instance")

        data_uri = Path(self.args.data_uri).expanduser()

        self.path_rel = str(data_uri)
        self.dir_path = data_uri

        self._ensure_dataset(data_uri)

        payload = self.args.model_dump(mode="json")
        payload["dir_path"] = str(data_uri)
        WorkDispatcher.args = payload

    def _extend_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload["dir_path"] = str(self.dir_path)
        return payload

    def _ensure_dataset(self, data_uri: Path) -> None:
        try:
            if not data_uri.exists():
                logger.info("Creating data directory at %s", data_uri)
                data_uri.mkdir(parents=True, exist_ok=True)

                data_src = Path(AGI._env.app_abs) / "data.7z"
                if not data_src.is_file():
                    raise FileNotFoundError(f"Data archive not found at {data_src}")

                logger.info("Extracting data archive from %s to %s", data_src, data_uri)
                with py7zr.SevenZipFile(data_src, mode="r") as archive:
                    archive.extractall(path=data_uri)
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.error("Failed to initialize data directory: %s", exc)
            raise

    @staticmethod
    def pool_init(vars: dict[str, Any]) -> None:  # pragma: no cover - template hook
        FireducksApp.worker_vars = vars

    def work_pool(self, x: Any = None) -> None:  # pragma: no cover - template hook
        pass

    def work_done(self, worker_df: Any) -> None:  # pragma: no cover - template hook
        pass

    def stop(self) -> None:
        if self.verbose > 0:
            print("FireducksAppWorker All done!\n", end="")
        super().stop()

    def build_distribution(
        self,
    ) -> Tuple[List[List], List[List[Tuple[int, int]]], str, str, str]:  # pragma: no cover - template hook
        return [], [], "id", "nb_fct", ""
