import logging

from agi_env.agi_logger import AgiLogger, LogFormatter


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
