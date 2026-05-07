"""Manager surface for the built-in global DAG project."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher

from .app_args import ArgsOverrides, GlobalDagArgs, dump_args, ensure_defaults, load_args, merge_args
from .preview_global_dag import PROJECT_ROOT, build_preview, planning_repo_root


class GlobalDag(BaseWorker):
    """Planning-only manager for built-in global DAG templates."""

    worker_vars: dict[str, Any] = {}

    def __init__(
        self,
        env,
        args: GlobalDagArgs | None = None,
        **kwargs: ArgsOverrides,
    ) -> None:
        self.env = env
        self.verbose = int(kwargs.pop("verbose", getattr(env, "verbose", 0) or 0))
        if args is None:
            try:
                args = GlobalDagArgs(**kwargs)
            except ValidationError as exc:
                raise ValueError(f"Invalid Global DAG arguments: {exc}") from exc
        self.args = ensure_defaults(args, env=env)
        WorkDispatcher.args = self.args.model_dump(mode="json")

    @classmethod
    def from_toml(
        cls,
        env,
        settings_path: str | Path = "app_settings.toml",
        section: str = "args",
        **overrides: ArgsOverrides,
    ) -> "GlobalDag":
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

    def preview(self) -> dict[str, Any]:
        dag_path = self.args.dag_path.expanduser()
        if not dag_path.is_absolute():
            dag_path = PROJECT_ROOT / dag_path
        return build_preview(
            repo_root=planning_repo_root(None),
            dag_path=dag_path,
            output_path=self.args.output_path.expanduser(),
        )

    def as_dict(self) -> dict[str, Any]:
        return self.args.model_dump(mode="json")

    def build_distribution(self, _workers: dict | None = None):
        return [], [], "stage", "weight", ""

    def stop(self) -> None:
        super().stop()


class GlobalDagApp(GlobalDag):
    """Compatibility alias retaining the app suffix."""


__all__ = ["GlobalDag", "GlobalDagApp"]
