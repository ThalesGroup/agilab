import logging
import warnings
from pathlib import Path
from typing import Any

from agi_node.agi_dispatcher import BaseWorker, WorkDispatcher

from .app_args import (
    AgentAppArgs,
    ArgsOverrides,
    dump_args,
    ensure_defaults,
    load_args,
    merge_args,
)

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")


class Main(BaseWorker):
    """Minimal agent app wiring with centralised argument handling."""

    worker_vars: dict[str, Any] = {}

    def __init__(
        self,
        env,
        args: AgentAppArgs | None = None,
        **kwargs: ArgsOverrides,
    ) -> None:
        super().__init__()
        self.env = env

        if args is None:
            args = AgentAppArgs(**kwargs)

        args = ensure_defaults(args, env=env)
        self.args = args

        data_dir = Path(args.data_dir).expanduser()
        if env.is_managed_pc:
            home = Path.home()
            data_dir = Path(str(data_dir).replace(str(home), str(home / "MyApp")))

        self.path_rel = str(data_dir)
        self.dir_path = data_dir

        data_dir.mkdir(parents=True, exist_ok=True)

        payload = args.model_dump(mode="json")
        payload["dir_path"] = str(data_dir)
        WorkDispatcher.args = payload
        logger.info("Application initialized with data directory: %s", data_dir)

    @classmethod
    def from_toml(
        cls,
        env,
        settings_path: str | Path = "app_settings.toml",
        section: str = "args",
        **overrides: ArgsOverrides,
    ) -> "Main":
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
        Main.worker_vars = vars

    def perform_work(self) -> None:  # pragma: no cover - template hook
        logger.info("Starting main work...")

    def stop(self) -> None:
        if getattr(self, "verbose", 0) > 0:
            print("Main Application All done!\n", end="")
            logger.info("Main application stopped successfully.")
        super().stop()

