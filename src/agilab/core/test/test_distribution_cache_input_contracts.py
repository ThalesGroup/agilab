"""Cache input discovery and fingerprint failure contracts."""

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_node.agi_dispatcher import distribution_cache_support as cache


@pytest.mark.parametrize("payload_kind", ["mapping", "object", "model"])
def test_input_discovery_normalizes_nested_declared_inputs(tmp_path, payload_kind):
    payload = {
        "input_files": {
            "primary": tmp_path / "a",
            "others": [
                str(tmp_path / "b"),
                "",
                "https://example.invalid/data",
                b"ignored",
            ],
        },
        "nested": {"training_input_path": tmp_path / "c"},
        "data_out": tmp_path / "not-input",
    }
    args = payload if payload_kind == "mapping" else SimpleNamespace(**payload)
    if payload_kind == "model":
        args = SimpleNamespace(model_dump=lambda mode: payload)
    worker = SimpleNamespace(
        args=args, distribution_cache_inputs=lambda: [tmp_path / "a", tmp_path / "d"]
    )
    assert cache._discover_input_paths(worker) == [tmp_path / name for name in "abcd"]


@pytest.mark.parametrize(
    "worker,error",
    [
        (SimpleNamespace(distribution_cache_inputs_mode="unknown"), ValueError),
        (SimpleNamespace(distribution_cache_inputs_mode="replace"), TypeError),
        (SimpleNamespace(distribution_cache_inputs=123), TypeError),
    ],
)
def test_invalid_input_contract_is_rejected(worker, error):
    with pytest.raises(error):
        cache._discover_input_paths(worker)


def test_replace_contract_ignores_inferred_inputs(tmp_path):
    worker = SimpleNamespace(
        args={"data_in": tmp_path / "inferred"},
        distribution_cache_inputs_mode="replace",
        distribution_cache_inputs=lambda: tmp_path / "explicit",
    )
    assert cache._discover_input_paths(worker) == [tmp_path / "explicit"]
    assert cache._discover_input_paths(SimpleNamespace(args=123)) == []


def test_async_input_hook_is_rejected_without_running():
    class Awaitable:
        def __await__(self):
            raise AssertionError("input hook must not be awaited")
            yield

    with pytest.raises(TypeError, match="synchronous"):
        cache._discover_input_paths(
            SimpleNamespace(distribution_cache_inputs=lambda: Awaitable())
        )


def test_directory_fingerprint_captures_empty_directories_and_content(tmp_path):
    root = tmp_path / "input"
    (root / "empty").mkdir(parents=True)
    (root / "data").write_bytes(b"abc")
    fingerprint = cache._path_fingerprint(root)
    assert fingerprint == {
        "path": root.as_posix(),
        "kind": "directory",
        "entries": [
            {
                "path": "data",
                "kind": "file",
                "size": 3,
                "sha256": hashlib.sha256(b"abc").hexdigest(),
            },
            {"path": "empty", "kind": "directory"},
        ],
    }
    (root / "data").write_bytes(b"abd")
    assert cache._path_fingerprint(root) != fingerprint
    assert cache._path_fingerprint(root / "missing")["kind"] == "missing"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes require POSIX")
def test_nonregular_input_is_fingerprinted_without_opening_it(tmp_path):
    fifo = tmp_path / "input.pipe"
    os.mkfifo(fifo)
    standalone = cache._path_fingerprint(fifo)
    nested = cache._path_fingerprint(tmp_path)["entries"][0]
    assert standalone["kind"] == nested["kind"] == "other"
    assert standalone["size"] == nested["size"] == fifo.stat().st_size
    assert standalone["mtime_ns"] == nested["mtime_ns"] == fifo.stat().st_mtime_ns


def test_mutating_input_is_rejected_during_fingerprint(tmp_path, monkeypatch):
    source = tmp_path / "input"
    source.write_bytes(b"before")
    original_open = Path.open

    class MutatingReader:
        def __enter__(self):
            self.stream = original_open(source, "rb")
            return self

        def read(self, size):
            value = self.stream.read(size)
            if value:
                with original_open(source, "ab") as writer:
                    writer.write(b"changed")
                self.stream.seek(0, 2)
            return value

        def __exit__(self, *args):
            self.stream.close()

    monkeypatch.setattr(
        Path,
        "open",
        lambda path, *args, **kwargs: MutatingReader()
        if path == source and args == ("rb",)
        else original_open(path, *args, **kwargs),
    )
    with pytest.raises(RuntimeError, match="changed while being fingerprinted"):
        cache._file_sha256(source)


def test_bytecode_fallback_changes_when_planner_behavior_changes(monkeypatch):
    monkeypatch.setattr(
        cache,
        "inspect",
        SimpleNamespace(
            getsource=lambda obj: (_ for _ in ()).throw(OSError("no source")),
            getsourcefile=lambda obj: None,
        ),
    )
    namespace = {}
    exec(
        "def plan():\n return (lambda: 1), frozenset({2,3}), b'abc', ..., 1j", namespace
    )
    first = cache._planner_fingerprint(
        SimpleNamespace(build_distribution=namespace["plan"])
    )
    exec(
        "def plan():\n return (lambda: 2), frozenset({2,3}), b'abc', ..., 1j", namespace
    )
    second = cache._planner_fingerprint(
        SimpleNamespace(build_distribution=namespace["plan"])
    )
    assert first["sha256"] != second["sha256"]
    assert first["callable"] == second["callable"]


def test_constant_encoding_is_stable_for_nested_unordered_values():
    value = (frozenset({3, 1, 2}), b"abc", Ellipsis, None, 1j, object())
    encoded = cache._stable_code_constant(value)
    assert encoded["kind"] == "tuple"
    assert encoded["items"][0] == {
        "kind": "frozenset",
        "items": [
            {"kind": "int", "value": "1"},
            {"kind": "int", "value": "2"},
            {"kind": "int", "value": "3"},
        ],
    }
    assert encoded["items"][1:] == [
        {"kind": "bytes", "hex": "616263"},
        {"kind": "ellipsis"},
        {"kind": "NoneType", "value": "None"},
        {"kind": "complex", "value": "1j"},
        {"kind": "object"},
    ]
