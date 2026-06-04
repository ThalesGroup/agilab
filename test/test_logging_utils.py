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


def test_bound_log_value_handles_nonpositive_and_tiny_limits() -> None:
    assert logging_utils.bound_log_value("payload", 0) == ""
    assert logging_utils.bound_log_value("payload", -1) == ""
    assert logging_utils.bound_log_value("payload", 1) == "."
    assert logging_utils.bound_log_value("payload", 2) == ".."
    assert logging_utils.bound_log_value("payload", 3) == "..."


def test_compact_log_view_keeps_signal_lines_and_omits_benign_bulk() -> None:
    text = "\n".join(
        [
            *[f"progress {index}" for index in range(20)],
            "ModuleNotFoundError: No module named 'demo_worker'",
            "continuing cleanup",
            "tail marker",
        ]
    )

    view = logging_utils.compact_log_view(text, verbose=1, tail_limit=1)

    assert view["strategy"] == "signal-first-token-budget"
    assert view["line_count"] == 23
    assert view["signal_count"] == 1
    assert view["signals"] == [
        {"line": 21, "text": "ModuleNotFoundError: No module named 'demo_worker'"}
    ]
    assert view["tail"] == ["23: tail marker"]
    assert view["omitted_line_count"] == 21
    rendered = logging_utils.render_compact_log_view(view)
    assert "signals: 1" in rendered
    assert "progress 1" not in rendered


def test_compact_log_view_expands_context_only_when_verbose_is_detailed() -> None:
    text = "\n".join(["setup", "before", "ERROR: failed to connect", "after", "done"])

    standard = logging_utils.compact_log_view(text, verbose=1, tail_limit=0)
    detailed = logging_utils.compact_log_view(text, verbose=2, tail_limit=0, context_radius=1)

    assert standard["context"] == []
    assert detailed["context"] == ["2: before", "4: after"]


def test_compact_log_view_debug_includes_small_logs_but_caps_large_logs() -> None:
    small = logging_utils.compact_log_view("a\nb", verbose=3)
    large = logging_utils.compact_log_view("\n".join(f"line {i}" for i in range(5)), verbose=3, debug_max_lines=2)

    assert small["debug_lines"] == ["1: a", "2: b"]
    assert large["debug_lines"] == []
    assert "full prompt-facing output is capped" in large["note"]


def test_compact_log_view_redacts_secret_like_values() -> None:
    view = logging_utils.compact_log_view(
        "ERROR api_key=sk-proj-abcdefghijklmnopqrstuvwxyz123456 token=ghp_abcdefghijklmnopqrstuvwxyz123456",
        verbose=1,
    )

    rendered = logging_utils.render_compact_log_view(view)
    assert "sk-proj" not in rendered
    assert "ghp_" not in rendered
    assert "api_key=<redacted>" in rendered
    assert "token=<redacted>" in rendered


def test_compact_log_view_has_budget_ceiling_for_large_stdout_artifacts() -> None:
    noisy_lines = [
        f"stdout progress NOISY_FILLER_{index:03d} " + ("x" * 120)
        for index in range(300)
    ]
    noisy_lines.insert(
        150,
        "ERROR worker failed api_key=sk-proj-abcdefghijklmnopqrstuvwxyz123456",
    )
    noisy_lines.extend(["tail compact one", "tail compact two"])
    raw_log = "\n".join(noisy_lines)

    view = logging_utils.compact_log_view(
        raw_log,
        verbose=1,
        signal_limit=2,
        tail_limit=2,
        max_line_chars=120,
    )
    rendered = logging_utils.render_compact_log_view(view)

    assert view["line_count"] == 303
    assert view["signal_count"] == 1
    assert view["omitted_line_count"] >= 299
    assert len(rendered) < 1_200
    assert "ERROR worker failed" in rendered
    assert "api_key=<redacted>" in rendered
    assert "sk-proj" not in rendered
    assert "NOISY_FILLER_000" not in rendered
    assert "tail compact two" in rendered


def test_compact_log_view_quiet_mode_keeps_only_newest_signal_counts() -> None:
    raw_log = "\n".join(
        [
            "ERROR first failure should be skipped in quiet mode",
            *[f"progress {index}" for index in range(80)],
            "ModuleNotFoundError: No module named 'critical_worker'",
            "final benign line",
        ]
    )

    view = logging_utils.compact_log_view(raw_log, verbose=0)
    rendered = logging_utils.render_compact_log_view(view)

    assert view["verbose"] == 0
    assert view["signal_count"] == 2
    assert view["signals"] == [
        {"line": 82, "text": "ModuleNotFoundError: No module named 'critical_worker'"}
    ]
    assert view["tail"] == []
    assert "first failure should be skipped" not in rendered
    assert "progress 0" not in rendered
    assert "omitted:" in rendered


def test_compact_log_view_debug_mode_points_to_artifact_for_large_logs() -> None:
    raw_log = "\n".join(f"raw stdout line {index}" for index in range(200))

    view = logging_utils.compact_log_view(
        raw_log,
        verbose=3,
        tail_limit=0,
        debug_max_lines=20,
    )
    rendered = logging_utils.render_compact_log_view(view)

    assert view["debug_lines"] == []
    assert view["omitted_line_count"] == 200
    assert "full prompt-facing output is capped" in view["note"]
    assert "raw stdout line 0" not in rendered
    assert "raw log artifact" in rendered
