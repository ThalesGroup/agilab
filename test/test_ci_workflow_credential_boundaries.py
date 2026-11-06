import json
import re
import shlex
from pathlib import Path

import yaml

WORKFLOW_ROOT = Path(".github/workflows")
LOCKED_TOOLS_INSTALLER = Path("tools/setup_locked_python_tools.py")
LOCK_INTEGRITY_WORKFLOW = WORKFLOW_ROOT / "ci-tool-lock-integrity.yml"
REQUIREMENTS_ROOT = Path(".github/requirements")
SETUP_UV_SHA = "68559e99cc807c1eb7e9238fd43a15bba460eec2"

LOCKED_TOOL_JOBS = {
    ("pypi-publish.yaml", "release-plan"): ".github/requirements/ci-publish.txt",
    (
        "pypi-publish.yaml",
        "build-library-packages",
    ): ".github/requirements/ci-publish.txt",
    ("pypi-publish.yaml", "build-agilab"): ".github/requirements/ci-publish.txt",
    ("pypi-publish.yaml", "sync-hf-space"): ".github/requirements/ci-hf-release.txt",
    (
        "pypi-publish.yaml",
        "publish-release-proof",
    ): ".github/requirements/ci-hf-release.txt",
    (
        "pypi-pending-trusted-publisher.yaml",
        "register",
    ): ".github/requirements/ci-pypi-web.txt",
    (
        "pypi-release-retention.yaml",
        "cleanup-plan",
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

EXPECTED_DIRECT_PINS = {
    "ci-free-threaded-coverage.in": ["coverage==7.16.1"],
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
        "twine==7.0.0",
    ],
    "ci-pypi-web.in": [
        "packaging==26.2",
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


def _locked_setup_requirements(step: dict) -> str | None:
    command = shlex.split(str(step.get("run", "")))
    if "tools/setup_locked_python_tools.py" not in command:
        return None
    assert command[:3] == [
        "python", "tools/setup_locked_python_tools.py", "--requirements",
    ]
    assert len(command) == 5 and command[4] == "--github-env"
    return command[3]


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
    workflow_path = WORKFLOW_ROOT / "pypi-pending-trusted-publisher.yaml"
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

def test_cleanup_plan_dispatch_has_no_credentials_or_destructive_authority() -> None:
    workflow = _load_yaml(WORKFLOW_ROOT / "pypi-release-retention.yaml")
    trigger = workflow.get("on") or workflow.get(True)
    inputs = trigger["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"delete_releases"}
    assert inputs["delete_releases"]["type"] == "string"
    assert inputs["delete_releases"]["required"] is True
    assert workflow["permissions"] == {"contents": "read"}
    serialized = json.dumps(workflow)
    assert "secrets." not in serialized
    assert "github.token" not in serialized
    assert "id-token" not in serialized
    assert set(workflow["jobs"]) == {"cleanup-plan"}

    job = workflow["jobs"]["cleanup-plan"]
    assert job["runs-on"] == "ubuntu-latest"
    assert "environment" not in job
    assert job.get("permissions", workflow["permissions"]) == {"contents": "read"}
    run_text = "\n".join(str(step.get("run", "")) for step in job["steps"])
    assert 'args = ["--repo-root", ".", "--dry-run", "--json"]' in run_text
    assert "--confirm-delete" not in run_text
    assert "--do-it" not in run_text


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
        "publish-release-proof",
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
        "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333",
        "pypa/gh-action-pypi-publish@7245906fb61fa33a13554f9d5fb856fe61758086",
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
            and "tools/setup_locked_python_tools.py" not in str(step.get("run", ""))
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
        "release-approval",
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
        "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333",
        "pypa/gh-action-pypi-publish@7245906fb61fa33a13554f9d5fb856fe61758086",
    ]
    assert "environment" not in test_job
    publish_step = test_job["steps"][-1]
    assert publish_step["with"]["password"] == (
        "${{ secrets.TEST_PYPI_API_TOKEN || secrets.TEST_PYPI_SECRET }}"
    )
    assert publish_step["with"]["attestations"] is False
    assert publish_step["with"]["print-hash"] is True
    assert "TWINE_PASSWORD" not in json.dumps(test_pypi["jobs"], sort_keys=True)


def test_hf_secret_and_github_release_write_credentials_are_compartmentalized() -> None:
    release = _load_yaml(WORKFLOW_ROOT / "pypi-publish.yaml")
    hf_sync = release["jobs"]["sync-hf-space"]
    proof = release["jobs"]["publish-release-proof"]

    assert hf_sync["permissions"] == {"contents": "read"}
    assert "HF_TOKEN" in json.dumps(hf_sync, sort_keys=True)
    assert "HF_TOKEN" not in json.dumps(proof, sort_keys=True)
    assert proof["permissions"] == {
        "actions": "read",
        "artifact-metadata": "write",
        "attestations": "write",
        "contents": "write",
        "id-token": "write",
        "pull-requests": "write",
    }
    assert set(proof["needs"]) == {
        "release-approval",
        "release-plan",
        "sync-hf-space",
    }
    assert proof["env"]["PROVENANCE_PACKAGES"] == (
        "${{ needs.release-plan.outputs.provenance_packages }}"
    )
    assert "needs.sync-hf-space.outputs.hf_space_commit" in json.dumps(
        proof, sort_keys=True
    )


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
            if _locked_setup_requirements(step) == requirements
        ]
        assert len(setup_indexes) == 1, f"{workflow_path}:{job_name}:{requirements}"
        pinned_setup = [
            step for step in steps[:setup_indexes[0]]
            if step.get("uses") == f"astral-sh/setup-uv@{SETUP_UV_SHA}"
        ]
        assert pinned_setup, f"{workflow_path}:{job_name}"
        assert pinned_setup[-1]["with"]["version"] == "0.10.7"
        assert pinned_setup[-1]["with"]["prune-cache"] is True

        credential_indexes = [
            index
            for index, step in enumerate(steps)
            if _contains_credential(step)
        ]
        if credential_indexes:
            assert setup_indexes[0] < min(credential_indexes), (
                f"{workflow_path}:{job_name}"
            )


def test_local_locked_installer_and_manual_workflow_preserve_unprivileged_smokes() -> None:
    assert LOCKED_TOOLS_INSTALLER.is_file()
    workflow = _load_yaml(LOCK_INTEGRITY_WORKFLOW)
    trigger = workflow.get("on") or workflow.get(True)
    serialized = json.dumps(workflow)
    assert set(trigger) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    assert "secrets." not in serialized and "id-token" not in serialized
    job = workflow["jobs"]["verify-locks"]
    assert job["runs-on"] == "ubuntu-latest"
    assert job["permissions"] == {"contents": "read"}
    steps = job["steps"]
    setup_requirements = [
        requirements for step in steps
        if (requirements := _locked_setup_requirements(step)) is not None
    ]
    expected_requirements = {
        path.as_posix() for path in REQUIREMENTS_ROOT.glob("ci-*.txt")
    }
    assert setup_requirements[0] == ".github/requirements/ci-lock-audit.txt"
    assert len(setup_requirements) == len(set(setup_requirements))
    assert set(setup_requirements) == expected_requirements
    for index, step in enumerate(steps):
        if _locked_setup_requirements(step):
            pinned_uv = steps[index - 1]
            assert pinned_uv["uses"] == f"astral-sh/setup-uv@{SETUP_UV_SHA}"
            assert pinned_uv["with"] == {"version": "0.10.7", "prune-cache": True}
    run_text = "\n".join(str(step.get("run", "")) for step in steps)
    assert "python tools/ci_tool_lock_integrity.py" in run_text
    assert "--requirements-dir .github/requirements" in run_text
    import_smokes = [
        step for step in steps if step.get("name", "").startswith("Import-smoke")
    ]
    assert import_smokes
    assert all(step["env"]["PIP_NO_INDEX"] == "1" for step in import_smokes)
    for module in (
        "pypi_publish", "pypi_pending_trusted_publisher",
        "pypi_release_retention", "hf_space_release_sync",
    ):
        assert f"import tools.{module}" in run_text


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
