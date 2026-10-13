"""Qualification evidence must reject misleading green dependency results."""

from __future__ import annotations

from collections import Counter
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "agilab_polars_2_qualification",
    ROOT / ".github/scripts/agilab_polars_2_runtime_qualification.py",
)
assert SPEC and SPEC.loader
qualification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualification)


def finished_plugin():
    plugin = qualification.QualificationPlugin(ROOT)
    plugin.collected = len(qualification.TEST_PATHS)
    plugin.collected_by_file = Counter({name: 1 for name in qualification.TEST_PATHS})
    plugin.counts = Counter(passed=plugin.collected)
    plugin.collection_sdk = {"agi_env": {"module_file": "source"}}
    plugin.session_finish = {"dependencies": {"polars": {"version": "2.0.0"}}}
    return plugin


def write_junit(path, *, tests=8, skipped=0, failures=0):
    path.write_text(
        f'<testsuites><testsuite tests="{tests}" skipped="{skipped}" '
        f'failures="{failures}" errors="0"/></testsuites>',
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("collected", 0, "no_tests_collected"),
        ("counts", Counter(passed=1, skipped=1), "tests_skipped"),
        ("counts", Counter(passed=1), "incomplete_test_execution"),
        ("counts", Counter(passed=1, failed=1), "pytest_failed"),
        ("counts", Counter(collection_failed=1), "pytest_failed"),
        ("errors", ["polars_version_mismatch"], "same_process_attestation_failed"),
        ("session_finish", {}, "missing_pytest_attestation"),
        ("collection_sdk", {}, "missing_pytest_attestation"),
    ],
)
def test_result_validation_rejects_false_green(tmp_path, field, value, error):
    plugin = finished_plugin()
    setattr(plugin, field, value)
    junit = tmp_path / "qualification.xml"
    write_junit(junit)
    with pytest.raises(qualification.QualificationError, match=error):
        qualification.validate_results(plugin, 0, junit)


def test_missing_junit_cannot_pass(tmp_path):
    with pytest.raises(qualification.QualificationError, match="missing_junit"):
        qualification.validate_results(finished_plugin(), 0, tmp_path / "missing.xml")


@pytest.mark.parametrize(
    ("tests", "skipped", "failures"), [(1, 0, 0), (8, 1, 0), (8, 0, 1)]
)
def test_junit_must_agree_with_same_process_results(tmp_path, tests, skipped, failures):
    junit = tmp_path / "qualification.xml"
    write_junit(junit, tests=tests, skipped=skipped, failures=failures)
    with pytest.raises(
        qualification.QualificationError, match="junit_results_mismatch"
    ):
        qualification.validate_results(finished_plugin(), 0, junit)


def test_nonzero_pytest_exit_cannot_pass(tmp_path):
    junit = tmp_path / "qualification.xml"
    write_junit(junit)
    with pytest.raises(qualification.QualificationError, match="pytest_failed"):
        qualification.validate_results(finished_plugin(), 5, junit)


@pytest.mark.parametrize("changed_version", ["module", "distribution"])
def test_actual_module_and_distribution_versions_must_match(
    monkeypatch, tmp_path, changed_version
):
    installed_file = tmp_path / "polars.py"
    installed_file.write_text("# exact imported bytes", encoding="utf-8")
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    monkeypatch.setattr(
        qualification.importlib,
        "import_module",
        lambda name: SimpleNamespace(
            __version__="1.44.2" if changed_version == "module" else "2.0.0",
            __file__=str(installed_file),
        ),
    )
    monkeypatch.setattr(
        qualification.importlib.metadata,
        "distribution",
        lambda name: SimpleNamespace(
            version="1.44.2" if changed_version == "distribution" else "2.0.0",
            locate_file=lambda path: tmp_path / path,
        ),
    )
    with pytest.raises(
        qualification.QualificationError, match="polars_version_mismatch"
    ):
        qualification.dependency_attestation()


def test_dependency_loaded_from_other_environment_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "expected"))
    monkeypatch.setattr(
        qualification.importlib,
        "import_module",
        lambda name: SimpleNamespace(
            __version__="2.0.0", __file__=str(tmp_path / "other.py")
        ),
    )
    monkeypatch.setattr(
        qualification.importlib.metadata,
        "distribution",
        lambda name: SimpleNamespace(
            version="2.0.0", locate_file=lambda path: tmp_path / "expected" / path
        ),
    )
    with pytest.raises(
        qualification.QualificationError, match="polars_module_distribution_mismatch"
    ):
        qualification.dependency_attestation()


def test_sdk_provenance_does_not_import_or_reject_temporary_workers(
    monkeypatch, tmp_path
):
    modules = {}
    for name, relative in qualification.SDK_FILES.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# owned SDK", encoding="utf-8")
        modules[name] = SimpleNamespace(__file__=str(path))
    modules["synthetic_worker"] = SimpleNamespace(__file__=str(tmp_path / "worker.py"))
    monkeypatch.setattr(qualification.sys, "modules", modules)
    monkeypatch.setattr(
        qualification.importlib,
        "import_module",
        lambda name: pytest.fail("SDK provenance must inspect existing imports"),
    )
    result = qualification.sdk_attestation(tmp_path)
    assert set(result) == set(qualification.SDK_FILES)
    modules["agi_env"].__file__ = str(tmp_path / "outside.py")
    with pytest.raises(
        qualification.QualificationError, match="sdk_source_mismatch:agi_env"
    ):
        qualification.sdk_attestation(tmp_path)


def test_source_sha_must_match_actual_checkout(monkeypatch):
    monkeypatch.setattr(
        qualification.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 0, stdout="a" * 40 + "\n"
        ),
    )
    assert qualification.source_head(ROOT, "a" * 40) == "a" * 40
    with pytest.raises(qualification.QualificationError, match="source_sha_mismatch"):
        qualification.source_head(ROOT, "b" * 40)
    with pytest.raises(qualification.QualificationError, match="invalid_source_sha"):
        qualification.source_head(ROOT, "not-a-sha")


def test_ci_metadata_does_not_include_credentials_or_untrusted_values():
    result = qualification.public_ci_metadata(
        {
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "2",
            "GITHUB_EVENT_NAME": "pull_request",
            "RUNNER_OS": "Windows",
            "TOKEN": "private-value",
            "GITHUB_TOKEN": "private-value",
            "GITHUB_ACTOR": "private-user",
            "GITHUB_REF_NAME": "private-branch",
            "QUALIFICATION_INPUT": "private-value",
        }
    )
    assert result == {
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_EVENT_NAME": "pull_request",
        "RUNNER_OS": "Windows",
    }
    assert qualification.public_ci_metadata({"GITHUB_RUN_ID": "123 secret"}) == {}


@pytest.mark.parametrize(
    ("outcome", "expected_status"),
    [
        ("passed", "passed"),
        ("skipped", "failed"),
        ("missing_junit", "failed"),
        ("version_drift", "failed"),
    ],
)
def test_helper_writes_evidence_and_preserves_failures(
    monkeypatch, tmp_path, outcome, expected_status
):
    monkeypatch.setattr(qualification, "source_head", lambda *args: "a" * 40)
    monkeypatch.setattr(
        qualification, "source_hashes", lambda *args: {"source.py": "digest"}
    )
    monkeypatch.setattr(
        qualification,
        "sdk_attestation",
        lambda *args: {"owned": {"module_file": "source.py"}},
    )
    calls = 0

    def dependencies():
        nonlocal calls
        calls += 1
        if outcome == "version_drift" and calls > 1:
            raise qualification.QualificationError("polars_version_mismatch")
        return {"polars": {"version": "2.0.0"}, "pydantic": {"version": "2.14.0"}}

    def fake_pytest(args, plugins):
        plugin = plugins[0]
        plugin.pytest_collection_finish(
            SimpleNamespace(
                items=[
                    SimpleNamespace(path=ROOT / name)
                    for name in qualification.TEST_PATHS
                ]
            )
        )
        for _ in qualification.TEST_PATHS:
            plugin.pytest_runtest_logreport(
                SimpleNamespace(
                    failed=False,
                    skipped=outcome == "skipped",
                    when="call",
                    passed=True,
                )
            )
        plugin.pytest_sessionfinish(None, 0)
        if outcome != "missing_junit":
            write_junit(Path(args[args.index("--junitxml") + 1]))
        print("simulated controlled pytest output")
        return 0

    monkeypatch.setattr(qualification, "dependency_attestation", dependencies)
    monkeypatch.setattr(pytest, "main", fake_pytest)
    output = tmp_path / "evidence"
    result = qualification.run_qualification(
        ROOT,
        output,
        "a" * 40,
        ".".join(qualification.platform.python_version_tuple()[:2]),
        qualification.platform.system(),
    )
    report = json.loads(
        (output / "agilab-polars-2-runtime-qualification.json").read_text()
    )
    assert report["status"] == expected_status
    assert result == (0 if expected_status == "passed" else 1)
    assert report["collected"] == len(qualification.TEST_PATHS)
    assert (output / "agilab-polars-2-runtime-qualification.log").is_file()
    with pytest.raises(
        qualification.QualificationError, match="evidence_output_already_exists"
    ):
        qualification.run_qualification(ROOT, output, "a" * 40, "3.13", "Linux")


def test_workflow_runs_all_six_cells_without_credentials_or_weak_dependency_resolution():
    path = ROOT / qualification.WORKFLOW_PATH
    text = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    assert workflow["permissions"] == {"contents": "read"}
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) == {"pull_request", "push", "workflow_dispatch"}
    job = workflow["jobs"]["polars-2-runtime-qualification"]
    assert job["strategy"] == {
        "fail-fast": False,
        "matrix": {
            "os": ["ubuntu-latest", "windows-latest"],
            "python": ["3.12", "3.13", "3.14"],
        },
    }
    checkout = job["steps"][0]
    assert checkout["with"]["persist-credentials"] is False
    execution = next(step for step in job["steps"] if "run" in step)
    assert "--isolated --no-project" in execution["run"]
    assert "--with polars==2.0.0 --with pydantic==2.14.0" in execution["run"]
    assert "--with-editable ./src/agilab/lib/agi-web" in execution["run"]
    assert execution["env"]["QUALIFICATION_SOURCE_SHA"] == "${{ github.sha }}"
    upload = job["steps"][-1]
    assert upload["if"] == "always()"
    assert upload["with"]["if-no-files-found"] == "error"
    assert "secrets." not in text and "pull_request_target" not in text


def test_uv_isolated_distribution_outside_interpreter_prefix_is_supported(
    monkeypatch, tmp_path
):
    distribution_root = tmp_path / "uv-archive"
    modules = {}
    for name, version in qualification.EXPECTED_VERSIONS.items():
        path = distribution_root / name / "__init__.py"
        path.parent.mkdir(parents=True)
        path.write_text("# exact distribution bytes", encoding="utf-8")
        modules[name] = SimpleNamespace(__version__=version, __file__=str(path))
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "uv-build-interpreter"))
    monkeypatch.setattr(
        qualification.importlib, "import_module", lambda name: modules[name]
    )
    monkeypatch.setattr(
        qualification.importlib.metadata,
        "distribution",
        lambda name: SimpleNamespace(
            version=qualification.EXPECTED_VERSIONS[name],
            locate_file=lambda path: distribution_root / path,
        ),
    )
    result = qualification.dependency_attestation()
    assert result["polars"]["module_file"] == "$DISTRIBUTION_ROOT/polars/__init__.py"
    assert result["pydantic"]["version"] == "2.14.0"


def test_deselection_cannot_pass_matching_junit(tmp_path):
    plugin = finished_plugin()
    plugin.counts["deselected"] = 1
    junit = tmp_path / "qualification.xml"
    write_junit(junit)
    with pytest.raises(qualification.QualificationError, match="tests_deselected"):
        qualification.validate_results(plugin, 0, junit)


def test_all_eight_named_test_files_must_execute(tmp_path):
    plugin = finished_plugin()
    plugin.collected_by_file.pop(qualification.TEST_PATHS[-1])
    plugin.collected -= 1
    plugin.counts["passed"] -= 1
    junit = tmp_path / "qualification.xml"
    write_junit(junit, tests=plugin.collected)
    with pytest.raises(
        qualification.QualificationError, match="incomplete_test_file_coverage"
    ):
        qualification.validate_results(plugin, 0, junit)


def test_inherited_pytest_filter_and_plugin_cannot_reduce_real_run(tmp_path):
    for name in ("test_first.py", "test_second.py"):
        (tmp_path / name).write_text(
            "def test_one():\n    assert True\n"
            if name == "test_first.py"
            else "def test_two():\n    assert True\n",
            encoding="utf-8",
        )
    output = tmp_path / "actual-pytest-evidence"
    script = """
import importlib.util
from pathlib import Path
import sys
spec = importlib.util.spec_from_file_location("qualification", sys.argv[1])
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
helper.TEST_PATHS = ("test_first.py", "test_second.py")
helper.source_head = lambda *args: "a" * 40
helper.source_hashes = lambda *args: {"fixture.py": "fixture"}
helper.sdk_attestation = lambda *args: {"fixture": {"module_file": "fixture.py"}}
helper.dependency_attestation = lambda: {
    "polars": {"version": "2.0.0"}, "pydantic": {"version": "2.14.0"}
}
raise SystemExit(helper.run_qualification(
    Path(sys.argv[2]), Path(sys.argv[3]), "a" * 40,
    ".".join(helper.platform.python_version_tuple()[:2]),
    helper.platform.system(),
))
"""
    environment = dict(os.environ)
    environment.update(
        PYTEST_ADDOPTS="-k test_one",
        PYTEST_PLUGINS="qualification_plugin_that_does_not_exist",
        PYTHONDONTWRITEBYTECODE="1",
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(ROOT / qualification.HELPER_PATH),
            str(tmp_path),
            str(output),
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(
        (output / "agilab-polars-2-runtime-qualification.json").read_text()
    )
    assert report["status"] == "passed"
    assert report["collected"] == 2
    assert report["collected_by_file"] == {"test_first.py": 1, "test_second.py": 1}
    assert report["test_outcomes"] == {"passed": 2}


def test_workflow_passes_matrix_python_to_uv_before_resolution():
    workflow = yaml.safe_load((ROOT / qualification.WORKFLOW_PATH).read_text())
    job = workflow["jobs"]["polars-2-runtime-qualification"]
    execution = next(step for step in job["steps"] if "run" in step)
    assert execution["env"]["QUALIFICATION_PYTHON"] == "${{ matrix.python }}"
    assert '--python "$QUALIFICATION_PYTHON"' in execution["run"]
    assert '--expected-python "$QUALIFICATION_PYTHON"' in execution["run"]
    assert execution["run"].index('--python "$QUALIFICATION_PYTHON"') < execution[
        "run"
    ].index("--with-editable")
