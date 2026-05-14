from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path("tools/package_wheel_sanitizer.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("package_wheel_sanitizer_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_strip_packaged_core_uv_sources_removes_empty_source_section() -> None:
    module = _load_module()

    sanitized = module.strip_packaged_core_uv_sources(
        "\n".join(
            [
                "[project]",
                'name = "flight_telemetry_project"',
                'dependencies = ["agi-env", "agi-node"]',
                "",
                "[tool.uv.sources]",
                'agi-env = { path = "../../../core/agi-env", editable = true }',
                'agi-node = { path = "../../../core/agi-node", editable = true }',
                "",
                "[build-system]",
                'requires = ["setuptools"]',
                "",
            ]
        )
    )

    assert "[tool.uv.sources]" not in sanitized
    assert 'dependencies = ["agi-env", "agi-node"]' in sanitized
    assert "[build-system]" in sanitized


def test_strip_packaged_core_uv_sources_preserves_non_core_sources() -> None:
    module = _load_module()

    sanitized = module.strip_packaged_core_uv_sources(
        "\n".join(
            [
                "[tool.uv.sources]",
                'agi-env = { path = "../../../core/agi-env", editable = true }',
                'demo-lib = { path = "../demo-lib", editable = true }',
                "",
            ]
        )
    )

    assert "agi-env" not in sanitized
    assert "[tool.uv.sources]" in sanitized
    assert "demo-lib" in sanitized


def test_sanitize_packaged_builtin_app_pyprojects_updates_build_tree(tmp_path: Path) -> None:
    module = _load_module()
    pyproject = tmp_path / "agilab/apps/builtin/flight_telemetry_project/pyproject.toml"
    pyproject.parent.mkdir(parents=True)
    pyproject.write_text(
        "\n".join(
            [
                "[project]",
                'name = "flight_telemetry_project"',
                'dependencies = ["agi-env"]',
                "",
                "[tool.uv.sources]",
                'agi-env = { path = "../../../core/agi-env", editable = true }',
                "",
            ]
        ),
        encoding="utf-8",
    )

    changed = module.sanitize_packaged_builtin_app_pyprojects(tmp_path)

    assert changed == [pyproject]
    assert "[tool.uv.sources]" not in pyproject.read_text(encoding="utf-8")


def test_sanitize_packaged_page_bundle_pyprojects_updates_build_tree(tmp_path: Path) -> None:
    module = _load_module()
    pyproject = tmp_path / "agi_pages/view_maps/pyproject.toml"
    pyproject.parent.mkdir(parents=True)
    pyproject.write_text(
        "\n".join(
            [
                "[project]",
                'name = "agi-page-geospatial-map"',
                'dependencies = ["agi-gui"]',
                "",
                "[tool.uv.sources]",
                'agi-gui = { path = "../../lib/agi-gui", editable = true }',
                'agi-env = { path = "../../core/agi-env", editable = true }',
                "",
            ]
        ),
        encoding="utf-8",
    )

    changed = module.sanitize_packaged_page_bundle_pyprojects(tmp_path)

    assert changed == [pyproject]
    assert "[tool.uv.sources]" not in pyproject.read_text(encoding="utf-8")


def test_purge_packaged_builtin_app_artifacts_removes_build_noise(tmp_path: Path) -> None:
    module = _load_module()
    app_src = tmp_path / "agilab/apps/builtin/flight_telemetry_project/src/flight"
    pycache = app_src / "__pycache__"
    egg_info = app_src / "flight.egg-info"
    pycache.mkdir(parents=True)
    egg_info.mkdir()
    keep_source = app_src / "flight.py"
    keep_pyx = app_src / "flight_worker.pyx"
    remove_pyc = pycache / "flight.cpython-313.pyc"
    remove_c = app_src / "flight_worker.c"
    keep_source.write_text("print('ok')\n", encoding="utf-8")
    keep_pyx.write_text("# generated source kept for cython build\n", encoding="utf-8")
    remove_pyc.write_bytes(b"pyc")
    remove_c.write_text("/* generated C */\n", encoding="utf-8")
    (egg_info / "PKG-INFO").write_text("metadata\n", encoding="utf-8")

    removed = module.purge_packaged_builtin_app_artifacts(tmp_path)

    assert pycache in removed
    assert egg_info in removed
    assert remove_c in removed
    assert not pycache.exists()
    assert not egg_info.exists()
    assert not remove_c.exists()
    assert keep_source.is_file()
    assert keep_pyx.is_file()


def test_purge_packaged_page_bundle_artifacts_removes_build_noise(tmp_path: Path) -> None:
    module = _load_module()
    page_src = tmp_path / "agi_pages/view_maps/src/view_maps"
    pycache = page_src / "__pycache__"
    pycache.mkdir(parents=True)
    keep_source = page_src / "view_maps.py"
    remove_pyc = pycache / "view_maps.cpython-313.pyc"
    remove_lock = tmp_path / "agi_pages/view_maps/uv.lock"
    keep_source.write_text("print('ok')\n", encoding="utf-8")
    remove_pyc.write_bytes(b"pyc")
    remove_lock.write_text("lock\n", encoding="utf-8")

    removed = module.purge_packaged_page_bundle_artifacts(tmp_path)

    assert pycache in removed
    assert remove_pyc in removed or not remove_pyc.exists()
    assert remove_lock in removed
    assert not pycache.exists()
    assert not remove_lock.exists()
    assert keep_source.is_file()


def test_purge_packaged_public_app_payload_removes_root_wheel_payload_only(tmp_path: Path) -> None:
    module = _load_module()
    apps = tmp_path / "agilab/apps"
    examples = tmp_path / "agilab/examples"
    apps_pages = tmp_path / "agilab/apps-pages"
    apps.mkdir(parents=True)
    examples.mkdir()
    apps_pages.mkdir()
    (apps / "install.py").write_text("# installer\n", encoding="utf-8")
    (examples / "README.md").write_text("examples\n", encoding="utf-8")
    (apps_pages / "README.md").write_text("views\n", encoding="utf-8")

    removed = module.purge_packaged_public_app_payload(tmp_path)

    assert removed == [apps, examples, apps_pages]
    assert not apps.exists()
    assert not examples.exists()
    assert not apps_pages.exists()
