"""Minimal manager implementation for the mycode sample project."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, List, Tuple

from pydantic import ValidationError

from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher

from .app_args import ArgsOverrides, MycodeArgs, dump_args, ensure_defaults, load_args, merge_args

logger = logging.getLogger(__name__)


class Mycode(BaseWorker):
    """Lightweight orchestration surface for the mycode example."""

    worker_vars: dict[str, Any] = {}

    def __init__(
        self,
        env,
        args: MycodeArgs | None = None,
        **kwargs: ArgsOverrides,
    ) -> None:
        self.env = env
        self._ensure_managed_pc_share_dir(env)
        # Allow caller-provided verbosity flag even though the Pydantic model forbids extras.
        self.verbose = bool(kwargs.pop("verbose", env.verbose))

        if args is None:
            try:
                args = MycodeArgs(**kwargs)
            except ValidationError as exc:
                raise ValueError(f"Invalid Mycode arguments: {exc}") from exc
        self.args = args
        self.args.data_in = env.resolve_share_path(self.args.data_in)
        self.args.data_out = env.resolve_share_path(self.args.data_out)
        self.data_out = self.args.data_out

        # The mycode tests expect the data source directory to exist immediately
        # after instantiation so fixtures can write files into it.
        logger.info(f"mkdir {self.args.data_in}")
        self.args.data_in.mkdir(parents=True, exist_ok=True)

        WorkDispatcher.args = self.args.model_dump(mode="json")

        reset_target = getattr(self.args, "reset_target", False)
        try:
            if reset_target and self.data_out.exists():
                shutil.rmtree(
                    self.data_out,
                    ignore_errors=True,
                    onerror=WorkDispatcher._onerror,
                )
            logger.info(f"mkdir {self.data_out}")
            self.data_out.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning(
                "Issue while preparing dataframe directory %s: %s",
                self.data_out,
                exc,
            )

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
        payload["dir_path"] = str(self.args.data_in)
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
        _workers: dict | None = None,
    ) -> Tuple[List[List], List[List[Tuple[int, int]]], str, str, str]:  # pragma: no cover - template hook
        return [], [], "id", "nb_fct", ""


class MycodeApp(Mycode):
    """Alias retaining the historical suffix for compatibility."""


__all__ = ["Mycode", "MycodeApp"]

