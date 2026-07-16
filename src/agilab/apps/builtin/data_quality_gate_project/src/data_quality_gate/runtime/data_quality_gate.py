"""Manager for the built-in data quality gate app."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher

from .app_args import (
    ArgsOverrides,
    DataQualityGateArgs,
    dump_args,
    ensure_defaults,
    filter_arg_overrides,
    load_args,
    merge_args,
)

logger = logging.getLogger(__name__)


class DataQualityGate(BaseWorker):
    """Manager that dispatches one deterministic data-quality gate run."""

    worker_vars: dict[str, Any] = {}

    def __init__(
        self,
        env,
        args: DataQualityGateArgs | None = None,
        **kwargs: ArgsOverrides,
    ) -> None:
        self.env = env
        self._ensure_managed_pc_share_dir(env)
        self.verbose = int(kwargs.pop("verbose", getattr(env, "verbose", 0) or 0))
        arg_overrides = filter_arg_overrides(kwargs)

        if args is None:
            try:
                args = DataQualityGateArgs(**arg_overrides)
            except ValidationError as exc:
                raise ValueError(f"Invalid DataQualityGate arguments: {exc}") from exc
        elif arg_overrides:
            args = merge_args(args, arg_overrides)

        self.args = ensure_defaults(args, env=env)
        self.args = self._apply_managed_pc_paths(self.args)
        try:
            self.data_out = env.resolve_share_path(self.args.data_out)
        except ValueError as exc:
            raise ValueError(f"Invalid DataQualityGate data_out path: {exc}") from exc

        resolve_input = getattr(env, "resolve_share_input_path", None) or env.resolve_share_path
        protected_inputs: list[Path] = []
        for value in (
            self.args.baseline_csv,
            self.args.candidate_csv,
            self.args.contract_json,
            self.args.thresholds_json,
        ):
            if value is None:
                continue
            protected_path = Path(value).expanduser()
            protected_path = Path(resolve_input(protected_path))
            protected_inputs.append(protected_path)

        if self.args.reset_target:
            reset_path = self._safe_share_reset_path(
                env,
                self.data_out,
                protected_paths=protected_inputs,
                label="data_out",
            )
            if reset_path.exists():
                shutil.rmtree(reset_path, ignore_errors=True, onerror=WorkDispatcher._onerror)
        self.data_out.mkdir(parents=True, exist_ok=True)
        self.analysis_artifact_dir.mkdir(parents=True, exist_ok=True)

    @property
    def analysis_artifact_dir(self) -> Path:
        export_root = Path(getattr(self.env, "AGILAB_EXPORT_ABS", Path.home() / "export"))
        target = str(
            getattr(self.env, "target", "")
            or getattr(self.env, "app", "")
            or getattr(self.env, "active_app", "")
            or "data_quality_gate_project"
        )
        return export_root / target / "data_quality_gate"

    @classmethod
    def from_toml(
        cls,
        env,
        settings_path: str | Path = "app_settings.toml",
        section: str = "args",
        **overrides: ArgsOverrides,
    ) -> "DataQualityGate":
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
        work_plan = [[["data_quality_gate"]]] + [[] for _ in range(worker_count - 1)]
        metadata = [[{"run": "data_quality_gate", "work_items": 1}]] + [[] for _ in range(worker_count - 1)]
        return work_plan, metadata, "run", "work_items", "items"


class DataQualityGateApp(DataQualityGate):
    """Compatibility class with the descriptive *App suffix."""


__all__ = ["DataQualityGate", "DataQualityGateApp"]
