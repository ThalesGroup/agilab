from __future__ import annotations

import importlib.util
from pathlib import Path

_LOGGING_UTILS_PATH = Path(__file__).resolve().parents[1] / "src" / "agilab" / "logging_utils.py"
_LOGGING_UTILS_SPEC = importlib.util.spec_from_file_location("agilab_logging_utils_test", _LOGGING_UTILS_PATH)
if _LOGGING_UTILS_SPEC is None or _LOGGING_UTILS_SPEC.loader is None:
    raise ModuleNotFoundError(f"Unable to load logging_utils.py from {_LOGGING_UTILS_PATH}")
logging_utils = importlib.util.module_from_spec(_LOGGING_UTILS_SPEC)
_LOGGING_UTILS_SPEC.loader.exec_module(logging_utils)


def test_bound_log_value_keeps_short_strings_unchanged() -> None:
    assert logging_utils.bound_log_value("ready") == "ready"


def test_bound_log_value_normalizes_newlines_and_tabs() -> None:
    assert logging_utils.bound_log_value("alpha\nbeta\tgamma") == "alpha\\nbeta\\tgamma"


def test_bound_log_value_truncates_with_ellipsis() -> None:
    text = "x" * 20

    assert logging_utils.bound_log_value(text, 10) == "xxxxxxx..."
    assert len(logging_utils.bound_log_value(text, 10)) == 10
