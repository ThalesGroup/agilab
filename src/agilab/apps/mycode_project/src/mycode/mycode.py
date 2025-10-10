"""Minimal manager implementation for the mycode sample project."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, List, Tuple

from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher

from .mycode_args import ArgsOverrides, MycodeArgs, dump_args, ensure_defaults, load_args, merge_args

logger = logging.getLogger(__name__)


class Mycode(BaseWorker):
    """Lightweight orchestration surface for the mycode example."""

    worker_vars: dict[str, Any] = {}

    def __init__(
        self,
        env,
        args: MycodeArgs | None = None,
        **overrides: ArgsOverrides,
    ) -> None:
        super().__init__()
        self.env = env

        if args is None:
            allowed = set(MycodeArgs.model_fields.keys())
            clean = {k: v for k, v in overrides.items() if k in allowed}
            if extra := set(overrides) - allowed:
                logger.debug("Ignoring extra MycodeArgs keys: %s", sorted(extra))
            args = MycodeArgs(**clean)

        args = ensure_defaults(args, env=env)
        self.args = args

        data_uri = Path(args.data_uri).expanduser()
        data_uri.mkdir(parents=True, exist_ok=True)

        payload = args.model_dump(mode="json")
        payload["dir_path"] = str(data_uri)
        WorkDispatcher.args = payload

    @classmethod
    def from_toml(
        cls,
        env,
        settings_path: str | Path = "app_settings.toml",
        section: str = "args",
        **overrides: ArgsOverrides,
    ) -> "Mycode":
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
        payload["dir_path"] = str(Path(self.args.data_uri).expanduser())
        return payload

    @staticmethod
    def pool_init(vars: dict[str, Any]) -> None:
        Mycode.worker_vars = vars

    def work_pool(self, _: Any = None) -> None:  # pragma: no cover - template hook
        pass

    def work_done(self, _: Any) -> None:  # pragma: no cover - template hook
        pass

    def stop(self) -> None:
        if self.verbose > 0:
            print("Mycode worker completed.\n", end="")
        super().stop()

    def build_distribution(
        self,
    ) -> Tuple[List[List], List[List[Tuple[int, int]]], str, str, str]:  # pragma: no cover - template hook
        return [], [], "id", "nb_fct", ""
