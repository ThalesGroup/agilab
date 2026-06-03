from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


MODULE_PATH = Path("tools/beta_readiness.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("beta_readiness_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_package_pyproject(root: Path, rel_path: str, classifier: str) -> None:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    module = _load_module()
    package_module = module.TYPING_POLICY_PACKAGE_MODULES.get(rel_path)
    typing_policy = (
        "\n".join(
            [
                "[tool.mypy]",
                "disallow_untyped_defs = true",
                "",
            ]
        )
        if package_module is not None
        else ""
    )
    path.write_text(
        "\n".join(
            [
                "[project]",
                'name = "demo"',
                f'classifiers = ["{classifier}"]',
                "",
                typing_policy,
            ]
        ),
        encoding="utf-8",
    )


def _write_release_package_set(root: Path, classifier: str) -> None:
    module = _load_module()
    for rel_path in module.RELEASE_PACKAGE_PYPROJECTS:
        _write_package_pyproject(root, rel_path, classifier)


def _readme_maturity_text(*, production_status: str = "Experimental") -> str:
    return "\n".join(
        [
            "# AGILAB",
            "",
            "### Maturity snapshot",
            "",
            "| Capability | Status |",
            "|---|---|",
            "| Local run | Stable |",
            "| Distributed (Dask) | Stable |",
            "| UI Streamlit | Beta |",
            "| MLflow | Beta |",
            f"| Production | {production_status} |",
            "",
            "AGILAB is most mature in the bridge between notebook experimentation and",
            "reproducible AI applications: local execution, environment control, and",
            "analysis. Distributed execution is mature in the core runtime; remote cluster",
            "mounts, credentials, and hardware stacks remain environment-dependent.",
            "Production-grade MLOps features are delivered through integrations and are not",
            "yet a packaged platform claim.",
            "",
        ]
    )


def _write_required_docs(root: Path, text: str = "Beta readiness\n") -> None:
    module = _load_module()
    for rel_path in module.PUBLIC_DOC_FILES:
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _readme_maturity_text() if rel_path == "README.md" else text
        path.write_text(payload, encoding="utf-8")


def test_package_classifier_planning_mode_accepts_alpha_with_info(tmp_path: Path) -> None:
    module = _load_module()
    _write_release_package_set(tmp_path, module.ALPHA_CLASSIFIER)

    check = module.check_package_classifiers(tmp_path, final=False)

    assert check.success is True
    assert check.severity == "info"
    assert "still say Alpha" in check.detail


def test_package_classifier_final_mode_requires_beta(tmp_path: Path) -> None:
    module = _load_module()
    _write_release_package_set(tmp_path, module.ALPHA_CLASSIFIER)

    check = module.check_package_classifiers(tmp_path, final=True)

    assert check.success is False
    assert "need beta classifiers" in check.detail


def test_public_app_tree_rejects_non_public_entries(tmp_path: Path) -> None:
    module = _load_module()
    apps = tmp_path / "src/agilab/apps"
    (apps / "builtin").mkdir(parents=True)
    (apps / "private_project").mkdir()

    check = module.check_public_app_tree(tmp_path)

    assert check.success is False
    assert check.evidence == ["private_project"]


def test_public_app_tree_rejects_tracked_non_public_entries(tmp_path: Path) -> None:
    module = _load_module()

    def _runner(argv):
        assert argv == ["git", "-C", str(tmp_path), "ls-files", "-z", "--", "src/agilab/apps"]
        return subprocess.CompletedProcess(
            argv,
            0,
            "src/agilab/apps/builtin/flight_telemetry_project/pyproject.toml\0"
            "src/agilab/apps/private_project/pyproject.toml\0",
            "",
        )

    check = module.check_public_app_tree(tmp_path, _runner)

    assert check.success is False
    assert check.evidence == ["private_project"]
    assert "tracked release entries" in check.detail


def test_public_app_tree_allows_ignored_local_private_entries(tmp_path: Path) -> None:
    module = _load_module()
    apps = tmp_path / "src/agilab/apps"
    (apps / "builtin").mkdir(parents=True)
    (apps / "private_project").mkdir()

    def _runner(argv):
        if argv == ["git", "-C", str(tmp_path), "ls-files", "-z", "--", "src/agilab/apps"]:
            return subprocess.CompletedProcess(
                argv,
                0,
                "src/agilab/apps/builtin/flight_telemetry_project/pyproject.toml\0",
                "",
            )
        if argv == ["git", "-C", str(tmp_path), "check-ignore", "--quiet", "src/agilab/apps/private_project"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        raise AssertionError(f"unexpected command: {argv}")

    check = module.check_public_app_tree(tmp_path, _runner)

    assert check.success is True
    assert check.evidence == []
    assert "not release-blocking" in check.detail
    assert "private_project" in check.detail


def test_typing_policy_accepts_root_mypy_and_module_override(tmp_path: Path) -> None:
    module = _load_module()
    _write_release_package_set(tmp_path, module.BETA_CLASSIFIER)
    agi_core = tmp_path / "src/agilab/core/agi-core/pyproject.toml"
    agi_core.write_text(
        "\n".join(
            [
                "[project]",
                'name = "agi-core"',
                f'classifiers = ["{module.BETA_CLASSIFIER}"]',
                "",
                "[[tool.mypy.overrides]]",
                'module = "agi_core.*"',
                "disallow_untyped_defs = true",
                "",
            ]
        ),
        encoding="utf-8",
    )

    check = module.check_typing_policy(tmp_path)

    assert check.success is True


def test_typing_policy_rejects_missing_public_package_policy(tmp_path: Path) -> None:
    module = _load_module()
    _write_release_package_set(tmp_path, module.BETA_CLASSIFIER)
    (tmp_path / "src/agilab/core/agi-env/pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "agi-env"',
                f'classifiers = ["{module.BETA_CLASSIFIER}"]',
                "",
            ]
        ),
        encoding="utf-8",
    )

    check = module.check_typing_policy(tmp_path)

    assert check.success is False
    assert "agi-env/pyproject.toml: disallow_untyped_defs not enforced for agi_env" in check.detail


def test_public_maturity_positioning_accepts_audited_beta_scope(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / "README.md").write_text(_readme_maturity_text(), encoding="utf-8")

    check = module.check_public_maturity_positioning(tmp_path)

    assert check.success is True
    assert check.evidence == []
    assert "audited beta scope" in check.detail


def test_public_maturity_positioning_rejects_production_overclaim(tmp_path: Path) -> None:
    module = _load_module()
    (tmp_path / "README.md").write_text(
        _readme_maturity_text(production_status="Stable"),
        encoding="utf-8",
    )

    check = module.check_public_maturity_positioning(tmp_path)

    assert check.success is False
    assert "Production: expected Experimental, found Stable" in check.detail


def test_final_gate_requires_network_and_clean_tree(tmp_path: Path) -> None:
    module = _load_module()
    _write_release_package_set(tmp_path, module.BETA_CLASSIFIER)
    _write_required_docs(tmp_path)
    apps = tmp_path / "src/agilab/apps"
    (apps / "builtin").mkdir(parents=True)
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools/pypi_publish.py").write_text(
        repr(list(module.RELEASE_PREFLIGHT_PROFILES)),
        encoding="utf-8",
    )

    def _runner(argv):
        if argv == ["git", "status", "--porcelain=v1"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(argv, 0, "abc\n", "")
        if argv == ["git", "rev-parse", "origin/main"]:
            return subprocess.CompletedProcess(argv, 0, "abc\n", "")
        if argv == ["git", "-C", str(tmp_path), "ls-files", "-z", "--", "src/agilab/apps"]:
            return subprocess.CompletedProcess(
                argv,
                0,
                "src/agilab/apps/builtin/flight_telemetry_project/pyproject.toml\0",
                "",
            )
        raise AssertionError(f"unexpected command: {argv}")

    summary = module.run_gate(
        repo_root=tmp_path,
        final=True,
        include_network=False,
        runner=_runner,
    )

    assert summary.success is False
    assert any(check.name == "Hugging Face Space public" and not check.success for check in summary.checks)


def test_hf_space_public_uses_runtime_raw_sha() -> None:
    module = _load_module()

    def _runner(argv):
        assert argv == ["hf", "spaces", "info", "jpmorard/agilab", "--format", "json"]
        return subprocess.CompletedProcess(
            argv,
            0,
            (
                '{"private": false, "sha": "abc123", '
                '"runtime": {"stage": "RUNNING", "raw": {"sha": "abc123"}}}'
            ),
            "",
        )

    check = module.check_hf_space_public(_runner, final=True)

    assert check.success is True
    assert "runtime_sha=abc123" in check.detail


def test_render_human_lists_required_final_commands(tmp_path: Path) -> None:
    module = _load_module()
    summary = module.GateSummary(
        final=False,
        include_network=False,
        success=True,
        checks=[module.GateCheck("demo", True, "ok")],
        required_commands=["uv run demo"],
    )

    rendered = module.render_human(summary)

    assert "verdict: PASS" in rendered
    assert "uv run demo" in rendered
