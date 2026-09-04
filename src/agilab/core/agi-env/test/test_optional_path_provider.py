from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agi_env.runtime.optional_path_provider import (
    OPTIONAL_PATH_ENTRY_POINT_GROUP,
    resolve_optional_path,
)


@dataclass(frozen=True)
class _FakeEntryPoint:
    name: str
    value: str
    provider: object

    def load(self) -> object:
        if isinstance(self.provider, BaseException):
            raise self.provider
        return self.provider


class _SelectableEntryPoints(tuple):
    def select(self, *, group: str):
        return self if group == OPTIONAL_PATH_ENTRY_POINT_GROUP else ()


def test_resolve_optional_path_uses_named_provider_and_expands_user(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    entry_points = _SelectableEntryPoints(
        (
            _FakeEntryPoint("other", "demo:other", lambda: "/ignored"),
            _FakeEntryPoint("pages", "demo:pages", lambda: "~/page-bundles"),
        )
    )

    assert resolve_optional_path("pages", entry_points_fn=lambda: entry_points) == (
        tmp_path / "page-bundles"
    )


def test_resolve_optional_path_ignores_broken_providers_and_supports_mapping_api(
    tmp_path: Path,
):
    entry_points = {
        OPTIONAL_PATH_ENTRY_POINT_GROUP: (
            _FakeEntryPoint("pages", "broken:pages", RuntimeError("broken provider")),
            _FakeEntryPoint("pages", "working:pages", {"root": tmp_path / "bundles"}),
        )
    }

    assert resolve_optional_path("pages", entry_points_fn=lambda: entry_points) == (
        tmp_path / "bundles"
    )
    assert resolve_optional_path("", entry_points_fn=lambda: entry_points) is None
