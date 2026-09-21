"""Focused physical, boundary, isolation, engine and Streamlit regressions."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from energy_core import (
    check_result,
    cpu_limits,
    default_settings,
    make_batch,
    validate_batch,
    validate_settings,
)
from energy_runner import (
    _exclusive,
    _launch,
    _terminate_group,
    compare_runs,
    run_batch,
    run_scenario,
)

ROOT = Path(__file__).resolve().parent


class Boundaries(unittest.TestCase):
    def test_reject_before_launch(self):
        bad = [
            None,
            [],
            {"unknown": 1},
            {"hours": 4.0},
            {"hours": True},
            {"hours": 5},
            {"max_modules": False},
            {"max_modules": 0},
            {"max_modules": 101},
            {"allow_shedding": 1},
            {"allow_shedding": "false"},
        ]
        for field in (
            "demand_multiplier",
            "module_mw",
            "investment_cost",
            "marginal_cost",
            "startup_cost",
            "standby_cost",
            "min_loading",
            "solar_capacity",
            "time_limit",
            "mip_rel_gap",
        ):
            bad.extend(
                {field: value}
                for value in (
                    True,
                    "1",
                    None,
                    float("nan"),
                    float("inf"),
                    -float("inf"),
                    -1,
                    10**1000,
                )
            )
        with patch("energy_runner._launch") as launch:
            for value in bad:
                with (
                    self.subTest(value=str(value)[:100]),
                    self.assertRaises(ValueError),
                ):
                    run_scenario(value)
            launch.assert_not_called()

    def test_valid_boundaries(self):
        for value in (0.1, 10):
            self.assertEqual(
                validate_settings({"time_limit": value})["time_limit"], value
            )
        self.assertEqual(validate_settings({"min_loading": 0})["min_loading"], 0)
        self.assertEqual(validate_settings({"min_loading": 1})["min_loading"], 1)
        for key in (
            "investment_cost",
            "marginal_cost",
            "startup_cost",
            "standby_cost",
            "solar_capacity",
            "mip_rel_gap",
        ):
            self.assertEqual(validate_settings({key: 0})[key], 0)
        json.dumps(default_settings(), allow_nan=False)

    def test_batch_limits_and_determinism(self):
        self.assertEqual(make_batch({}, 4), make_batch({}, 4))
        self.assertEqual(
            len({json.dumps(x, sort_keys=True) for x in make_batch({}, 12)}), 12
        )
        for count in (True, 2, 16, 4.0):
            with self.assertRaises(ValueError):
                make_batch({}, count)
        for workers in (True, 0, 5):
            with self.assertRaises(ValueError):
                validate_batch(make_batch({}, 4), workers)

    def test_cpu_environment_pollution(self):
        with patch.dict(os.environ, {"CPU_CORES": "1.5"}):
            self.assertEqual(cpu_limits()["effective_cpus"], 1)
        for bad in ("nan", "inf", "wrong", "0"):
            with patch.dict(os.environ, {"CPU_CORES": bad}):
                self.assertEqual(cpu_limits()["effective_cpus"], 1)
        self.assertLessEqual(cpu_limits()["effective_cpus"], 4)

    def test_cgroup_ancestor_limit(self):
        original = Path.read_text

        def read(path, *args, **kwargs):
            fake = {
                "/proc/self/cgroup": "0::/lab/child",
                "/sys/fs/cgroup/lab/child/cpu.max": "400000 100000",
                "/sys/fs/cgroup/lab/cpu.max": "100000 100000",
            }
            if str(path) in fake:
                return fake[str(path)]
            if str(path).startswith("/sys/fs/cgroup"):
                raise FileNotFoundError
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", read):
            self.assertEqual(cpu_limits()["effective_cpus"], 1)

    def test_busy_and_nesting_fail_fast(self):
        start = time.monotonic()
        with _exclusive():
            with self.assertRaisesRegex(RuntimeError, "busy"):
                run_scenario({})
        self.assertLess(time.monotonic() - start, 1)
        with patch.dict(os.environ, {"MILP_ENERGY_CHILD": "1"}):
            with self.assertRaisesRegex(RuntimeError, "Nested"):
                run_scenario({})

    def test_timeout_cleanup_real_child(self):
        # Starts the real fixed solver CLI, times it out during startup, and checks cleanup.
        created = []
        real_popen = subprocess.Popen

        def record(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            created.append(process)
            return process

        with tempfile.TemporaryDirectory() as scratch:
            with (
                patch("energy_runner.tempfile.tempdir", scratch),
                patch("energy_runner.subprocess.Popen", record),
            ):
                with self.assertRaises(TimeoutError):
                    _launch("single", validate_settings({}), time.monotonic() + 0.02)
                self.assertEqual(list(Path(scratch).iterdir()), [])
        self.assertEqual(len(created), 1)
        self.assertIsNotNone(created[0].poll())

    def test_cleanup_when_process_enumeration_is_denied(self):
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        with patch(
            "psutil.Process.children",
            side_effect=PermissionError("sandbox PID enumeration denied"),
        ):
            _terminate_group(process)
        self.assertIsNotNone(process.returncode)

    def test_process_group_descendants(self):
        import psutil

        with tempfile.TemporaryDirectory() as scratch:
            pidfile = Path(scratch) / "pid"
            # Test-only fixed child workload; never exposed through the app or runner.
            code = (
                "import subprocess,sys,time,pathlib; "
                'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
                "pathlib.Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(30)"
            )
            process = subprocess.Popen(
                [sys.executable, "-c", code, str(pidfile)], start_new_session=True
            )
            try:
                deadline = time.monotonic() + 5
                while not pidfile.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(pidfile.exists())
                child_pid = int(pidfile.read_text())
            finally:
                _terminate_group(process)
            self.assertIsNotNone(process.returncode)
            if psutil.pid_exists(child_pid):
                self.assertEqual(
                    psutil.Process(child_pid).status(), psutil.STATUS_ZOMBIE
                )

    def test_source_integrity(self):
        expected = {
            "source/original.ipynb": "f7ea554af73cb21b3eb8c0569c7c21eac0b327e0ce35c29cf23806d74af926b8",
            "source/LICENSE": "d557539df68e771cc1eedcc91d13f70fca930e508d11eedcafa4b15db49e3744",
            "source/provenance.json": "5a142f1195399b3efb5b6f8713500d72c81efcd7b68fc27c9102ff4bc19566ff",
            "agilab_pool.py": "305ba174348e92376b08be149b488fc41983de04c5b2564695493769fc21f066",
            "AGILAB_LICENSE": "b9c2bbb8087ee916e1f8628c002b1f9af77cf7dc112331edca5edec4cd5b0a16",
        }
        for name, digest in expected.items():
            self.assertEqual(
                hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest, name
            )


class PhysicalModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.batch = [
            default_settings(),
            default_settings() | {"max_modules": 10},
            default_settings() | {"max_modules": 10, "allow_shedding": True},
            default_settings() | {"solar_capacity": 12000, "min_loading": 0.5},
        ]
        cls.report = run_batch(cls.batch, 1)
        cls.results = [x["result"] for x in cls.report["rows"]]

    def independently_assert(self, r):
        self.assertIn(r["status"], ("optimal", "feasible"), r.get("message"))
        self.assertTrue(r["residuals"]["verified"])
        s = r["settings"]
        self.assertAlmostEqual(r["modules"], round(r["modules"]), places=5)
        self.assertLessEqual(r["modules"], s["max_modules"] + 1e-5)
        self.assertAlmostEqual(r["capacity_mw"], s["module_mw"] * r["modules"])
        last = 0
        for t, (p, u, q, unserved, a, b) in enumerate(
            zip(
                r["dispatch"],
                r["active_modules"],
                r["solar"],
                r["shed"],
                r["startup"],
                r["shutdown"],
            )
        ):
            for value in (u, a, b):
                self.assertAlmostEqual(value, round(value), places=5)
            for value in (p, u, q, unserved, a, b):
                self.assertGreaterEqual(value, -1e-5)
            self.assertLessEqual(u, r["modules"] + 1e-5)
            self.assertGreaterEqual(p + 1e-5, u * s["module_mw"] * s["min_loading"])
            self.assertLessEqual(p, u * s["module_mw"] + 1e-5)
            demand = [4000, 6000, 5000, 800][t % 4] * s["demand_multiplier"]
            self.assertAlmostEqual(p + q + unserved, demand, places=5)
            self.assertLessEqual(q, r["solar_available"][t] + 1e-5)
            self.assertLessEqual(unserved, demand * s["allow_shedding"] + 1e-5)
            self.assertAlmostEqual(a, max(0, u - last), places=5)
            self.assertAlmostEqual(b, max(0, last - u), places=5)
            last = u
        objective = (
            s["investment_cost"] * s["module_mw"] * r["modules"]
            + s["marginal_cost"] * sum(r["dispatch"])
            + s["standby_cost"] * sum(r["active_modules"])
            + s["startup_cost"] * sum(r["startup"])
            + 100000 * sum(r["shed"])
        )
        self.assertTrue(
            math.isclose(objective, r["objective"], rel_tol=1e-7, abs_tol=1e-4)
        )
        json.dumps(r, allow_nan=False)

    def test_reference_and_real_bound(self):
        r = self.results[0]
        self.independently_assert(r)
        self.assertEqual(r["modules"], 30)
        self.assertEqual(r["active_modules"], [20, 30, 25, 4])
        self.assertEqual(r["dispatch"], [4000, 6000, 5000, 800])
        self.assertEqual(r["startup"], [20, 10, 0, 0])
        self.assertEqual(r["objective"], 6000 + 15800 + 79)
        self.assertEqual(r["solver"]["gap"], 0)
        self.assertEqual(r["solver"]["objective_bound"], 21879)

    def test_infeasible_and_no_incumbent(self):
        r = self.results[1]
        self.assertEqual(r["status"], "infeasible", r.get("message"))
        for key in ("objective", "modules", "capacity_mw"):
            self.assertIsNone(r[key])
        for key in (
            "dispatch",
            "active_modules",
            "solar",
            "shed",
            "startup",
            "shutdown",
        ):
            self.assertEqual(r[key], [])
        self.assertFalse(r["residuals"]["verified"])

    def test_shedding(self):
        r = self.results[2]
        self.independently_assert(r)
        self.assertAlmostEqual(sum(r["shed"]), 9000)
        self.assertFalse(r["physical_supply_sufficient"])

    def test_solar_and_curtailment(self):
        r = self.results[3]
        self.independently_assert(r)
        self.assertGreater(sum(r["solar"]), 0)
        self.assertGreater(sum(r["solar_available"]) - sum(r["solar"]), 0)

    def test_corruption_detected(self):
        for key in (
            "dispatch",
            "active_modules",
            "startup",
            "shutdown",
            "shed",
            "solar",
        ):
            r = copy.deepcopy(self.results[0])
            r[key][0] += 1
            self.assertFalse(check_result(r["settings"], r)[1]["verified"], key)
        r = copy.deepcopy(self.results[0])
        r["objective"] += 10
        self.assertFalse(check_result(r["settings"], r)[1]["verified"])

    def test_actual_engine_rows(self):
        self.assertEqual(len(self.report["rows"]), 4)
        self.assertGreater(self.report["engine_seconds"], 0)
        self.assertGreaterEqual(
            self.report["wall_seconds"], self.report["engine_seconds"]
        )
        for row in self.report["rows"]:
            self.assertNotEqual(row["pid"], os.getpid())
            self.assertGreater(row["end_monotonic"], row["start_monotonic"])
        self.assertTrue(compare_runs(self.report, self.report)["matches"])
        incomplete = copy.deepcopy(self.report)
        incomplete["rows"].pop()
        with self.assertRaisesRegex(RuntimeError, "Missing or reordered"):
            compare_runs(self.report, incomplete)
        other = copy.deepcopy(self.report)
        other["rows"][0]["result"]["status"] = "error"
        self.assertFalse(compare_runs(self.report, other)["matches"])

    def test_startup_tradeoff(self):
        batch = [
            default_settings() | {"hours": 12, "startup_cost": v}
            for v in (0, 1000, 1000, 0)
        ]
        r = run_batch(batch, 1)
        low, high = [row["result"] for row in r["rows"][:2]]
        self.independently_assert(low)
        self.independently_assert(high)
        self.assertLess(sum(high["startup"]), sum(low["startup"]))
        self.assertGreater(sum(high["active_modules"]), sum(low["active_modules"]))


class Interface(unittest.TestCase):
    def test_real_run_and_saved_input_identity(self):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
        self.assertFalse(app.exception)
        buttons = [b for b in app.button if b.label == "Run analysis"]
        self.assertEqual(len(buttons), 1)
        self.assertNotIn("milp_energy_result", app.session_state)
        buttons[0].click().run()
        self.assertFalse(app.exception)
        r = app.session_state["milp_energy_result"]
        self.assertEqual(r["objective"], 21879)
        self.assertTrue(any("21,879" in m.value for m in app.metric))
        next(b for b in app.button if b.label == "Save current scenario").click().run()
        self.assertEqual(len(app.session_state["milp_energy_saved"]), 1)
        app.number_input(key="milp_energy_demand").set_value(1.2)
        next(b for b in app.button if b.label == "Save current scenario").click().run()
        self.assertEqual(
            app.session_state["milp_energy_result"]["settings"]["demand_multiplier"],
            1.0,
        )
        self.assertFalse(app.exception)


def browser_check():
    """Optional real-browser check using already-installed Chromium; no downloads."""
    import socket
    import urllib.request
    from playwright.sync_api import sync_playwright

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    issues = dict(
        console_errors=[],
        console_warnings=[],
        page_errors=[],
        failed_requests=[],
        http_errors=[],
    )
    env = os.environ.copy()
    env.update(STREAMLIT_BROWSER_GATHER_USAGE_STATS="false")
    with tempfile.TemporaryDirectory(prefix="milp-browser-") as scratch:
        with open(Path(scratch) / "server.log", "w+") as log:
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "streamlit",
                    "run",
                    str(ROOT / "app.py"),
                    "--server.address=127.0.0.1",
                    f"--server.port={port}",
                    "--server.headless=true",
                    "--browser.gatherUsageStats=false",
                ],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    try:
                        with urllib.request.urlopen(
                            f"http://127.0.0.1:{port}/_stcore/health", timeout=1
                        ) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(0.1)
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page(viewport=dict(width=1280, height=1000))
                    page.on(
                        "console",
                        lambda msg: (
                            issues[
                                "console_errors"
                                if msg.type == "error"
                                else "console_warnings"
                            ].append(msg.text)
                            if msg.type in ("error", "warning")
                            else None
                        ),
                    )
                    page.on(
                        "pageerror", lambda exc: issues["page_errors"].append(str(exc))
                    )
                    page.on(
                        "requestfailed",
                        lambda req: issues["failed_requests"].append(
                            dict(url=req.url, error=req.failure)
                        ),
                    )
                    page.on(
                        "response",
                        lambda res: (
                            issues["http_errors"].append(
                                dict(url=res.url, status=res.status)
                            )
                            if res.status >= 400
                            else None
                        ),
                    )
                    page.goto(f"http://127.0.0.1:{port}", wait_until="networkidle")
                    page.get_by_role("button", name="Run analysis", exact=True).click()
                    page.get_by_text("21,879.00", exact=True).first.wait_for(
                        timeout=60000
                    )
                    page.screenshot(
                        path=str(ROOT / "browser-experiment.png"), full_page=True
                    )
                    page.get_by_role("tab", name="Inspect", exact=True).click()
                    page.get_by_text("HiGHS", exact=False).first.wait_for()
                    page.get_by_role("tab", name="Compare", exact=True).click()
                    page.get_by_role(
                        "button", name="Save current scenario", exact=True
                    ).click()
                    page.get_by_role(
                        "button", name="Clear saved scenarios", exact=True
                    ).wait_for()
                    page.get_by_role("tab", name="Scale", exact=True).click()
                    if cpu_limits()["effective_cpus"] >= 2:
                        page.get_by_role(
                            "button", name="Run scaling experiment", exact=True
                        ).click()
                        page.get_by_text(
                            "All statuses and objectives match", exact=False
                        ).wait_for(timeout=150000)
                        page.screenshot(
                            path=str(ROOT / "browser-scale.png"), full_page=True
                        )
                    page.get_by_role("tab", name="Reproduce", exact=True).click()
                    with page.expect_download() as download:
                        page.get_by_role(
                            "button", name="Results JSON", exact=True
                        ).click()
                    result_path = Path(scratch) / "download.json"
                    download.value.save_as(result_path)
                    assert json.loads(result_path.read_text())["objective"] == 21879
                    page.set_viewport_size(dict(width=390, height=844))
                    page.get_by_role("tab", name="Experiment", exact=True).click()
                    page.screenshot(
                        path=str(ROOT / "browser-mobile.png"), full_page=True
                    )
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth + 2"
                    ), "Mobile page overflows horizontally"
                    report = dict(
                        status="passed",
                        checks=[
                            "default_solve",
                            "inspect",
                            "save_scenario",
                            "scaling",
                            "download",
                            "mobile",
                        ],
                        issues=issues,
                    )
                    (ROOT / "browser-evidence.json").write_text(
                        json.dumps(report, indent=2)
                    )
                    assert not any(
                        issues[k]
                        for k in (
                            "console_errors",
                            "page_errors",
                            "failed_requests",
                            "http_errors",
                        )
                    ), issues
                    browser.close()
            finally:
                _terminate_group(server)
    print(json.dumps(report))


if __name__ == "__main__":
    if sys.argv[1:] == ["--browser"]:
        browser_check()
    else:
        unittest.main(verbosity=2)
