"""Workerless local app template for AGILAB."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .simple_app_args import (
    ArgsOverrides,
    SimpleAppArgs,
    dump_args,
    ensure_defaults,
    load_args,
    merge_args,
)

logger = logging.getLogger(__name__)


class SimpleApp:
    """Minimal AGILAB app manager without worker deployment."""

    def __init__(
        self,
        env,
        args: SimpleAppArgs | None = None,
        **kwargs: ArgsOverrides,
    ) -> None:
        self.env = env
        self.verbose = int(kwargs.pop("verbose", getattr(env, "verbose", 0) or 0))

        if args is None:
            allowed = set(SimpleAppArgs.model_fields.keys())
            clean = {key: value for key, value in kwargs.items() if key in allowed}
            if extra := set(kwargs) - allowed:
                logger.debug("Ignoring extra SimpleAppArgs keys: %s", sorted(extra))
            args = SimpleAppArgs(**clean)

        self.args = ensure_defaults(args, env=env)
        self.args.data_out = self._resolve_output_path(env, self.args.data_out)
        self.data_out = self.args.data_out

    @classmethod
    def from_toml(
        cls,
        env,
        settings_path: str | Path = "app_settings.toml",
        section: str = "args",
        **overrides: ArgsOverrides,
    ) -> "SimpleApp":
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

    def run(self) -> Path:
        """Write a deterministic local manifest and return its path."""

        self.data_out.mkdir(parents=True, exist_ok=True)
        manifest_path = self.data_out / "simple_app_manifest.json"
        payload = {
            "schema": "agilab.simple_app_template.manifest.v1",
            "title": self.args.title,
            "note": self.args.note,
        }
        manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return manifest_path

    @staticmethod
    def _resolve_output_path(env: Any, value: Path) -> Path:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
        resolve_share_path = getattr(env, "resolve_share_path", None)
        if callable(resolve_share_path):
            return Path(resolve_share_path(path))
        return path


__all__ = ["SimpleApp"]
