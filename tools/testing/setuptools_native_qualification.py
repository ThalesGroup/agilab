"""Qualify actual SDK-selected compiled workers at a setuptools boundary."""

from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]


def validate_native_case(junit: Path, result: int) -> dict[str, str]:
    cases = ET.parse(junit).findall(".//testcase")
    if (
        result != 0
        or len(cases) != 1
        or list(cases[0].iter("skipped"))
        or list(cases[0].iter("failure"))
        or list(cases[0].iter("error"))
    ):
        raise ValueError(
            "Native qualification requires one executed, passing compilation test; skips are not proof."
        )
    props = {
        item.attrib["name"]: item.attrib["value"]
        for item in cases[0].findall("./properties/property")
    }
    if props.get("sdk_selected_worker_module") != "uav_relay_queue_worker_cy":
        raise ValueError("The SDK did not select the compiled relay worker.")
    value = props.get("compiled_worker_sha256", "")
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Compiled worker hash is missing or invalid.")
    return props


def qualify(expected: str, output: Path) -> dict:
    import pytest
    import setuptools
    from agi_node.agi_dispatcher import build

    output.parent.mkdir(parents=True, exist_ok=True)
    junit = output.with_suffix(".xml")
    junit.unlink(missing_ok=True)
    from tools.testing.local_validation_receipt import source_snapshot

    snapshot = source_snapshot(ROOT)
    source = ROOT / "src/agilab/core/agi-node/src/agi_node/agi_dispatcher/build.py"
    payload = {
        "schema": "agilab.setuptools_native_qualification.v1",
        "source_sha": snapshot["head"],
        "source_snapshot_sha256": snapshot["sha256"],
        "run_id": os.environ.get("GITHUB_RUN_ID", "")
        if os.environ.get("GITHUB_ACTIONS") == "true"
        else "local-" + uuid.uuid4().hex,
        "execution": "github-actions"
        if os.environ.get("GITHUB_ACTIONS") == "true"
        else "local",
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT")
        if os.environ.get("GITHUB_ACTIONS") == "true"
        else None,
        "platform": platform.system(),
        "python": platform.python_version(),
        "setuptools": expected,
        "status": "failed",
        "qualification_test_sha256": hashlib.sha256(
            (ROOT / "test/test_uav_dag_scientific_handoff.py").read_bytes()
        ).hexdigest(),
        "sdk_build_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    try:
        if Path(build.__file__).resolve() != source.resolve():
            raise ValueError("SDK build module is not from this checkout.")
        if (
            setuptools.__version__ != expected
            or metadata.version("setuptools") != expected
        ):
            raise ValueError(
                "Installed setuptools differs from the requested boundary."
            )
        result = pytest.main(
            [
                "-q",
                "-o",
                "addopts=",
                f"--junitxml={junit}",
                "test/test_uav_dag_scientific_handoff.py::test_compiled_relay_worker_loads_scientific_handoff_through_sdk",
            ]
        )
        props = validate_native_case(junit, int(result))
        payload.update(
            status="passed",
            native_worker_sha256=props["compiled_worker_sha256"],
            sdk_selected_worker_module=props["sdk_selected_worker_module"],
            junit_sha256=hashlib.sha256(junit.read_bytes()).hexdigest(),
        )
    except (AssertionError, ValueError, OSError, ET.ParseError) as exc:
        payload["error"] = str(exc)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expected-setuptools", choices=("83.0.0", "84.2.1"), required=True
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = qualify(args.expected_setuptools, args.output)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
