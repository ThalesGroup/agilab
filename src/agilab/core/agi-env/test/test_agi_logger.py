import logging
from pathlib import Path

import agi_env.agi_logger as agi_logger_module
from agi_env.agi_logger import (
    AgiLogger,
    ClassNameFilter,
    LogFormatter,
    MaxLevelFilter,
)


class _RecursiveMessage:
    def __str__(self) -> str:
        raise RecursionError("boom")


def test_log_formatter_handles_recursive_message():
    formatter = LogFormatter(verbose=0)
    record = logging.makeLogRecord(
        {
            "name": "agilab.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "pathname": __file__,
            "lineno": 1,
            "msg": _RecursiveMessage(),
            "args": (),
            "funcName": "test_log_formatter_handles_recursive_message",
        }
    )
    rendered = formatter.format(record)
    plain = AgiLogger.decolorize(rendered)
    assert "<log-message-recursion type=_RecursiveMessage>" in plain


class _BrokenMessage:
    def __str__(self) -> str:
        raise ValueError("bad message")


class _DemoEmitter:
    def emit(self):
        record = logging.makeLogRecord(
            {
                "name": "agilab.test",
                "levelno": logging.INFO,
                "levelname": "INFO",
                "pathname": __file__,
                "lineno": 1,
                "msg": "hello",
                "args": (),
                "funcName": "emit",
                "module": Path(__file__).stem,
            }
        )
        assert ClassNameFilter().filter(record) is True
        return record.classname


def _emit_without_self():
    record = logging.makeLogRecord(
        {
            "name": "agilab.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "pathname": __file__,
            "lineno": 1,
            "msg": "hello",
            "args": (),
            "funcName": "_emit_without_self",
            "module": "module_name",
        }
    )
    assert ClassNameFilter().filter(record) is True
    return record.classname


def test_class_name_filter_uses_self_class_name():
    assert _DemoEmitter().emit() == "_DemoEmitter"


def test_class_name_filter_falls_back_to_module_name_without_self():
    assert _emit_without_self() == "module_name"


def test_class_name_filter_uses_no_class_when_frame_not_found():
    record = logging.makeLogRecord(
        {
            "name": "agilab.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "pathname": "/tmp/other_module.py",
            "lineno": 1,
            "msg": "hello",
            "args": (),
            "funcName": "missing_func",
            "module": "other_module",
        }
    )

    assert ClassNameFilter().filter(record) is True
    assert record.classname == "<no-class>"


def test_class_name_filter_handles_frame_lookup_exception(monkeypatch):
    record = logging.makeLogRecord(
        {
            "name": "agilab.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "pathname": __file__,
            "lineno": 1,
            "msg": "hello",
            "args": (),
            "funcName": "boom",
            "module": "other_module",
        }
    )

    monkeypatch.setattr(agi_logger_module.sys, "_getframe", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))

    assert ClassNameFilter().filter(record) is True
    assert record.classname == "<no-class>"


def test_max_level_filter_blocks_higher_levels():
    info_record = logging.makeLogRecord({"levelno": logging.INFO})
    error_record = logging.makeLogRecord({"levelno": logging.ERROR})
    filt = MaxLevelFilter(logging.WARNING)

    assert filt.filter(info_record) is True
    assert filt.filter(error_record) is False


def test_log_formatter_suppresses_build_noise_when_quiet():
    formatter = LogFormatter(verbose=0)
    record = logging.makeLogRecord(
        {
            "name": "agilab.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "pathname": "/tmp/build.py",
            "lineno": 1,
            "msg": "build output",
            "args": (),
            "funcName": "run",
        }
    )

    assert formatter.format(record) == ""


def test_log_formatter_uses_unknown_venv_when_prefix_missing(monkeypatch):
    formatter = LogFormatter(verbose=0)
    record = logging.makeLogRecord(
        {
            "name": "agilab.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "pathname": __file__,
            "lineno": 1,
            "msg": "hello",
            "args": (),
            "funcName": "emit",
        }
    )

    monkeypatch.setattr(agi_logger_module.sys, "prefix", "")

    plain = AgiLogger.decolorize(formatter.format(record))
    assert "<unknown>" in plain


def test_log_formatter_keeps_build_noise_when_verbose():
    formatter = LogFormatter(verbose=2)
    record = logging.makeLogRecord(
        {
            "name": "agilab.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "pathname": "/tmp/build.py",
            "lineno": 1,
            "msg": "build output",
            "args": (),
            "funcName": "run",
        }
    )

    plain = AgiLogger.decolorize(formatter.format(record))
    assert "build.py" in plain
    assert "build output" in plain


def test_log_formatter_falls_back_to_module_filename_when_basename_breaks(monkeypatch):
    formatter = LogFormatter(verbose=0)
    record = logging.makeLogRecord(
        {
            "name": "agilab.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "pathname": "/tmp/not-build.py",
            "lineno": 1,
            "msg": "build output",
            "args": (),
            "funcName": "run",
            "module": "build",
        }
    )

    monkeypatch.setattr(
        agi_logger_module.os.path,
        "basename",
        lambda *_: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert formatter.format(record) == ""


def test_log_formatter_handles_general_message_format_error():
    formatter = LogFormatter(verbose=0)
    record = logging.makeLogRecord(
        {
            "name": "agilab.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "pathname": __file__,
            "lineno": 1,
            "msg": _BrokenMessage(),
            "args": (),
            "funcName": "test_log_formatter_handles_general_message_format_error",
        }
    )

    plain = AgiLogger.decolorize(formatter.format(record))
    assert "<log-message-format-error type=_BrokenMessage error=bad message>" in plain


def test_log_formatter_returns_message_only_for_subprocess_records():
    formatter = LogFormatter(verbose=0)
    record = logging.makeLogRecord(
        {
            "name": "agilab.test",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "pathname": __file__,
            "lineno": 1,
            "msg": "subprocess output",
            "args": (),
            "funcName": "worker",
            "subprocess": True,
        }
    )

    plain = AgiLogger.decolorize(formatter.format(record))
    assert plain == "subprocess output"


def test_agi_logger_configure_and_set_level():
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    original_configured = AgiLogger._configured
    original_base_name = AgiLogger._base_name
    try:
        logger = AgiLogger.configure(verbose=1, base_name="demo-base", force=True)
        assert logger.name == "demo-base"
        assert AgiLogger.get_logger().name == "demo-base"

        AgiLogger.set_level(logging.DEBUG)
        assert logging.getLogger().level == logging.DEBUG
    finally:
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        for handler in original_handlers:
            root.addHandler(handler)
        root.setLevel(original_level)
        AgiLogger._configured = original_configured
        AgiLogger._base_name = original_base_name


def test_agi_logger_configure_reuses_existing_logger_without_force():
    original_configured = AgiLogger._configured
    original_base_name = AgiLogger._base_name
    try:
        AgiLogger._configured = True
        AgiLogger._base_name = "existing-base"

        logger = AgiLogger.configure()

        assert logger.name == "existing-base"
    finally:
        AgiLogger._configured = original_configured
        AgiLogger._base_name = original_base_name


def test_agi_logger_configure_defaults_verbose_to_zero():
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    original_configured = AgiLogger._configured
    original_base_name = AgiLogger._base_name
    try:
        AgiLogger.configure(verbose=None, base_name="verbose-default", force=True)

        assert AgiLogger.verbose == 0
        assert AgiLogger.get_logger().name == "verbose-default"
    finally:
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        for handler in original_handlers:
            root.addHandler(handler)
        root.setLevel(original_level)
        AgiLogger._configured = original_configured
        AgiLogger._base_name = original_base_name


def test_agi_logger_configure_keeps_existing_base_name_when_none_provided():
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    original_configured = AgiLogger._configured
    original_base_name = AgiLogger._base_name
    try:
        AgiLogger._base_name = "kept-base"
        AgiLogger.configure(verbose=1, force=True)

        assert AgiLogger.get_logger().name == "kept-base"
    finally:
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        for handler in original_handlers:
            root.addHandler(handler)
        root.setLevel(original_level)
        AgiLogger._configured = original_configured
        AgiLogger._base_name = original_base_name
