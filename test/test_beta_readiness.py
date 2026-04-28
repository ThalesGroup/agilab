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
    path.write_text(
        "\n".join(
            [
                "[project]",
                'name = "demo"',
                f'classifiers = ["{classifier}"]',
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_release_package_set(root: Path, classifier: str) -> None:
    module = _load_module()
    for rel_path in module.RELEASE_PACKAGE_PYPROJECTS:
        _write_package_pyproject(root, rel_path, classifier)


def _write_required_docs(root: Path, text: str = "Beta readiness\n") -> None:
    module = _load_module()
    for rel_path in module.PUBLIC_DOC_FILES:
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


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
