import logging
import warnings
from pathlib import Path
from typing import Any, List, Tuple

import py7zr

from agi_cluster.agi_distributor import AGI
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
warnings.filterwarnings("ignore")


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

        if args is None:
            allowed = set(FireducksAppArgs.model_fields.keys())
            clean = {k: v for k, v in kwargs.items() if k in allowed}
            if extra := set(kwargs) - allowed:
                logger.debug("Ignoring extra FireducksAppArgs keys: %s", sorted(extra))
            args = FireducksAppArgs(**clean)

        args = ensure_defaults(args, env=env)
        self.args = args

        data_uri = Path(args.data_uri).expanduser()
        if env._is_managed_pc:
            home = Path.home()
            data_uri = Path(str(data_uri).replace(str(home), str(home / "MyApp")))

        self.path_rel = str(data_uri)
        self.dir_path = data_uri

        self._ensure_dataset(data_uri)

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
