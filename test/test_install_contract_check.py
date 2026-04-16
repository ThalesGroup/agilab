from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/install_contract_check.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("install_contract_check_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_manifest(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def test_analyze_contract_reports_safe_when_manifests_align(tmp_path) -> None:
    module = _load_module()
    app_root = tmp_path / "demo_project"
    worker_source = app_root / "src" / "demo_worker" / "pyproject.toml"
    worker_copy = tmp_path / "wenv" / "demo_worker" / "pyproject.toml"
    local_dep = tmp_path / "deps" / "shared"
    local_dep.mkdir(parents=True, exist_ok=True)

    _write_manifest(
        app_root / "pyproject.toml",
        """
[project]
name = "demo_project"
dependencies = ["numpy>=1.26"]
""",
    )
    _write_manifest(
        worker_source,
        """
[project]
name = "demo_worker"
dependencies = ["numpy>=1.26", "shared"]
""",
    )
    _write_manifest(
        worker_copy,
        f"""
[project]
name = "demo_worker"
dependencies = ["numpy>=1.26", "shared"]

[tool.uv.sources]
shared = {{ path = "{local_dep}" }}
""",
    )

    report = module.analyze_contract(app_path=app_root, worker_copy=worker_copy)

    assert report.status == module.SAFE_STATUS
    assert not any(finding.severity == "error" for finding in report.findings)


def test_analyze_contract_flags_missing_worker_source_as_app_local_issue(tmp_path) -> None:
    module = _load_module()
    app_root = tmp_path / "demo_project"
    worker_copy = tmp_path / "wenv" / "demo_worker" / "pyproject.toml"

    _write_manifest(
        app_root / "pyproject.toml",
        """
[project]
name = "demo_project"
dependencies = ["numpy>=1.26"]
""",
    )
    _write_manifest(
        worker_copy,
        """
[project]
name = "demo_worker"
dependencies = ["numpy>=1.26"]
""",
    )

    report = module.analyze_contract(app_path=app_root, worker_copy=worker_copy)

    assert report.status == module.APP_LOCAL_STATUS
    assert any(finding.key == "worker-source-discovery" for finding in report.findings)


def test_analyze_contract_flags_exact_pin_injection_as_shared_core_issue(tmp_path) -> None:
    module = _load_module()
    app_root = tmp_path / "demo_project"
    worker_source = app_root / "src" / "demo_worker" / "pyproject.toml"
    worker_copy = tmp_path / "wenv" / "demo_worker" / "pyproject.toml"

    _write_manifest(
        app_root / "pyproject.toml",
        """
[project]
name = "demo_project"
dependencies = ["scipy>=1.15.2,<1.17"]
""",
    )
    _write_manifest(
        worker_source,
        """
[project]
name = "demo_worker"
dependencies = ["scipy>=1.15.2,<1.17"]
""",
    )
    _write_manifest(
        worker_copy,
        """
[project]
name = "demo_worker"
dependencies = ["scipy==1.16.1"]
""",
    )

    report = module.analyze_contract(app_path=app_root, worker_copy=worker_copy)

    assert report.status == module.SHARED_CORE_STATUS
    finding = next(finding for finding in report.findings if finding.key == "injected-exact-pins")
    assert "scipy: copied=scipy==1.16.1" in finding.details


def test_analyze_contract_flags_stale_uv_sources_as_shared_core_issue(tmp_path) -> None:
    module = _load_module()
    app_root = tmp_path / "demo_project"
    worker_source = app_root / "src" / "demo_worker" / "pyproject.toml"
    worker_copy = tmp_path / "wenv" / "demo_worker" / "pyproject.toml"

    _write_manifest(
        app_root / "pyproject.toml",
        """
[project]
name = "demo_project"
dependencies = ["demo-lib"]
""",
    )
    _write_manifest(
        worker_source,
        """
[project]
name = "demo_worker"
dependencies = ["demo-lib"]
""",
    )
    _write_manifest(
        worker_copy,
        """
[project]
name = "demo_worker"
dependencies = ["demo-lib"]

[tool.uv.sources]
demo-lib = { path = "_uv_sources/demo-lib" }
""",
    )

    report = module.analyze_contract(app_path=app_root, worker_copy=worker_copy)

    assert report.status == module.SHARED_CORE_STATUS
    finding = next(finding for finding in report.findings if finding.key == "stale-uv-sources")
    assert "demo-lib: _uv_sources/demo-lib" in finding.details


def test_analyze_contract_flags_missing_local_core_paths_for_repo_app(tmp_path, monkeypatch) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    app_root = repo_root / "src" / "agilab" / "apps" / "demo_project"
    worker_source = app_root / "src" / "demo_worker" / "pyproject.toml"
    worker_copy = tmp_path / "wenv" / "demo_worker" / "pyproject.toml"

    monkeypatch.setattr(module, "REPO_ROOT", repo_root.resolve(strict=False))

    _write_manifest(
        app_root / "pyproject.toml",
        """
[project]
name = "demo_project"
dependencies = ["numpy>=1.26"]
""",
    )
    _write_manifest(
        worker_source,
        """
[project]
name = "demo_worker"
dependencies = ["agi-env", "agi-node", "numpy>=1.26"]
""",
    )
    _write_manifest(
        worker_copy,
        """
[project]
name = "demo_worker"
dependencies = ["agi-env", "agi-node", "numpy>=1.26"]
""",
    )

    report = module.analyze_contract(app_path=app_root, worker_copy=worker_copy)

    assert report.status == module.SHARED_CORE_STATUS
    finding = next(finding for finding in report.findings if finding.key == "missing-local-core-paths")
    assert "agi-env: missing [tool.uv.sources].agi-env.path" in finding.details
    assert "agi-node: missing [tool.uv.sources].agi-node.path" in finding.details


def test_main_json_output_and_exit_code_for_shared_core_issue(tmp_path, capsys) -> None:
    module = _load_module()
    app_root = tmp_path / "demo_project"
    worker_source = app_root / "src" / "demo_worker" / "pyproject.toml"
    worker_copy = tmp_path / "wenv" / "demo_worker" / "pyproject.toml"

    _write_manifest(
        app_root / "pyproject.toml",
        """
[project]
name = "demo_project"
dependencies = ["scipy>=1.15.2,<1.17"]
""",
    )
    _write_manifest(
        worker_source,
        """
[project]
name = "demo_worker"
dependencies = ["scipy>=1.15.2,<1.17"]
""",
    )
    _write_manifest(
        worker_copy,
        """
[project]
name = "demo_worker"
dependencies = ["scipy==1.16.1"]
""",
    )

    exit_code = module.main(
        [
            "--app-path",
            str(app_root),
            "--worker-copy",
            str(worker_copy),
            "--json",
        ]
    )

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == module.SHARED_CORE_STATUS
    assert any(finding["key"] == "injected-exact-pins" for finding in payload["findings"])
