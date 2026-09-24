"""Unit tests for the free-threading lab kernel.

Runs under pytest or standalone:  python tests.py
"""
from __future__ import annotations

import os

import free_threading_core as core


def test_reference_matches_original_loop():
    """The kernel must reproduce the original notebook's exact loop."""
    width, height, iterations = 5, 3, 10
    expected = []
    for y in range(height):
        cy = -1.2 + 2.4 * y / (height - 1)
        for x in range(width):
            cx = -2.0 + 3.0 * x / (width - 1)
            z = 0j
            c = complex(cx, cy)
            count = 0
            while count < iterations and z.real * z.real + z.imag * z.imag <= 4.0:
                z = z * z + c
                count += 1
            expected.append(count)
    assert core.reference_image(width, height, iterations) == expected


def test_tiles_cover_image_exactly_once():
    for tile_rows in range(2, 5):
        tiles = core.make_tiles(17, tile_rows)
        covered = [row for tile in tiles for row in range(tile[0], tile[1])]
        assert covered == list(range(17))


def test_digest_is_deterministic_and_content_sensitive():
    a = core.digest_of_counts([1, 2, 3])
    b = core.digest_of_counts([1, 2, 3])
    c = core.digest_of_counts([1, 2, 4])
    assert a == b
    assert a != c
    assert len(a) == 64


def test_validation_rejects_bad_input():
    good = dict(width=16, height=16, iterations=16, workers=2)
    assert core.validate_params(**good)["width"] == 16
    for bad in (
        dict(width=True, height=16, iterations=16, workers=2),
        dict(width=0, height=16, iterations=16, workers=2),
        dict(width=-1, height=16, iterations=16, workers=2),
        dict(width=10**9, height=16, iterations=16, workers=2),
        dict(width=float("nan"), height=16, iterations=16, workers=2),
        dict(width=16, height=16, iterations=16, workers=0),
        dict(width=16, height=16, iterations=16, workers=9),
        dict(width=16, height=16, iterations=16, workers=1, repeats=0),
        dict(width=16, height=16, iterations=16, workers=1, repeats=4),
        dict(width=16, height=16, iterations=16, workers=1, tile_rows=1),
        dict(width=16, height=16, iterations=16, workers=1, tile_rows=5),
    ):
        try:
            core.validate_params(**bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"validate_params accepted {bad}")
    for bad_mode in ("threads", "GIL-off-threads", "", 3):
        try:
            core.validate_mode(bad_mode)
        except ValueError:
            pass
        else:
            raise AssertionError(f"validate_mode accepted {bad_mode!r}")


def test_child_env_is_private_per_mode():
    env = dict(os.environ)
    env["AGILAB_POOL_EXECUTOR"] = "polluter"
    env["PYTHONPATH"] = "/polluted"
    env["PYTHON_GIL"] = "1"
    saved = os.environ
    os.environ = env
    try:
        off = core.child_env(core.MODE_GIL_OFF_THREADS)
        on = core.child_env(core.MODE_GIL_ON_PROCESSES)
        assert off["PYTHON_GIL"] == "0"
        assert on["PYTHON_GIL"] == "1"
        for one in (off, on):
            assert "AGILAB_POOL_EXECUTOR" not in one
            assert "PYTHONPATH" not in one
            assert one["PYTHONHASHSEED"] == "0"
    finally:
        os.environ = saved


def test_child_argv_carries_mode_flags():
    params = core.validate_params(16, 16, 16, 2)
    argv = core.child_argv("/py", params, core.MODE_GIL_OFF_THREADS, 2, 1)
    assert argv[:3] == ["/py", "-X", "gil=0"]
    assert argv[3] == "-m" and argv[4] == "free_threading_core"
    assert "--mode" in argv and core.MODE_GIL_OFF_THREADS in argv
    argv_on = core.child_argv("/py", params, core.MODE_GIL_ON_THREADS, 2, 1)
    assert argv_on[2] == "gil=1"


def test_reduce_tiles_rejects_bad_coverage():
    params = core.validate_params(4, 4, 4, 1)
    good = [
        core.compute_tile(params, (0, 2)),
        core.compute_tile(params, (2, 4)),
    ]
    reduced = core.reduce_tiles(good, 4, 4)
    assert reduced["digest"] == core.digest_of_counts(
        core.reference_image(4, 4, 4)
    )
    try:
        core.reduce_tiles(good[:1], 4, 4)
    except ValueError:
        pass
    else:
        raise AssertionError("reduce_tiles accepted missing coverage")


def test_run_case_matches_serial_reference():
    params = core.validate_params(48, 32, 20, 2, repeats=1, tile_rows=4)
    for mode in (core.MODE_GIL_ON_THREADS, core.MODE_GIL_OFF_THREADS):
        report = core.run_case(params, mode, 2, 1)
        assert report["digest"] == core.digest_of_counts(
            core.reference_image(48, 32, 20)
        )
        assert report["same_as_serial_reference"] is True
        assert report["repeats"][0]["engine_width"] in (1, 2)


def test_preview_png_is_valid_png_header():
    pixels = core.reference_image(8, 4, 8)
    png = core.render_preview_png(pixels, 8, 4, 8)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert b"IHDR" in png and b"IEND" in png


def test_cpu_allowance_is_bounded():
    allowance = core.effective_cpu_allowance()
    assert 1 <= allowance <= core.MAX_WORKERS


def test_gil_state_reports_build_facts():
    state = core.gil_state()
    assert state["version"]
    assert isinstance(state["py_gil_disabled_build"], bool)


def _run_all() -> int:
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 - test harness
                failures += 1
                print(f"FAIL {name}: {type(exc).__name__}: {exc}")
            else:
                print(f"ok   {name}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
