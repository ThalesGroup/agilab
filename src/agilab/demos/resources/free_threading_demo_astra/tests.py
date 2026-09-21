"""Run using the existing normal UI Python: python -B tests.py."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import benchmark as bench
import free_threading_core as core


def original_reference(width, height, iterations):
    # Independent transcription of the source notebook, not a call to the kernel.
    pixels = []
    for y in range(height):
        cy = -1.2 + 2.4 * y / (height - 1)
        for x in range(width):
            cx = -2.0 + 3.0 * x / (width - 1)
            z = 0j
            c = complex(cx, cy)
            count = 0
            while count < iterations and z.real*z.real + z.imag*z.imag <= 4.0:
                z = z*z + c
                count += 1
            pixels.append(count)
    return pixels


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workers = min(2, bench.effective_cpus()["effective_cpus"])
        cls.samples = []
        for dimensions in ((7, 5, 25), (20, 13, 60), (48, 32, 80)):
            for mode in core.MODES:
                cls.samples.append((dimensions, mode, bench.run_case(*dimensions, cls.workers, mode)))

    def test_exact_original_counts_all_backends_and_shapes(self):
        for dimensions, mode, result in self.samples:
            with self.subTest(dimensions=dimensions, mode=mode):
                expected = original_reference(*dimensions)
                counts = core.reduce_tiles(result["records"], core.tile_plan(*dimensions))
                self.assertEqual(expected, counts)
                self.assertEqual(result["digest"], core.image_digest(expected))
                self.assertEqual(result["before"], result["after"])
                self.assertTrue(result["before"]["free_threaded_build"])
                self.assertEqual(result["before"]["gil_enabled"], bool(core.MODES[mode][0]))

    def test_mono_api_uses_same_reduction(self):
        source = ("import json,free_threading_core as c; "
                  "print(json.dumps(c.execute(7,5,25,1,'gil_on_threads',mono=True)))")
        env = bench.child_environment("gil_on_threads", 1)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parent)
        output, _ = bench._communicate([bench.interpreter(), "-B", "-X", "gil=1", "-c", source],
                                       "", env, 10)
        result = json.loads(output)
        self.assertEqual(core.reduce_tiles(result["records"], core.tile_plan(7, 5, 25)),
                         original_reference(7, 5, 25))
        self.assertEqual(result["backend"], "mono")

    def test_incomplete_duplicate_mismatched_results_rejected(self):
        dimensions, mode, result = self.samples[-1]
        mutations = [lambda r: r["records"].pop(),
                     lambda r: r["records"].append(r["records"][0]),
                     lambda r: r["records"][0].update(row_start=999),
                     lambda r: r.update(digest="0" * 64),
                     lambda r: r.update(mode="gil_off_threads"),
                     lambda r: r["tile_plan"].reverse(),
                     lambda r: r["records"][0]["counts"].pop(),
                     lambda r: r["after"].update(gil_enabled=False),
                     lambda r: r["records"][0].update(gil_enabled=False)]
        for mutation in mutations:
            bad = copy.deepcopy(result)
            mutation(bad)
            with self.subTest(mutation=mutation), self.assertRaises((ValueError, RuntimeError)):
                bench.validate_result(bad, *dimensions, self.workers, mode)

    def test_six_cases_medians_and_parent_state_unchanged(self):
        cwd, env = Path.cwd(), dict(os.environ)
        report = bench.run_benchmark(12, 8, 20, workers=self.workers, repeats=1)
        self.assertEqual(len(report["runs"]), 6)
        self.assertEqual(len({r["digest"] for r in report["runs"]}), 1)
        self.assertEqual({r["role"] for r in report["runs"]}, {"baseline", "scaled"})
        for row in report["summary"]:
            if row["role"] == "baseline":
                self.assertEqual(row["speedup"], 1)
                self.assertEqual(row["engine_speedup"], 1)
        self.assertEqual(Path.cwd(), cwd)
        self.assertEqual(dict(os.environ), env)


class GuardTests(unittest.TestCase):
    def test_invalid_inputs_never_launch(self):
        invalid = (True, False, 0, -1, float("nan"), float("inf"), "2", 2.5, None)
        with patch.object(bench.subprocess, "Popen", side_effect=AssertionError("launched")):
            for name in ("width", "height", "iterations", "workers", "repeats"):
                for value in invalid:
                    values = dict(width=12, height=8, iterations=20, workers=1, repeats=1)
                    values[name] = value
                    with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                        bench.run_benchmark(**values)
            for mode in ("unknown", None, True, [], {}):
                with self.assertRaises(ValueError):
                    bench.run_case(12, 8, 20, 1, mode)
            for values in ((385, 8, 20, 1), (12, 257, 20, 1), (12, 8, 301, 1),
                           (12, 8, 20, 9), (1, 8, 20, 1)):
                with self.assertRaises(ValueError):
                    bench.run_benchmark(*values)
            with self.assertRaises(ValueError):
                bench.run_benchmark(repeats=4)
            for timeout in (True, 0, -1, float("nan"), float("inf"), 51):
                with self.assertRaises(ValueError):
                    bench.run_benchmark(total_timeout=timeout)

    def test_scrub_polluted_environment(self):
        dirty = {"PYTHON_GIL": "1", "AGILAB_POOL_EXECUTOR": "process",
                 "AGILAB_POOL_ITEM_TIMEOUT": "0.000001", "AGILAB_POOL_OTHER": "junk"}
        with patch.dict(os.environ, dirty):
            env = bench.child_environment("gil_off_threads", 2)
            self.assertNotIn("PYTHON_GIL", env)
            self.assertNotIn("AGILAB_POOL_ITEM_TIMEOUT", env)
            self.assertNotIn("AGILAB_POOL_OTHER", env)
            self.assertEqual(env["AGILAB_POOL_EXECUTOR"], "auto")
            self.assertEqual(env["AGILAB_POOL_MAX_WORKERS"], "2")
            self.assertEqual(os.environ["AGILAB_POOL_EXECUTOR"], "process")

    def test_cpu_quota_affinity_and_space_caps(self):
        with patch.dict(os.environ, {"CPU_CORES": "2", "SPACE_CPU_CORES": "4"}), \
             patch.object(bench, "_cgroup_limits", return_value=[1.5]), \
             patch.object(bench.os, "cpu_count", return_value=32):
            self.assertEqual(bench.effective_cpus()["effective_cpus"], 1)
        with patch.dict(os.environ, {"CPU_CORES": "nan"}):
            with self.assertRaises(ValueError):
                bench.effective_cpus()

    def test_cgroup_ancestor_quota(self):
        files = {"/proc/self/cgroup": "0::/team/job",
                 "/proc/self/mountinfo": "1 0 0:1 / /sys/fs/cgroup rw - cgroup2 cgroup rw",
                 "/sys/fs/cgroup/team/job/cpu.max": "max 100000",
                 "/sys/fs/cgroup/team/cpu.max": "150000 100000",
                 "/sys/fs/cgroup/cpu.max": "800000 100000"}
        with patch.object(bench, "_read", side_effect=lambda p: files.get(str(p), "")):
            self.assertEqual(bench._cgroup_limits(), [1.5, 8.0])

    def test_busy_lock_and_release(self):
        with bench.benchmark_lock():
            with self.assertRaises(bench.BusyError):
                with bench.benchmark_lock():
                    self.fail("Concurrent entry")
        with bench.benchmark_lock():
            pass

    def test_missing_and_ordinary_interpreters_fail(self):
        with patch.dict(os.environ, {"AGILAB_FREE_THREADING_PYTHON": "missing-free-threading-python"}):
            with self.assertRaisesRegex(RuntimeError, "AGILAB_FREE_THREADING_PYTHON"):
                bench.run_case(7, 5, 20, 1, "gil_off_threads")
        with patch.dict(os.environ, {"AGILAB_FREE_THREADING_PYTHON": sys.executable}):
            with self.assertRaises(RuntimeError):
                bench.run_case(7, 5, 20, 1, "gil_on_threads")

    def test_timeout_terminates_descendant_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as scratch:
            pidfile = Path(scratch) / "pid"
            source = ("import subprocess,sys,time,signal,pathlib; "
                      "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']); "
                      f"pathlib.Path({str(pidfile)!r}).write_text(str(p.pid)); "
                      "signal.signal(signal.SIGTERM,lambda *args: (p.wait(timeout=1),sys.exit(0))); "
                      "time.sleep(120)")
            with bench.benchmark_lock():
                with self.assertRaises(subprocess.TimeoutExpired):
                    bench._communicate([sys.executable, "-B", "-c", source], "", dict(os.environ), 0.5)
            pid = int(pidfile.read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
            with bench.benchmark_lock():
                pass

    def test_total_timeout_stops_before_more_cases(self):
        with patch.object(bench, "run_case") as run, patch.object(bench.time, "monotonic", side_effect=[0, 51]):
            with self.assertRaises(TimeoutError):
                bench.run_benchmark(12, 8, 20, workers=1, repeats=1)
            run.assert_not_called()


class InterfaceTests(unittest.TestCase):
    def test_actual_evidence_and_stale_controls(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(Path(__file__).with_name("app.py")), default_timeout=60).run()
        self.assertFalse(app.exception)
        self.assertNotIn("analysis", app.session_state)
        started = time.monotonic()
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertLess(time.monotonic() - started, 60)
        evidence = app.session_state["analysis"]
        self.assertTrue(evidence["same_work_verified"])
        self.assertEqual(len(evidence["runs"]), 12)
        self.assertEqual(len(app.metric), 6)
        app.selectbox[0].select("Medium · 288 × 192 · 240 iterations").run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Previous results" in warning.value for warning in app.warning))
        self.assertEqual(app.session_state["analysis"]["created_utc"], evidence["created_utc"])
        with bench.benchmark_lock():
            app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("busy" in warning.value for warning in app.warning))
        self.assertEqual(app.session_state["analysis"]["created_utc"], evidence["created_utc"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
