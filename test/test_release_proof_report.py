from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path("tools/release_proof_report.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "release_proof_report_test_module",
        MODULE_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_release_proof_manifest_renders_checked_in_page() -> None:
    module = _load_module()

    report = module.build_report(
        manifest_path=Path("docs/source/data/release_proof.toml"),
        output_path=Path("docs/source/release-proof.rst"),
    )

    assert report["status"] == "pass"
    assert report["summary"]["failed"] == 0
    assert {check["id"] for check in report["checks"]} >= {
        "pyproject_version",
        "pypi_badge_version",
        "changelog_release",
        "readme_release_proof_link",
        "rendered_page",
    }


def test_release_proof_cli_check_emits_machine_readable_report(capsys) -> None:
    module = _load_module()

    assert module.main(["--check", "--compact"]) == 0

    payload = json.loads(capsys.readouterr().out)
    manifest = module.load_manifest(Path("docs/source/data/release_proof.toml"))
    assert payload["schema"] == module.SCHEMA
    assert payload["status"] == "pass"
    assert payload["release"]["package_version"] == manifest["release"]["package_version"]


def test_release_proof_renderer_fails_unknown_template_key(tmp_path: Path) -> None:
    module = _load_module()
    manifest = module.load_manifest(Path("docs/source/data/release_proof.toml"))
    manifest["proof_command"]["commands"] = ["python -m pip install {missing_key}"]

    try:
        module.render_release_proof(manifest)
    except KeyError as exc:
        assert "missing_key" in str(exc)
    else:
        raise AssertionError("unknown template key should fail rendering")
