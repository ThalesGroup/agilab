import logging
from pathlib import Path
from typing import Any, List, Tuple

import py7zr

from agi_env.data_archive_support import ensure_py7zr_package_compatibility
from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher

from .fireducks_app_args import (
    ArgsOverrides,
    FireducksAppArgs,
    dump_args,
    ensure_defaults,
    load_args,
    merge_args,
)

logger = logging.getLogger(__name__)
ensure_py7zr_package_compatibility(py7zr)


class FireducksApp(BaseWorker):
    """Minimal worker wiring for the FireDucks app template."""

    worker_vars: dict[str, Any] = {}

    def __init__(
        self,
        env,
        args: FireducksAppArgs | None = None,
        **kwargs: ArgsOverrides,
    ) -> None:
        super().__init__()
        self.env = env
        self.verbose = int(kwargs.pop("verbose", getattr(env, "verbose", 0) or 0))

        if args is None:
            allowed = set(FireducksAppArgs.model_fields.keys())
            clean = {k: v for k, v in kwargs.items() if k in allowed}
            if extra := set(kwargs) - allowed:
                logger.debug("Ignoring extra FireducksAppArgs keys: %s", sorted(extra))
            args = FireducksAppArgs(**clean)

        args = ensure_defaults(args, env=env)
        self.args = args

        data_in = self._resolve_data_dir(env, args.data_in)
        self._ensure_dataset(data_in, app_root=self._app_root(env))
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
    ) -> "FireducksApp":
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
    def _app_root(env: Any) -> Path:
        configured = getattr(env, "app_abs", None)
        if configured:
            return Path(configured)
        return Path(__file__).resolve().parents[2]

    def _ensure_dataset(self, data_in: Path, *, app_root: Path) -> None:
        try:
            if data_in.exists() and any(data_in.iterdir()):
                return

            logger.info("Creating data directory at %s", data_in)
            data_in.mkdir(parents=True, exist_ok=True)

            data_src = app_root / "data.7z"
            if not data_src.is_file():
                logger.info("No data.7z archive found at %s; leaving %s empty", data_src, data_in)
                return

            logger.info("Extracting data archive from %s to %s", data_src, data_in)
            with py7zr.SevenZipFile(data_src, mode="r") as archive:
                archive.extractall(path=data_in)
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
            logger.info("FireducksAppWorker finished")
        super().stop()

    def build_distribution(
        self,
    ) -> Tuple[List[List], List[List[Tuple[int, int]]], str, str, str]:  # pragma: no cover - template hook
        return [], [], "id", "nb_fct", ""


__all__ = ["FireducksApp"]
