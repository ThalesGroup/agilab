"""Run the fixed Polars/Pydantic qualification suite with same-process evidence."""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from typing import TextIO
import xml.etree.ElementTree as ET

TEST_PATHS = (
    "src/agilab/core/test/test_polars_worker.py",
    "test/test_execution_polars_runtime_contracts.py",
    "src/agilab/core/test/test_agi_distributor_capacity_support.py",
    "src/agilab/core/agi-cluster/test/test_distribution_plan_and_cleanup_boundaries.py",
    "test/test_worker_dynamic_import_contract.py",
    "test/test_app_args.py",
    "test/test_app_args_form_normalization.py",
    "test/test_streamlit_args.py",
)
EXPECTED_VERSIONS = {"polars": "2.0.0", "pydantic": "2.14.0"}
SDK_FILES = {
    "agi_env": "src/agilab/core/agi-env/src/agi_env/__init__.py",
    "agi_node.polars_worker.polars_worker": "src/agilab/core/agi-node/src/agi_node/polars_worker/polars_worker.py",
    "agi_cluster.agi_distributor.runtime.runtime_distribution_support": "src/agilab/core/agi-cluster/src/agi_cluster/agi_distributor/runtime/runtime_distribution_support.py",
    "agi_web.testing": "src/agilab/lib/agi-web/src/agi_web/testing.py",
}
HELPER_PATH = ".github/scripts/agilab_polars_2_runtime_qualification.py"
WORKFLOW_PATH = ".github/workflows/agilab-polars-2-runtime-qualification.yml"
MANIFEST_PATHS = tuple(
    f"src/agilab/core/{name}/pyproject.toml"
    for name in ("agi-env", "agi-node", "agi-cluster", "agi-core")
) + ("src/agilab/lib/agi-web/pyproject.toml", "pyproject.toml")
SOURCE_PATHS = (
    TEST_PATHS
    + tuple(SDK_FILES.values())
    + MANIFEST_PATHS
    + (
        HELPER_PATH,
        WORKFLOW_PATH,
        "tools/testing/pytest_entrypoint.py",
    )
)


class QualificationError(RuntimeError):
    """A closed, metadata-only qualification failure."""


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes(root: Path) -> dict[str, str]:
    return {name: file_hash(root / name) for name in sorted(set(SOURCE_PATHS))}


def source_head(root: Path, expected: str) -> str:
    if re.fullmatch(r"[0-9a-f]{40}", expected) is None:
        raise QualificationError("invalid_source_sha")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    ).stdout.strip()
    if head != expected:
        raise QualificationError("source_sha_mismatch")
    return head


def public_ci_metadata(environment: dict[str, str]) -> dict[str, str]:
    """Never publish arbitrary environment contents or workflow inputs."""
    patterns = {
        "GITHUB_RUN_ID": r"[0-9]+",
        "GITHUB_RUN_ATTEMPT": r"[0-9]+",
        "GITHUB_EVENT_NAME": r"(pull_request|push|workflow_dispatch)",
        "RUNNER_OS": r"(Linux|Windows|macOS)",
    }
    return {
        key: value
        for key, pattern in patterns.items()
        if (value := environment.get(key)) and re.fullmatch(pattern, value)
    }


def dependency_attestation() -> dict[str, dict[str, str]]:
    result = {}
    for name, expected in EXPECTED_VERSIONS.items():
        module = importlib.import_module(name)
        version = getattr(module, "__version__", None)
        distribution = importlib.metadata.distribution(name)
        installed_version = distribution.version
        if version != expected or installed_version != expected:
            raise QualificationError(f"{name}_version_mismatch")
        path = Path(module.__file__).resolve()
        distribution_root = Path(distribution.locate_file("")).resolve()
        if path != Path(distribution.locate_file(f"{name}/__init__.py")).resolve():
            raise QualificationError(f"{name}_module_distribution_mismatch")
        relative_path = path.relative_to(distribution_root)
        result[name] = {
            "version": version,
            "distribution_version": installed_version,
            "module_file": "$DISTRIBUTION_ROOT/" + relative_path.as_posix(),
            "module_sha256": file_hash(path),
        }
    return result


def sdk_attestation(root: Path) -> dict[str, dict[str, str]]:
    """Inspect modules loaded by the tests; never import SDK worker classes."""
    result = {}
    for name, relative_path in SDK_FILES.items():
        module = sys.modules.get(name)
        module_file = getattr(module, "__file__", None)
        if (
            not module_file
            or Path(module_file).resolve() != (root / relative_path).resolve()
        ):
            raise QualificationError(f"sdk_source_mismatch:{name}")
        result[name] = {
            "module_file": relative_path,
            "module_sha256": file_hash(root / relative_path),
        }
    return result


class QualificationPlugin:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.collected = 0
        self.collected_by_file: Counter[str] = Counter()
        self.counts: Counter[str] = Counter()
        self.errors: list[str] = []
        self.collection_sdk: dict = {}
        self.session_finish: dict = {}

    def pytest_collection_finish(self, session) -> None:
        self.collected = len(session.items)
        for item in session.items:
            try:
                name = (
                    Path(item.path)
                    .resolve()
                    .relative_to(self.root.resolve())
                    .as_posix()
                )
            except (AttributeError, ValueError):
                self.errors.append("unexpected_collected_source")
                continue
            self.collected_by_file[name] += 1
        try:
            self.collection_sdk = sdk_attestation(self.root)
        except QualificationError as error:
            self.errors.append(str(error))

    def pytest_deselected(self, items) -> None:
        self.counts["deselected"] += len(items)

    def pytest_collectreport(self, report) -> None:
        if report.failed:
            self.counts["collection_failed"] += 1
        if report.skipped:
            self.counts["skipped"] += 1

    def pytest_runtest_logreport(self, report) -> None:
        if report.failed:
            self.counts["failed"] += 1
        elif report.skipped:
            self.counts["skipped"] += 1
        elif report.when == "call" and report.passed:
            self.counts["passed"] += 1

    def pytest_sessionfinish(self, session, exitstatus) -> None:
        try:
            self.session_finish = {
                "dependencies": dependency_attestation(),
                "sdk": sdk_attestation(self.root),
            }
        except QualificationError as error:
            self.errors.append(str(error))


class Tee:
    def __init__(self, console: TextIO, log: TextIO) -> None:
        self.console, self.log = console, log

    def write(self, text: str) -> int:
        self.console.write(text)
        return self.log.write(text)

    def flush(self) -> None:
        self.console.flush()
        self.log.flush()

    def isatty(self) -> bool:
        return False


def validate_results(
    plugin: QualificationPlugin, exit_code: int, junit_path: Path
) -> None:
    if plugin.errors:
        raise QualificationError("same_process_attestation_failed")
    if plugin.collected <= 0:
        raise QualificationError("no_tests_collected")
    if exit_code != 0 or plugin.counts["failed"] or plugin.counts["collection_failed"]:
        raise QualificationError("pytest_failed")
    if plugin.counts["skipped"]:
        raise QualificationError("tests_skipped")
    if plugin.counts["deselected"]:
        raise QualificationError("tests_deselected")
    if (
        set(plugin.collected_by_file) != set(TEST_PATHS)
        or any(plugin.collected_by_file[name] <= 0 for name in TEST_PATHS)
        or sum(plugin.collected_by_file.values()) != plugin.collected
    ):
        raise QualificationError("incomplete_test_file_coverage")
    if plugin.counts["passed"] != plugin.collected:
        raise QualificationError("incomplete_test_execution")
    if not plugin.collection_sdk or not plugin.session_finish:
        raise QualificationError("missing_pytest_attestation")
    if not junit_path.is_file():
        raise QualificationError("missing_junit")
    suites = ET.parse(junit_path).getroot().iter("testsuite")
    totals = Counter()
    for suite in suites:
        for key in ("tests", "failures", "errors", "skipped"):
            totals[key] += int(suite.get(key, "0"))
    if totals["tests"] != plugin.collected or any(
        totals[key] for key in ("failures", "errors", "skipped")
    ):
        raise QualificationError("junit_results_mismatch")


def run_qualification(
    root: Path,
    output: Path,
    expected_sha: str,
    expected_python: str,
    expected_platform: str,
) -> int:
    root = root.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "agilab-polars-2-runtime-qualification.json"
    junit_path = output / "agilab-polars-2-runtime-qualification.xml"
    log_path = output / "agilab-polars-2-runtime-qualification.log"
    if any(path.exists() for path in (report_path, junit_path, log_path)):
        raise QualificationError("evidence_output_already_exists")
    report: dict = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "failed",
        "expected_versions": EXPECTED_VERSIONS,
        "python_version": platform.python_version(),
        "platform": platform.system(),
        "ci": public_ci_metadata(dict(os.environ)),
        "test_files": list(TEST_PATHS),
    }
    plugin = QualificationPlugin(root)
    exit_code = None
    try:
        if ".".join(platform.python_version_tuple()[:2]) != expected_python:
            raise QualificationError("python_minor_mismatch")
        if platform.system() != expected_platform:
            raise QualificationError("platform_mismatch")
        report["source_sha"] = source_head(root, expected_sha)
        report["source_hashes"] = source_hashes(root)
        report["before_pytest"] = dependency_attestation()
        sys.path.insert(0, str(root))
        from tools.testing.pytest_entrypoint import clear_uv_target_environment

        clear_uv_target_environment()
        for key in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
            os.environ.pop(key, None)
        os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        import pytest

        with log_path.open("x", encoding="utf-8") as log:
            with (
                redirect_stdout(Tee(sys.stdout, log)),
                redirect_stderr(Tee(sys.stderr, log)),
            ):
                exit_code = int(
                    pytest.main(
                        [
                            "-q",
                            "-ra",
                            "-o",
                            "addopts=",
                            "-p",
                            "no:cacheprovider",
                            "-p",
                            "pytest_asyncio.plugin",
                            "--import-mode=importlib",
                            "--junitxml",
                            str(junit_path),
                            *[str(root / name) for name in TEST_PATHS],
                        ],
                        plugins=[plugin],
                    )
                )
        report["after_pytest"] = dependency_attestation()
        report["after_pytest_sdk"] = sdk_attestation(root)
        if source_hashes(root) != report["source_hashes"]:
            raise QualificationError("source_changed_during_tests")
        validate_results(plugin, exit_code, junit_path)
        report["status"] = "passed"
    except (
        QualificationError,
        OSError,
        ValueError,
        subprocess.SubprocessError,
        importlib.metadata.PackageNotFoundError,
    ) as error:
        report["error"] = (
            str(error)
            if isinstance(error, QualificationError)
            else type(error).__name__
        )
    finally:
        report["pytest_exit_code"] = exit_code
        report["collected"] = plugin.collected
        report["collected_by_file"] = dict(sorted(plugin.collected_by_file.items()))
        report["test_outcomes"] = dict(sorted(plugin.counts.items()))
        report["collection_sdk"] = plugin.collection_sdk
        report["session_finish"] = plugin.session_finish
        report["attestation_errors"] = plugin.errors
        report["artifacts"] = {
            path.name: {"sha256": file_hash(path), "bytes": path.stat().st_size}
            for path in (junit_path, log_path)
            if path.is_file()
        }
        with report_path.open("x", encoding="utf-8") as target:
            json.dump(report, target, indent=2, sort_keys=True)
            target.write("\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "source_sha": report.get("source_sha"),
                "collected": plugin.collected,
                "test_outcomes": report["test_outcomes"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument(
        "--expected-python", choices=("3.12", "3.13", "3.14"), required=True
    )
    parser.add_argument(
        "--expected-platform", choices=("Linux", "Windows", "Darwin"), required=True
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    return run_qualification(
        Path(__file__).resolve().parents[2],
        args.output_dir,
        args.source_sha,
        args.expected_python,
        args.expected_platform,
    )


if __name__ == "__main__":
    raise SystemExit(main())
