"""Manager for the built-in UAV queue project."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher

from .app_args import ArgsOverrides, UavQueueArgs, dump_args, ensure_defaults, load_args, merge_args

logger = logging.getLogger(__name__)


class UavQueue(BaseWorker):
    """Manager that turns a lightweight UAV queue scenario into a runnable app."""

    worker_vars: dict[str, Any] = {}

    def __init__(
        self,
        env,
        args: UavQueueArgs | None = None,
        **kwargs: ArgsOverrides,
    ) -> None:
        self.env = env
        self._ensure_managed_pc_share_dir(env)
        self.verbose = int(kwargs.pop("verbose", getattr(env, "verbose", 0) or 0))

        if args is None:
            try:
                args = UavQueueArgs(**kwargs)
            except ValidationError as exc:
                raise ValueError(f"Invalid UavQueue arguments: {exc}") from exc

        self.args = ensure_defaults(args, env=env)
        self.args = self._apply_managed_pc_paths(self.args)
        self.args.data_in = env.resolve_share_path(self.args.data_in)
        self.args.data_out = env.resolve_share_path(self.args.data_out)
        self.data_out = self.args.data_out

        self.args.data_in.mkdir(parents=True, exist_ok=True)
        self._ensure_dataset(self.args.data_in)

        if self.args.reset_target and self.data_out.exists():
            shutil.rmtree(self.data_out, ignore_errors=True, onerror=WorkDispatcher._onerror)
        self.data_out.mkdir(parents=True, exist_ok=True)
        self.analysis_artifact_dir.mkdir(parents=True, exist_ok=True)

        WorkDispatcher.args = self.args.model_dump(mode="json")

    @property
    def analysis_artifact_dir(self) -> Path:
        export_root = Path(getattr(self.env, "AGILAB_EXPORT_ABS", Path.home() / "export"))
        return export_root / self.env.target / "queue_analysis"

    def _sample_dataset_source(self) -> Path:
        return Path(__file__).resolve().parent / "sample_data" / "uav_queue_hotspot.json"

    def _ensure_dataset(self, data_in: Path) -> None:
        existing = sorted(data_in.glob(self.args.files))
        if existing:
            return
        sample = self._sample_dataset_source()
        if not sample.is_file():
            raise FileNotFoundError(f"Bundled sample scenario missing: {sample}")
        destination = data_in / sample.name
        shutil.copy2(sample, destination)
        logger.info("Seeded UAV queue sample scenario at %s", destination)

    @classmethod
    def from_toml(
        cls,
        env,
        settings_path: str | Path = "app_settings.toml",
        section: str = "args",
        **overrides: ArgsOverrides,
    ) -> "UavQueue":
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
        files = sorted(self.args.data_in.glob(self.args.files))
        if self.args.nfile > 0:
            files = files[: self.args.nfile]
        if not files:
            raise FileNotFoundError(
                f"No scenario file found in {self.args.data_in} with pattern {self.args.files!r}"
            )

        weights = [(str(path), max(int(path.stat().st_size // 1024), 1)) for path in files]
        if len(weights) == 1:
            worker_chunks = [[weights[0]]]
        else:
            worker_chunks = WorkDispatcher.make_chunks(
                len(weights),
                weights,
                workers=workers,
                verbose=self.verbose,
                threshold=12,
            )

        work_plan = []
        metadata = []
        for chunk in worker_chunks:
            file_batch = [file_path for file_path, _ in chunk]
            total_size_kb = sum(size_kb for _, size_kb in chunk)
            batch_label = Path(file_batch[0]).name if len(file_batch) == 1 else f"{len(file_batch)} files"
            work_plan.append([file_batch])
            metadata.append([{"scenario": batch_label, "size_kb": total_size_kb}])

        return work_plan, metadata, "scenario", "size_kb", "KB"


class UavQueueApp(UavQueue):
    """Compatibility alias retaining the historical *App suffix."""


class UavRelayQueue(UavQueue):
    """Historical descriptive alias for the lightweight UAV queue manager."""


class UavRelayQueueApp(UavRelayQueue):
    """Compatibility alias retaining the descriptive *App suffix."""


__all__ = ["UavQueue", "UavQueueApp", "UavRelayQueue", "UavRelayQueueApp"]
