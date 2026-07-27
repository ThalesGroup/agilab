import json
import re
from pathlib import Path

import yaml

WORKFLOW_ROOT = Path(".github/workflows")
LOCKED_TOOLS_ACTION = Path(".github/actions/setup-locked-python-tools/action.yml")
LOCK_INTEGRITY_WORKFLOW = WORKFLOW_ROOT / "ci-tool-lock-integrity.yml"
REQUIREMENTS_ROOT = Path(".github/requirements")
SETUP_UV_SHA = "c771a70e6277c0a99b617c7a806ffedaca235ff9"

LOCKED_TOOL_JOBS = {
    ("pypi-publish.yaml", "release-plan"): ".github/requirements/ci-publish.txt",
    (
        "pypi-publish.yaml",
        "build-library-packages",
    ): ".github/requirements/ci-publish.txt",
    ("pypi-publish.yaml", "build-agilab"): ".github/requirements/ci-publish.txt",
    (
        "pypi-publish.yaml",
        "pypi-release-retention",
    ): ".github/requirements/ci-pypi-web.txt",
    ("pypi-publish.yaml", "sync-hf-space"): ".github/requirements/ci-hf-release.txt",
    (
        "pypi-pending-trusted-publisher.yaml",
        "register",
    ): ".github/requirements/ci-pypi-web.txt",
    (
        "pypi-release-retention.yaml",
        "retention",
    ): ".github/requirements/ci-pypi-web.txt",
    (
        "test-pypi-publish.yaml",
        "build-testpypi",
    ): ".github/requirements/ci-publish.txt",
}

CREDENTIAL_HARDENED_WORKFLOWS = (
    "pypi-pending-trusted-publisher.yaml",
    "pypi-publish.yaml",
    "pypi-release-retention.yaml",
    "test-pypi-publish.yaml",
)

LOCK_INTEGRITY_TRIGGER_PATHS = {
    ".github/workflows/pypi-pending-trusted-publisher.yaml",
    ".github/workflows/pypi-publish.yaml",
    ".github/workflows/pypi-release-retention.yaml",
    ".github/workflows/test-pypi-publish.yaml",
    "dev",
    "tools/agilab_dev.py",
    "tools/ci_tool_lock_integrity.py",
    "tools/hf_space_release_sync.py",
    "tools/package_split_contract.py",
    "tools/pypi_*.py",
    "tools/release_*.py",
    "tools/sync_docs_source.py",
}

EXPECTED_DIRECT_PINS = {
    "ci-hf-release.in": [
        "click==8.4.2",
        "huggingface-hub==1.24.0",
        "packaging==26.2",
        "tomlkit==0.15.1",
    ],
    "ci-publish.in": [
        "packaging==26.2",
        "pyyaml==6.0.3",
        "tomlkit==0.15.1",
        "twine==6.2.0",
    ],
    "ci-pypi-web.in": [
        "packaging==26.2",
        "pypi-cleanup==0.1.10",
        "requests==2.34.2",
    ],
}


def _workflow_paths() -> list[Path]:
    return sorted({*WORKFLOW_ROOT.glob("*.yml"), *WORKFLOW_ROOT.glob("*.yaml")})


def _load_yaml(path: Path) -> dict:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict), path
    return document


def _contains_credential(value: object) -> bool:
    serialized = json.dumps(value, sort_keys=True)
    return "secrets." in serialized or "github.token" in serialized


def test_credentialed_workflows_do_not_run_mutable_pip_installs() -> None:
    install_pattern = re.compile(r"(?:python\s+-m\s+)?pip\s+install|uv\s+pip\s+install")

    for path in _workflow_paths():
        text = path.read_text(encoding="utf-8")
        if "secrets." not in text and "id-token: write" not in text:
            continue
        assert install_pattern.search(text) is None, path


def test_workflow_credentials_are_step_scoped_and_shell_tracing_is_disabled() -> None:
    for path in _workflow_paths():
        text = path.read_text(encoding="utf-8")
        if not any(
            marker in text for marker in ("secrets.", "github.token", "id-token: write")
        ):
            continue

        workflow = _load_yaml(path)
        assert not _contains_credential(workflow.get("env", {})), path
        for job_name, job in workflow.get("jobs", {}).items():
            assert not _contains_credential(job.get("env", {})), f"{path}:{job_name}"
            for step in job.get("steps", []):
                if not _contains_credential(step.get("env", {})):
                    continue
                run = str(step.get("run", ""))
                assert "set -x" not in run, f"{path}:{job_name}:{step.get('name')}"
                assert "set -eux" not in run, f"{path}:{job_name}:{step.get('name')}"


def test_dispatch_inputs_are_not_interpolated_in_credentialed_run_scripts() -> None:
    direct_input = re.compile(r"\$\{\{\s*(?:inputs|github\.event\.inputs)\.[^}]+\}\}")

    for workflow_name in CREDENTIAL_HARDENED_WORKFLOWS:
        workflow_path = WORKFLOW_ROOT / workflow_name
        workflow = _load_yaml(workflow_path)
        for job_name, job in workflow["jobs"].items():
            oidc_enabled = job.get("permissions", {}).get("id-token") == "write"
            for step in job.get("steps", []):
                run = str(step.get("run", ""))
                credentialed = oidc_enabled or _contains_credential(step.get("env", {}))
                if credentialed and run:
                    assert direct_input.search(run) is None, (
                        f"{workflow_path}:{job_name}:{step.get('name')}"
                    )


def test_privileged_dispatch_runner_inputs_are_type_restricted() -> None:
    for workflow_name in (
        "pypi-pending-trusted-publisher.yaml",
        "pypi-release-retention.yaml",
    ):
        workflow_path = WORKFLOW_ROOT / workflow_name
        workflow = _load_yaml(workflow_path)
        trigger = workflow.get("on") or workflow.get(True)
        runner = trigger["workflow_dispatch"]["inputs"]["runner"]
        assert runner["type"] == "choice", workflow_path
        assert set(runner["options"]) == {"ubuntu-latest", "self-hosted"}, workflow_path


def test_privileged_dispatch_values_are_validated_before_secret_steps() -> None:
    pending = _load_yaml(WORKFLOW_ROOT / "pypi-pending-trusted-publisher.yaml")
    pending_steps = pending["jobs"]["register"]["steps"]
    pending_validation = next(
        step
        for step in pending_steps
        if step["name"] == "Validate pending publisher inputs"
    )
    pending_secret = next(
        step
        for step in pending_steps
        if step["name"] == "Register pending trusted publisher"
    )
    assert pending_steps.index(pending_validation) < pending_steps.index(pending_secret)
    assert "re.fullmatch" in pending_validation["run"]
    assert '--project-name "$PROJECT_NAME"' in pending_secret["run"]
    assert '--workflow-filename "$PUBLISHER_WORKFLOW"' in pending_secret["run"]
    assert '--environment "$PYPI_ENVIRONMENT"' in pending_secret["run"]

    retention = _load_yaml(WORKFLOW_ROOT / "pypi-release-retention.yaml")
    retention_steps = retention["jobs"]["retention"]["steps"]
    retention_validation = next(
        step for step in retention_steps if step["name"] == "Validate retention inputs"
    )
    retention_secret = next(
        step
        for step in retention_steps
        if step["name"]
        == "Delete older PyPI releases and keep the protected release only"
    )
    assert retention_steps.index(retention_validation) < retention_steps.index(
        retention_secret
    )
    assert "re.fullmatch" in retention_validation["run"]
    assert 'packages="$RELEASE_PACKAGES"' in retention_secret["run"]
    assert '--protect-version "$PROTECT_VERSION"' in retention_secret["run"]


def test_release_workflow_defaults_to_read_only_and_limits_oidc_jobs() -> None:
    workflow = _load_yaml(WORKFLOW_ROOT / "pypi-publish.yaml")

    assert workflow["permissions"] == {"contents": "read"}
    assert {
        job_name
        for job_name, job in workflow["jobs"].items()
        if job.get("permissions", {}).get("id-token") == "write"
    } == {
        "publish-agilab",
        "publish-dataset-release-assets",
        "publish-library-packages",
        "publish-release-assets",
    }


def test_release_checkouts_do_not_persist_implicit_github_credentials() -> None:
    for workflow_name in CREDENTIAL_HARDENED_WORKFLOWS:
        workflow_path = WORKFLOW_ROOT / workflow_name
        workflow = _load_yaml(workflow_path)
        checkouts = [
            step
            for job in workflow["jobs"].values()
            for step in job.get("steps", [])
            if str(step.get("uses", "")).startswith("actions/checkout@")
        ]
        assert checkouts, workflow_path
        assert all(
            step.get("with", {}).get("persist-credentials") is False
            for step in checkouts
        ), workflow_path

    test_pypi = _load_yaml(WORKFLOW_ROOT / "test-pypi-publish.yaml")
    assert test_pypi["jobs"]["build-testpypi"]["permissions"] == {"contents": "read"}
    assert test_pypi["jobs"]["publish-testpypi"]["permissions"] == {"contents": "read"}


def test_distribution_publish_jobs_do_not_execute_checkout_or_local_code() -> None:
    release = _load_yaml(WORKFLOW_ROOT / "pypi-publish.yaml")
    test_pypi = _load_yaml(WORKFLOW_ROOT / "test-pypi-publish.yaml")
    allowed_release_actions = {
        "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
        "pypa/gh-action-pypi-publish@ba38be9e461d3875417946c167d0b5f3d385a247",
    }

    for job_name in ("publish-library-packages", "publish-agilab"):
        job = release["jobs"][job_name]
        assert job["permissions"] == {"contents": "read", "id-token": "write"}
        assert "environment" in job
        assert "!cancelled()" in job["if"], job_name
        assert "always()" not in job["if"], job_name
        assert all("run" not in step for step in job["steps"]), job_name
        assert {step["uses"] for step in job["steps"]} <= allowed_release_actions
        assert all(
            not str(step.get("uses", "")).startswith("actions/checkout@")
            and step.get("uses") != "./.github/actions/setup-locked-python-tools"
            for step in job["steps"]
        )

        downloads = [
            step
            for step in job["steps"]
            if str(step.get("uses", "")).startswith("actions/download-artifact@")
        ]
        assert len(downloads) == 1
        assert "run-id" not in downloads[0].get("with", {})
        assert "repository" not in downloads[0].get("with", {})
        assert "github-token" not in downloads[0].get("with", {})
        assert job["steps"][-1]["with"]["print-hash"] is True

    assert set(release["jobs"]["publish-library-packages"]["needs"]) == {
        "release-plan",
        "build-library-packages",
    }
    assert set(release["jobs"]["publish-agilab"]["needs"]) >= {
        "release-plan",
        "build-agilab",
    }

    test_job = test_pypi["jobs"]["publish-testpypi"]
    assert all("run" not in step for step in test_job["steps"])
    assert [step["uses"] for step in test_job["steps"]] == [
        "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
        "pypa/gh-action-pypi-publish@ba38be9e461d3875417946c167d0b5f3d385a247",
    ]
    assert "environment" not in test_job
    publish_step = test_job["steps"][-1]
    assert publish_step["with"]["password"] == (
        "${{ secrets.TEST_PYPI_API_TOKEN || secrets.TEST_PYPI_SECRET }}"
    )
    assert publish_step["with"]["attestations"] is False
    assert publish_step["with"]["print-hash"] is True
    assert "TWINE_PASSWORD" not in json.dumps(test_pypi["jobs"], sort_keys=True)


def test_unprivileged_build_jobs_own_checkout_build_and_artifact_upload() -> None:
    release = _load_yaml(WORKFLOW_ROOT / "pypi-publish.yaml")
    test_pypi = _load_yaml(WORKFLOW_ROOT / "test-pypi-publish.yaml")

    for job_name in ("build-library-packages", "build-agilab"):
        job = release["jobs"][job_name]
        serialized = json.dumps(job, sort_keys=True)
        assert job["permissions"] == {"contents": "read"}
        assert "environment" not in job
        assert "id-token" not in serialized
        assert "secrets." not in serialized
        assert "actions/checkout@" in serialized
        assert "actions/upload-artifact@" in serialized
        assert "uv --preview-features extra-build-dependencies build" in serialized
        uploads = [
            step
            for step in job["steps"]
            if str(step.get("uses", "")).startswith("actions/upload-artifact@")
        ]
        assert uploads
        assert all(step["with"]["overwrite"] is False for step in uploads)

    build_testpypi = test_pypi["jobs"]["build-testpypi"]
    serialized = json.dumps(build_testpypi, sort_keys=True)
    assert "environment" not in build_testpypi
    assert "secrets." not in serialized
    assert "id-token" not in serialized
    assert "--build-only" in serialized
    assert "actions/upload-artifact@" in serialized
    testpypi_upload = next(
        step
        for step in build_testpypi["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    )
    assert testpypi_upload["with"]["overwrite"] is False


def test_credentialed_tool_setup_is_locked_and_precedes_secret_steps() -> None:
    for (workflow_name, job_name), requirements in LOCKED_TOOL_JOBS.items():
        workflow_path = WORKFLOW_ROOT / workflow_name
        job = _load_yaml(workflow_path)["jobs"][job_name]
        steps = job["steps"]
        setup_indexes = [
            index
            for index, step in enumerate(steps)
            if step.get("uses") == "./.github/actions/setup-locked-python-tools"
            and step.get("with", {}).get("requirements") == requirements
        ]
        assert len(setup_indexes) == 1, f"{workflow_path}:{job_name}:{requirements}"

        credential_indexes = [
            index
            for index, step in enumerate(steps)
            if _contains_credential(step.get("env", {}))
        ]
        if credential_indexes:
            assert setup_indexes[0] < min(credential_indexes), (
                f"{workflow_path}:{job_name}"
            )


def test_locked_python_tools_action_uses_pinned_uv_and_hashed_installs() -> None:
    action = _load_yaml(LOCKED_TOOLS_ACTION)
    steps = action["runs"]["steps"]

    assert steps[0]["uses"] == f"astral-sh/setup-uv@{SETUP_UV_SHA}"
    assert steps[0]["with"]["version"] == "0.10.7"
    assert steps[0]["with"]["prune-cache"] is True
    install_step = steps[1]
    assert (
        'uv venv --python "$(command -v python)" "$environment_path"'
        in install_step["run"]
    )
    assert "uv pip install" in install_step["run"]
    assert "--require-hashes" in install_step["run"]
    assert "--no-build" in install_step["run"]
    assert "AGILAB_DEV_UV_PROJECT_ENVIRONMENT=%s" in install_step["run"]


def test_ci_tool_locks_have_a_path_scoped_unprivileged_install_smoke() -> None:
    workflow = _load_yaml(LOCK_INTEGRITY_WORKFLOW)
    trigger = workflow.get("on") or workflow.get(True)
    serialized = json.dumps(workflow)

    assert workflow["permissions"] == {"contents": "read"}
    assert "secrets." not in serialized
    assert "id-token" not in serialized
    assert "workflow_dispatch" in trigger
    for event_name in ("pull_request", "push"):
        paths = set(trigger[event_name]["paths"])
        assert ".github/actions/setup-locked-python-tools/**" in paths
        assert ".github/requirements/ci-*" in paths
        assert LOCK_INTEGRITY_TRIGGER_PATHS <= paths

    job = workflow["jobs"]["verify-locks"]
    assert job["permissions"] == {"contents": "read"}
    steps = job["steps"]
    lock_setups = [
        step
        for step in steps
        if step.get("uses") == "./.github/actions/setup-locked-python-tools"
    ]
    assert [step["with"]["requirements"] for step in lock_setups] == [
        ".github/requirements/ci-publish.txt",
        ".github/requirements/ci-pypi-web.txt",
        ".github/requirements/ci-hf-release.txt",
    ]
    run_text = "\n".join(str(step.get("run", "")) for step in steps)
    assert "python tools/ci_tool_lock_integrity.py" in run_text
    assert "--requirements-dir .github/requirements" in run_text
    import_smokes = [
        step for step in steps if step.get("name", "").startswith("Import-smoke")
    ]
    assert import_smokes
    assert all(step["env"]["PIP_NO_INDEX"] == "1" for step in import_smokes)
    assert "import tools.pypi_publish" in run_text
    assert "import tools.pypi_pending_trusted_publisher" in run_text
    assert "import tools.pypi_release_retention" in run_text
    assert "import tools.hf_space_release_sync" in run_text


def test_ci_tool_requirements_pin_and_hash_every_dependency() -> None:
    for input_name, expected in EXPECTED_DIRECT_PINS.items():
        input_path = REQUIREMENTS_ROOT / input_name
        lock_path = input_path.with_suffix(".txt")
        assert input_path.read_text(encoding="utf-8").splitlines() == expected

        lock_text = lock_path.read_text(encoding="utf-8")
        assert "--hash=sha256:" in lock_text
        requirement_lines = [
            line
            for line in lock_text.splitlines()
            if line and not line[0].isspace() and not line.startswith("#")
        ]
        assert requirement_lines
        assert all("==" in line for line in requirement_lines)
        for direct_pin in expected:
            assert re.search(
                rf"^{re.escape(direct_pin)}(?:\s|\\|$)", lock_text, re.MULTILINE
            )


def test_secret_bearing_pypi_publish_imports_are_preinstalled() -> None:
    bootstrap_pins = {"packaging==26.2", "tomlkit==0.15.1"}

    for input_name in ("ci-publish.in", "ci-hf-release.in"):
        pins = set(
            (REQUIREMENTS_ROOT / input_name).read_text(encoding="utf-8").splitlines()
        )
        assert bootstrap_pins <= pins, input_name
