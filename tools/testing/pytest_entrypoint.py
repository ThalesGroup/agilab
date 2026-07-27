"""Run pytest without leaking the shared uv target into nested test commands."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping, Sequence

UV_TARGET_ENVIRONMENT_KEYS = (
    "UV_PROJECT_ENVIRONMENT",
    "UV_RUN_RECURSION_DEPTH",
    "VIRTUAL_ENV",
)


def cleaned_test_environment(
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return an environment safe for tests that invoke uv recursively."""

    env = dict(os.environ if source is None else source)
    for name in UV_TARGET_ENVIRONMENT_KEYS:
        env.pop(name, None)
    return env


def clear_uv_target_environment() -> None:
    """Stop nested uv commands from syncing the shared test environment."""

    for name in UV_TARGET_ENVIRONMENT_KEYS:
        os.environ.pop(name, None)


def main(argv: Sequence[str] | None = None) -> int:
    clear_uv_target_environment()
    import pytest

    return int(pytest.main(list(sys.argv[1:] if argv is None else argv)))


if __name__ == "__main__":
    raise SystemExit(main())
