"""RTX free-threading parameter, interpreter and deterministic-image contracts."""
import importlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import zlib

import pytest


@pytest.fixture
def core(monkeypatch):
    root = Path(__file__).resolve().parents[1] / "src/agilab/demos/resources/free_threading_demo_rtx"
    pool = importlib.import_module("agilab.demos.resources.free_threading_demo_rtx.agilab_pool")
    monkeypatch.setitem(sys.modules, "agilab_pool", pool)
    spec = importlib.util.spec_from_file_location("_rtx_core_contract", root / "free_threading_core.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("field", ["width", "height", "iterations", "workers", "repeats", "tile_rows"])
@pytest.mark.parametrize("value", [True, 1.5, 0, 100000])
def test_integer_limits_reject_type_confusion_and_resource_overflow(core, field, value):
    params = dict(width=2, height=2, iterations=2, workers=1)
    params[field] = value
    with pytest.raises(ValueError, match=field):
        core.validate_params(**params)


@pytest.mark.parametrize("field", ["child_timeout", "total_timeout"])
@pytest.mark.parametrize("value", [False, "10", float("nan"), float("inf"), 0, 100000])
def test_timeout_limits_reject_nonfinite_and_unbounded_requests(core, field, value):
    with pytest.raises(ValueError, match=field):
        core.validate_params(2, 2, 2, 1, **{field: value})


@pytest.mark.parametrize("mode", [None, False, 1, "gil_off_threads", "unknown"])
def test_unrecognized_execution_mode_is_rejected(core, mode):
    with pytest.raises(ValueError, match="mode"):
        core.validate_mode(mode)


def test_tile_reduction_reorders_rows_without_losing_pixels(core):
    records = [
        dict(row_start=1, row_end=2, rows=1, counts=[3, 4]),
        dict(row_start=0, row_end=1, rows=1, counts=[1, 2]),
    ]
    result = core.reduce_tiles(records, 2, 2)
    assert result["pixels"] == [1, 2, 3, 4]
    assert result["digest"] == core.digest_of_counts([1, 2, 3, 4])
    with pytest.raises(ValueError, match="exactly once"):
        core.reduce_tiles(records[:1], 2, 2)
    with pytest.raises(ValueError, match="exactly once"):
        core.reduce_tiles(records + records, 2, 2)
    records[0]["counts"] = [3]
    with pytest.raises(ValueError, match="length mismatch"):
        core.reduce_tiles(records, 2, 2)


@pytest.mark.parametrize("status,info", [
    (2, {}), (0, {"ok": False, "free_threaded_build": True}),
    (0, {"ok": True, "free_threaded_build": False}),
])
def test_interpreter_probe_refuses_failed_or_standard_runtime(core, monkeypatch, status, info):
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=status, stdout=json.dumps(info), stderr="probe failed")
    monkeypatch.setattr(core, "subprocess", SimpleNamespace(run=run))
    with pytest.raises(core.FreeThreadingInterpreterError):
        core.probe_free_threading_python("/synthetic/python")
    assert calls[0][0][0] == "/synthetic/python"
    assert calls[0][1]["timeout"] == 30
    assert calls[0][1]["check"] is False


@pytest.mark.parametrize("source", ["environment", "path", "missing", "not-file", "not-executable"])
def test_interpreter_resolution_preserves_explicit_selection_and_refuses_fallback(
    core, monkeypatch, source,
):
    calls = []
    candidate = "/synthetic/python"
    environment = {core.FREE_THREADING_PYTHON_ENV: candidate} if source != "path" else {}
    if source == "missing":
        environment = {}
    monkeypatch.setattr(core, "os", SimpleNamespace(
        environ=environment, path=SimpleNamespace(isfile=lambda value: source != "not-file"),
        access=lambda path, mode: source != "not-executable", X_OK=1))
    def which(name):
        calls.append(name)
        return candidate if source == "path" else None
    monkeypatch.setattr(core, "shutil", SimpleNamespace(which=which))
    probed = []
    monkeypatch.setattr(core, "probe_free_threading_python",
                        lambda path: probed.append(path) or {"ok": True})
    if source in ("environment", "path"):
        assert core.resolve_free_threading_python() == (candidate, {"ok": True})
        assert probed == [candidate]
        assert calls == ([] if source == "environment" else ["python3.14t"])
    else:
        with pytest.raises(core.FreeThreadingInterpreterError):
            core.resolve_free_threading_python()
        assert not probed


def test_preview_png_has_valid_chunks_and_deterministic_interior_pixels(core):
    image = core.render_preview_png([1, 2, 1, 2], 2, 2, 2)
    assert image == core.render_preview_png([1, 2, 1, 2], 2, 2, 2)
    assert image[:8] == b"\x89PNG\r\n\x1a\n"
    chunks, cursor = {}, 8
    while cursor < len(image):
        size = struct.unpack(">I", image[cursor:cursor + 4])[0]
        tag = image[cursor + 4:cursor + 8]
        data = image[cursor + 8:cursor + 8 + size]
        crc = struct.unpack(">I", image[cursor + 8 + size:cursor + 12 + size])[0]
        assert crc == zlib.crc32(tag + data)
        chunks[tag] = data
        cursor += size + 12
    assert cursor == len(image)
    assert struct.unpack(">IIBBBBB", chunks[b"IHDR"]) == (2, 2, 8, 2, 0, 0, 0)
    raw = zlib.decompress(chunks[b"IDAT"])
    assert len(raw) == 14 and raw[0] == raw[7] == 0
    assert raw[4:7] == raw[11:14] == bytes((8, 10, 14))
    assert raw[1:4] == raw[8:11] != raw[4:7]
