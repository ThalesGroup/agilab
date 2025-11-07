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
warnings.filterwarnings("ignore")


class DagApp(BaseWorker):
    """Minimal DAG app wiring with centralised argument handling."""

    worker_vars: dict[str, Any] = {}

    def __init__(
        self,
        env,
        args: DagAppArgs | None = None,
        **kwargs: ArgsOverrides,
    ) -> None:
        super().__init__()
        self.env = env

        if args is None:
            allowed = set(DagAppArgs.model_fields.keys())
            clean = {k: v for k, v in kwargs.items() if k in allowed}
            if extra := set(kwargs) - allowed:
                logger.debug("Ignoring extra DagAppArgs keys: %s", sorted(extra))
            args = DagAppArgs(**clean)

        args = ensure_defaults(args, env=env)
        self.args = args

        data_in = self._resolve_data_dir(env, args.data_in)
        data_in.mkdir(parents=True, exist_ok=True)
        self.path_rel = str(data_in)
        self.dir_path = data_in
        self.args.data_in = data_in

        payload = args.model_dump(mode="json")
        payload["dir_path"] = str(data_in)
        WorkDispatcher.args = payload

    @classmethod
    def from_toml(
        cls,
        env,
        settings_path: str | Path = "app_settings.toml",
        section: str = "args",
        **overrides: ArgsOverrides,
    ) -> "DagApp":
        base = load_args(settings_path, section=section)
        merged = ensure_defaults(merge_args(base, overrides or None), env=env)
        return cls(env, args=merged)

    def to_toml(
        self,
        settings_path: str | Path = "app_settings.toml",
        section: str = "args",
        create_missing: bool = True,
    ) -> None:
        dump_args(self.args, settings_path, section=section, create_missing=create_missing)

    def as_dict(self) -> dict[str, Any]:
        payload = self.args.model_dump(mode="json")
        payload["dir_path"] = str(self.dir_path)
        return payload

    @staticmethod
    def pool_init(vars: dict[str, Any]) -> None:
        DagApp.worker_vars = vars

    def build_distribution(
        self,
    ) -> Tuple[List[List], List[List[Tuple[int, int]]], str, str, str]:  # pragma: no cover - template hook
        return [], [], "id", "nb_fct", ""


class Dag(DagApp):
    """Alias matching legacy imports without the App suffix."""


__all__ = ["DagApp", "Dag"]
