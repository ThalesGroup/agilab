"""tests.py – Free-threading lab test suite (pytest + stdlib only)."""
import hashlib
import math
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import free_threading_core as core
import benchmark as bench

TIMEOUT = 30


# ── 1. Independent Mandelbrot oracle ──────────────────────────────────────────

def _oracle(w, h, n):
    """Scalar reference: c=(-2+3x/(w-1), -1.2+2.4y/(h-1)); iterate z=z²+c."""
    out = []
    for y in range(h):
        for x in range(w):
            cr = -2.0 + 3.0 * x / (w - 1)
            ci = -1.2 + 2.4 * y / (h - 1)
            zr, zi = 0.0, 0.0
            count = 0
            while count < n and zr * zr + zi * zi <= 4.0:
                zr, zi = zr * zr - zi * zi + cr, 2.0 * zr * zi + ci
                count += 1
            out.append(count)
    return out


@pytest.mark.parametrize("w,h,n", [(9, 7, 30), (16, 11, 40)])
def test_reference_matches_oracle(w, h, n):
    expected = _oracle(w, h, n)
    got = core.reference_image(w, h, n)
    assert len(got) == w * h
    assert got == expected, f"Mismatch at {[(i, e, g) for i, (e, g) in enumerate(zip(expected, got)) if e != g][:5]}"


# ── 2. Input validation ───────────────────────────────────────────────────────

@pytest.mark.parametrize("w,h,n,exc", [
    (0, 7, 30, ValueError), (-1, 7, 30, ValueError),
    (9, 0, 30, ValueError), (9, -3, 30, ValueError),
    (9, 7, 0, ValueError), (9, 7, -1, ValueError),
    (True, 7, 30, TypeError), (9, True, 30, TypeError), (9, 7, True, TypeError),
    (1.5, 7, 30, TypeError), (9, 2.5, 30, TypeError), (9, 7, 3.0, TypeError),
])
def test_reference_rejects_bad(w, h, n, exc):
    with pytest.raises(exc):
        core.reference_image(w, h, n)


@pytest.mark.parametrize("val,exc", [
    (True, TypeError), (-1, ValueError), (301, ValueError),
    (1.5, TypeError), (float("nan"), TypeError), (float("inf"), TypeError),
])
def test_digest_rejects_bad(val, exc):
    with pytest.raises(exc):
        core.image_digest([val])


# ── 3. Tile geometry ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("w,h", [(9, 7), (16, 11), (2, 3), (4, 5)])
def test_tiles_coverage_and_uniqueness(w, h):
    tiles = core.make_tiles(w, h)
    ids = [t["tile_id"] for t in tiles]
    assert len(ids) == len(set(ids)), "tile_ids not unique"
    covered = []
    for t in tiles:
        assert t["row_stop"] - t["row_start"] <= 2, f"tile {t['tile_id']} spans >2 rows"
        assert t["row_start"] >= 0 and t["row_stop"] <= h
        covered.extend(range(t["row_start"], t["row_stop"]))
    assert sorted(covered) == list(range(h)), "rows not exactly covered"


# ── 4. SHA-256 of bundled source files ────────────────────────────────────────

def _sha256(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_source_sha256():
    src = ROOT / "source" / "original.ipynb"
    assert _sha256(src) == "ea34493fc5caaa6062dfa9b4210b1d0620f205cce4cc117c9293155f75a1c911"


def test_engine_sha256():
    eng = ROOT / "agilab_pool.py"
    assert _sha256(eng) == "305ba174348e92376b08be149b488fc41983de04c5b2564695493769fc21f066"


# ── 5. run_benchmark rejects invalid input before subprocess ──────────────────

def _no_popen(*a, **kw):
    raise AssertionError("subprocess.Popen must NOT be called for invalid input")


@pytest.mark.parametrize("w,h,n,workers,repeats", [
    (0, 24, 40, 2, 1), (-1, 24, 40, 2, 1),
    (32, 0, 40, 2, 1), (32, -2, 40, 2, 1),
    (32, 24, 0, 2, 1), (32, 24, -5, 2, 1),
    (32, 24, 40, 0, 1), (32, 24, 40, -1, 1),
    (32, 24, 40, True, 1), (32, 24, 40, 1.5, 1),
    (32, 24, 40, 2, 0), (32, 24, 40, 2, -1),
    (32, 24, 40, 2, True), (32, 24, 40, 2, float("nan")),
    (True, 24, 40, 2, 1), (32, True, 40, 2, 1), (32, 24, True, 2, 1),
    (32, 24, 40, 2, float("inf")),
])
def test_benchmark_rejects_invalid(monkeypatch, w, h, n, workers, repeats):
    monkeypatch.setattr(bench.subprocess, "Popen", _no_popen)
    with pytest.raises((ValueError, TypeError)):
        bench.run_benchmark(w, h, n, workers, repeats)


# ── 6. Real smoke test (skip if no free-threading interpreter) ───────────────

def test_real_smoke():
    try:
        interp = bench.find_free_threading_python()
    except RuntimeError as e:
        pytest.skip(f"No free-threading Python available: {e}")

    w, h, n, repeats = 32, 24, 40, 1
    workers = min(2, bench.effective_cpus()["effective_cpus"])
    result = bench.run_benchmark(w, h, n, workers, repeats)

    # result is a dict
    assert isinstance(result, dict)

    # For repeats=1, len(runs)=6, len(summary)=6
    assert len(result["runs"]) == 6
    assert len(result["summary"]) == 6

    # Digest is a real SHA-256 hex string
    assert len(result["digest"]) == 64
    int(result["digest"], 16)

    # Independent oracle
    expected = _oracle(w, h, n)

    # Per-run: each run's counts must match the oracle image
    for run in result["runs"]:
        records = sorted(run["records"], key=lambda r: r["row_start"])
        all_counts = []
        for rec in records:
            all_counts.extend(rec["counts"])
        assert all_counts == expected

    # Digest consistency: oracle digest == run digest == result digest
    assert core.image_digest(expected) == result["digest"]
    for run in result["runs"]:
        assert run["digest"] == result["digest"]

    # before == after for each run
    for run in result["runs"]:
        assert run["before"] == run["after"]

    # free_threaded_build is True
    for run in result["runs"]:
        assert run["before"]["free_threaded_build"] is True
        assert run["after"]["free_threaded_build"] is True

    # gil_enabled matches mode
    for run in result["runs"]:
        expected_gil = run["mode"] != "gil_off_threads"
        assert run["before"]["gil_enabled"] == expected_gil
        assert run["after"]["gil_enabled"] == expected_gil

    # version matches result.python_build
    for run in result["runs"]:
        assert run["before"]["version"] == result["python_build"]
        assert run["after"]["version"] == result["python_build"]

    # Per record: exact keys gil_before, gil_after, runtime_before, runtime_after, pid, thread_id
    for run in result["runs"]:
        for rec in run["records"]:
            assert rec["gil_before"] is run["before"]["gil_enabled"]
            assert rec["gil_after"] is run["before"]["gil_enabled"]
            assert rec["runtime_before"] == rec["runtime_after"] == run["before"]

    # Worker identity: 1 <= actual <= pool_width <= workers
    for run in result["runs"]:
        actual = run["actual_workers"]
        pool = run["pool_width"]
        assert 1 <= actual <= pool <= run["workers"]

    # actual_workers == len(distinct (pid, thread_id))
    for run in result["runs"]:
        distinct = set()
        for rec in run["records"]:
            distinct.add((rec["pid"], rec["thread_id"]))
        assert run["actual_workers"] == len(distinct)

    # Summary: groups by mode/role; exact statistics.median wall/engine from raw group
    import statistics
    for s in result["summary"]:
        mode = s["mode"]
        role = s["role"]
        group = [r for r in result["runs"] if r["mode"] == mode and r["role"] == role]
        assert len(group) > 0
        wall_vals = [r["wall_seconds"] for r in group]
        eng_vals = [r["engine_seconds"] for r in group]
        assert s["wall_seconds"] == statistics.median(wall_vals)
        assert s["engine_seconds"] == statistics.median(eng_vals)

        # speedup = matching mode baseline median wall / group median wall
        baseline_group = [r for r in result["runs"] if r["mode"] == mode and r["role"] == "baseline"]
        if baseline_group:
            baseline_wall = statistics.median([r["wall_seconds"] for r in baseline_group])
            assert s["speedup"] == pytest.approx(baseline_wall / s["wall_seconds"], rel=1e-9)
            baseline_eng = statistics.median([r["engine_seconds"] for r in baseline_group])
            assert s["engine_speedup"] == pytest.approx(baseline_eng / s["engine_seconds"], rel=1e-9)

    # No forbidden fields in summary
    for s in result["summary"]:
        assert "median" not in s
        assert "ratio" not in s
        assert "serial_time" not in s

    # No forbidden fields in raw runs
    for run in result["runs"]:
        assert "counts" not in run
        assert "gil_free" not in run
        assert "elapsed" not in run