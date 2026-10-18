from __future__ import annotations

import gzip
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest

from agilab.environment import log_storage


@pytest.mark.parametrize("suffix", [".log", ".log.gz"])
def test_log_round_trip_and_legacy_appends(tmp_path, suffix):
    path = tmp_path / ("agilab-run" + suffix)
    with log_storage.open_log(path, "xt") as stream:
        stream.write("réseau 日本語\n")
    log_storage.append_log_text(path, "second line\n")
    assert log_storage.read_log_text(path) == "réseau 日本語\nsecond line\n"
    assert log_storage.tail_log_lines(path, max_lines=1) == ["second line"]
    with pytest.raises(FileExistsError):
        log_storage.open_log(path, "xt")
    assert log_storage.tail_log_lines(path, max_lines=0) == []


def test_flushed_active_gzip_is_readable_without_masking_strict_truncation(tmp_path):
    path = tmp_path / "agilab-active-run.log.gz"
    with log_storage.open_log(path, "xt") as stream:
        stream.write("first stage complete\n")
        stream.flush()
        assert log_storage.tail_log_lines(path) == ["first stage complete"]
        with pytest.raises(EOFError):
            log_storage.read_log_text(path)
        stream.write("second stage complete\n")
        stream.flush()
        assert log_storage.tail_log_lines(path, max_lines=1) == [
            "second stage complete"
        ]
    assert (
        gzip.decompress(path.read_bytes()).decode().replace("\r\n", "\n")
        == "first stage complete\nsecond stage complete\n"
    )


def test_reader_keeps_completed_members_and_the_flushed_final_member(tmp_path):
    path = tmp_path / "agilab-appended-run.log.gz"
    log_storage.append_log_text(path, "completed member\n")
    with log_storage.open_log(path, "at") as stream:
        stream.write("active member\n")
        stream.flush()
        assert (
            log_storage.read_log_text(path, allow_incomplete=True)
            == "completed member\nactive member\n"
        )
    assert log_storage.read_log_text(path) == "completed member\nactive member\n"


def test_callbacks_cannot_interleave_gzip_members(tmp_path):
    path = tmp_path / "agilab-parallel-callbacks.log.gz"
    messages = [f"stage {index}: " + "résultat " * 100 + "\n" for index in range(60)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda message: log_storage.append_log_text(path, message), messages
            )
        )
    assert Counter(log_storage.iter_log_lines(path)) == Counter(
        message.rstrip("\n") for message in messages
    )
    assert path.stat().st_size < sum(len(message.encode()) for message in messages) / 2


def test_exception_finalizes_gzip_and_keeps_written_output(tmp_path):
    path = tmp_path / "agilab-failed-run.log.gz"
    with pytest.raises(RuntimeError, match="worker failed"):
        with log_storage.open_log(path, "xt") as stream:
            stream.write("diagnostic before failure\n")
            raise RuntimeError("worker failed")
    assert (
        gzip.decompress(path.read_bytes()).decode().replace("\r\n", "\n")
        == "diagnostic before failure\n"
    )


@pytest.mark.parametrize("allow_incomplete", [False, True])
def test_live_read_does_not_hide_gzip_checksum_corruption(tmp_path, allow_incomplete):
    path = tmp_path / "agilab-corrupt-run.log.gz"
    data = bytearray(gzip.compress(b"original diagnostic\n"))
    data[-8] ^= 1
    path.write_bytes(data)
    with pytest.raises(OSError):
        log_storage.read_log_text(path, allow_incomplete=allow_incomplete)


def test_split_unicode_and_newlines_survive_bounded_reads(tmp_path, monkeypatch):
    path = tmp_path / "agilab-unicode-run.log.gz"
    path.write_bytes(gzip.compress("réseau\r\n日本語\nlast".encode()))
    monkeypatch.setattr(log_storage, "LOG_CHUNK_BYTES", 1)
    assert log_storage.read_log_text(path) == "réseau\n日本語\nlast"
    assert list(log_storage.iter_log_lines(path)) == ["réseau", "日本語", "last"]


def test_large_line_is_bounded_only_in_the_summary(tmp_path):
    path = tmp_path / "agilab-giant-line.log.gz"
    payload = "ERROR " + "x" * (2 * 1024 * 1024) + "\nlast\n"
    path.write_bytes(gzip.compress(payload.encode()))
    lines = list(log_storage.iter_log_lines(path, max_line_chars=96))
    assert len(lines) == 2
    assert lines[0].startswith("ERROR ")
    assert len(lines[0]) < 160
    assert "full content in log" in lines[0]
    assert lines[1] == "last"
    assert gzip.decompress(path.read_bytes()).decode() == payload


def test_preview_budget_counts_decompressed_bytes(tmp_path):
    path = tmp_path / "agilab-small-archive-large-log.log.gz"
    path.write_bytes(gzip.compress(b"x" * 200_000 + b"\nlatest diagnostic\n"))
    assert path.stat().st_size < 1024
    text, truncated = log_storage.log_tail_bytes(path, max_bytes=1024)
    assert truncated is True
    assert len(text.encode()) <= 1024
    assert text.endswith("\nlatest diagnostic\n")


def test_streaming_short_lines_retain_compression_dictionary(tmp_path):
    path = tmp_path / "agilab-many-short-lines.log.gz"
    line = "INFO worker stage complete; rows=1000; result=ready\n"
    with log_storage.open_log(path, "xt") as stream:
        for _ in range(1000):
            stream.write(line)
            stream.flush()
    assert (
        gzip.decompress(path.read_bytes()).decode().replace("\r\n", "\n") == line * 1000
    )
    assert path.stat().st_size < len(line.encode()) * 1000 * 0.4


def test_empty_log_and_invalid_preview_budgets(tmp_path):
    path = tmp_path / "agilab-empty-run.log.gz"
    with log_storage.open_log(path, "xt"):
        pass
    assert list(log_storage.iter_log_lines(path)) == []
    with pytest.raises(ValueError, match="positive"):
        log_storage.log_tail_bytes(path, max_bytes=0)
    with pytest.raises(ValueError, match="positive"):
        list(log_storage.iter_log_lines(path, max_line_chars=0))


def test_ui_tail_bounds_a_giant_line_without_discarding_the_archive(tmp_path):
    path = tmp_path / "agilab-giant-live-tail.log.gz"
    payload = "x" * 2_000_000 + "\nlatest\n"
    path.write_bytes(gzip.compress(payload.encode()))
    lines = log_storage.tail_log_lines(path, max_lines=2)
    assert len(lines[0]) < 4200
    assert lines[1] == "latest"
    assert gzip.decompress(path.read_bytes()).decode() == payload


def test_live_reader_keeps_prefix_across_every_gzip_member_boundary(tmp_path):
    path = tmp_path / "agilab-interrupted-member.log.gz"
    first = gzip.compress(b"completed member\n")
    second = gzip.compress(b"second diagnostic\n" * 100)
    cuts = [
        0,
        1,
        2,
        3,
        4,
        9,
        10,
        11,
        len(second) // 2,
        len(second) - 8,
        len(second) - 1,
    ]
    for cut in cuts:
        path.write_bytes(first + second[:cut])
        assert log_storage.read_log_text(path, allow_incomplete=True).startswith(
            "completed member\n"
        )
        if cut:
            with pytest.raises((EOFError, gzip.BadGzipFile)):
                log_storage.read_log_text(path)
    path.write_bytes(bytes([0x1F]))
    assert log_storage.read_log_text(path, allow_incomplete=True) == ""
    with pytest.raises(gzip.BadGzipFile):
        log_storage.read_log_text(path)


@pytest.mark.parametrize("tail", [b"x", b"\x1fx"])
def test_live_reader_rejects_malformed_member_headers(tmp_path, tail):
    path = tmp_path / "agilab-malformed-member.log.gz"
    path.write_bytes(gzip.compress(b"completed\n") + tail)
    with pytest.raises(OSError):
        log_storage.read_log_text(path, allow_incomplete=True)


def test_live_reader_rejects_invalid_deflate_data(tmp_path):
    path = tmp_path / "agilab-invalid-deflate.log.gz"
    path.write_bytes(bytes.fromhex("1f8b0800000000000000070000000000000000"))
    with pytest.raises(OSError):
        log_storage.read_log_text(path, allow_incomplete=True)
