"""Manager for the built-in R stage smoke app."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher

from .app_args import (
    ArgsOverrides,
    RStageSmokeArgs,
    dump_args,
    ensure_defaults,
    load_args,
    merge_args,
)

logger = logging.getLogger(__name__)


class RStageSmoke(BaseWorker):
    """Manager that dispatches one external Rscript JSON/artifact stage."""

    worker_vars: dict[str, Any] = {}

    def __init__(
        self,
        env,
        args: RStageSmokeArgs | None = None,
        **kwargs: ArgsOverrides,
    ) -> None:
        self.env = env
        self._ensure_managed_pc_share_dir(env)
        self.verbose = int(kwargs.pop("verbose", getattr(env, "verbose", 0) or 0))

        if args is None:
            try:
                args = RStageSmokeArgs(**kwargs)
            except ValidationError as exc:
                raise ValueError(f"Invalid RStageSmoke arguments: {exc}") from exc

        self.args = ensure_defaults(args, env=env)
        self.args.data_out = env.resolve_share_path(self.args.data_out)
        self.data_out = self.args.data_out

        if self.args.reset_target and self.data_out.exists():
            shutil.rmtree(self.data_out, ignore_errors=True, onerror=WorkDispatcher._onerror)
        self.data_out.mkdir(parents=True, exist_ok=True)
        self.analysis_artifact_dir.mkdir(parents=True, exist_ok=True)

        WorkDispatcher.args = self.args.model_dump(mode="json")

    @property
    def analysis_artifact_dir(self) -> Path:
        export_root = Path(getattr(self.env, "AGILAB_EXPORT_ABS", Path.home() / "export"))
        target = str(
            getattr(self.env, "target", "")
            or getattr(self.env, "app", "")
            or getattr(self.env, "active_app", "")
            or "r_stage_smoke_project"
        )
        return export_root / target / "r_stage_smoke"

    @classmethod
    def from_toml(
        cls,
        env,
        settings_path: str | Path = "app_settings.toml",
        section: str = "args",
        **overrides: ArgsOverrides,
    ) -> "RStageSmoke":
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
        return self.args.model_dump(mode="json")

    def build_distribution(self, workers):
        try:
            worker_count = max(1, int(workers))
        except (TypeError, ValueError):
            worker_count = 1
        work_plan = [[["r_stage_smoke"]]] + [[] for _ in range(worker_count - 1)]
        metadata = [[{"run": "r_stage_smoke", "work_items": 1}]] + [
            [] for _ in range(worker_count - 1)
        ]
        return work_plan, metadata, "run", "work_items", "items"


class RStageSmokeApp(RStageSmoke):
    """Compatibility class with the descriptive *App suffix."""


__all__ = ["RStageSmoke", "RStageSmokeApp"]
