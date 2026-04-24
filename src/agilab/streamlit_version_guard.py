from __future__ import annotations

from typing import Any


MIN_STREAMLIT_VERSION = "1.56.0"


def _version_key(version: str) -> tuple[int, int, int]:
    parts: list[int] = []
    for raw_part in str(version).split("."):
        digits = []
        for char in raw_part:
            if not char.isdigit():
                break
            digits.append(char)
        if not digits:
            parts.append(0)
        else:
            parts.append(int("".join(digits)))
        if len(parts) == 3:
            break
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def is_streamlit_version_supported(version: str, *, minimum: str = MIN_STREAMLIT_VERSION) -> bool:
    return _version_key(version) >= _version_key(minimum)


def streamlit_version_error_message(
    version: str,
    *,
    minimum: str = MIN_STREAMLIT_VERSION,
    runtime_label: str = "AGILAB",
) -> str:
    return (
        f"{runtime_label} requires Streamlit >= {minimum}, but this environment has "
        f"Streamlit {version or '<unknown>'}. Upgrade or recreate the venv before launching AGILAB."
    )


def require_streamlit_min_version(
    streamlit_module: Any,
    *,
    minimum: str = MIN_STREAMLIT_VERSION,
    runtime_label: str = "AGILAB",
) -> None:
    version = str(getattr(streamlit_module, "__version__", "") or "")
    if is_streamlit_version_supported(version, minimum=minimum):
        return

    message = streamlit_version_error_message(
        version,
        minimum=minimum,
        runtime_label=runtime_label,
    )
    reinstall_command = (
        "uv --preview-features extra-build-dependencies sync --upgrade-package streamlit"
    )
    try:
        streamlit_module.error(message)
        streamlit_module.code(reinstall_command, language="bash")
        streamlit_module.stop()
    except AttributeError:
        raise RuntimeError(f"{message} Suggested command: {reinstall_command}") from None
