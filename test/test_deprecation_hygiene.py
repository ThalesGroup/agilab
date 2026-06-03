from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_WARNING_SOURCES = (
    "src/agilab/core/agi-node/src/agi_node/agi_dispatcher/base_worker.py",
    "src/agilab/core/agi-node/src/agi_node/agi_dispatcher/agi_dispatcher.py",
    "src/agilab/core/agi-node/src/agi_node/pandas_worker/pandas_worker.py",
    "src/agilab/core/agi-node/src/agi_node/polars_worker/polars_worker.py",
    "src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/agi_distributor.py",
    "src/agilab/apps/builtin/flight_telemetry_project/src/flight_telemetry/flight_telemetry.py",
    "src/agilab/apps/builtin/flight_telemetry_project/src/flight_telemetry_worker/flight_telemetry_worker.py",
    "src/agilab/lib/agi-app-flight-telemetry/src/agi_app_flight_telemetry/project/flight_telemetry_project/src/flight_telemetry/flight_telemetry.py",
    "src/agilab/lib/agi-app-flight-telemetry/src/agi_app_flight_telemetry/project/flight_telemetry_project/src/flight_telemetry_worker/flight_telemetry_worker.py",
)


def test_runtime_modules_do_not_globally_ignore_warnings() -> None:
    offenders = []
    for relative_path in RUNTIME_WARNING_SOURCES:
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        if 'warnings.filterwarnings("ignore")' in text:
            offenders.append(relative_path)

    assert offenders == []


def test_core_runtime_imports_preserve_deprecation_warning_filters() -> None:
    code = """
import warnings
import agi_node.agi_dispatcher.base_worker
new_filters = [
    item for item in warnings.filters
    if item[0] == "ignore" and item[1] is None and item[2] is Warning
]
if new_filters:
    raise SystemExit(f"runtime import installed broad warning ignores: {new_filters!r}")
warnings.filterwarnings("error", category=DeprecationWarning)
try:
    warnings.warn("probe", DeprecationWarning)
except DeprecationWarning:
    pass
else:
    raise SystemExit("DeprecationWarning was suppressed")
"""
    pythonpath = os.pathsep.join(
        [
            str(ROOT / "src/agilab/core/agi-env/src"),
            str(ROOT / "src/agilab/core/agi-node/src"),
            os.environ.get("PYTHONPATH", ""),
        ]
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": pythonpath},
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_core_sources_do_not_use_deprecated_astor_or_distutils_sysconfig() -> None:
    sources = [
        ROOT / "src/agilab/core/agi-env/src/agi_env/agi_env.py",
        ROOT / "src/agilab/core/agi-env/src/agi_env/project_clone_support.py",
        ROOT / "src/agilab/core/agi-node/src/agi_node/agi_dispatcher/base_worker.py",
        ROOT / "src/agilab/core/agi-node/src/agi_node/agi_dispatcher/agi_dispatcher.py",
        ROOT / "src/agilab/pages/1_PROJECT.py",
    ]
    offenders: list[str] = []
    for source in sources:
        text = source.read_text(encoding="utf-8")
        if re.search(r"\bastor\b|distutils\.sysconfig", text):
            offenders.append(source.relative_to(ROOT).as_posix())

    assert offenders == []


def test_packaged_help_uses_current_troubleshooting_page() -> None:
    help_root = ROOT / "src/agilab/resources/help"
    html_files = sorted(help_root.glob("*.html"))
    assert (help_root / "troubleshooting.html").exists()

    typo_hits = []
    stale_heading_hits = []
    for html_file in html_files:
        text = html_file.read_text(encoding="utf-8")
        if "troubleshouting" in text:
            typo_hits.append(html_file.name)
        if "Known Bugs" in text:
            stale_heading_hits.append(html_file.name)

    assert typo_hits == []
    assert stale_heading_hits == []
