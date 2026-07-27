import json
import re
from pathlib import Path

import yaml

WORKFLOW_ROOT = Path(".github/workflows")
LOCKED_TOOLS_ACTION = Path(".github/actions/setup-locked-python-tools/action.yml")
REQUIREMENTS_ROOT = Path(".github/requirements")
SETUP_UV_SHA = "11f9893b081a58869d3b5fccaea48c9e9e46f990"

LOCKED_TOOL_JOBS = {
    ("pypi-publish.yaml", "release-plan"): ".github/requirements/ci-publish.txt",
    (
        "pypi-publish.yaml",
        "publish-library-packages",
    ): ".github/requirements/ci-publish.txt",
    ("pypi-publish.yaml", "publish-agilab"): ".github/requirements/ci-publish.txt",
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
        "publish-testpypi",
    ): ".github/requirements/ci-publish.txt",
}

CREDENTIAL_HARDENED_WORKFLOWS = (
    "pypi-pending-trusted-publisher.yaml",
    "pypi-publish.yaml",
    "pypi-release-retention.yaml",
    "test-pypi-publish.yaml",
)

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
    assert test_pypi["jobs"]["publish-testpypi"]["permissions"] == {"contents": "read"}


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
    install_step = steps[1]
    assert (
        'uv venv --python "$(command -v python)" "$environment_path"'
        in install_step["run"]
    )
    assert "uv pip install" in install_step["run"]
    assert "--require-hashes" in install_step["run"]
    assert "--no-build" in install_step["run"]
    assert "AGILAB_DEV_UV_PROJECT_ENVIRONMENT=%s" in install_step["run"]


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
