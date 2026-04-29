from __future__ import annotations

import importlib.util
import py_compile
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src/agilab/apps/install.py"
EXAMPLES_ROOT = ROOT / "src/agilab/examples"


def _load_installer(monkeypatch, tmp_path: Path):
    sys.modules.pop("agilab_app_install_test_module", None)
    app_path = tmp_path / "demo_project"
    app_path.mkdir()
    monkeypatch.setattr(sys, "argv", ["install.py", str(app_path)])
    spec = importlib.util.spec_from_file_location("agilab_app_install_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_seed_example_scripts_uses_packaged_examples_dir(tmp_path: Path, monkeypatch) -> None:
    module = _load_installer(monkeypatch, tmp_path)
    package_root = tmp_path / "site-packages" / "agilab"
    examples_dir = package_root / "examples" / "flight"
    examples_dir.mkdir(parents=True)
    (examples_dir / "AGI_install_flight.py").write_text("# install\n", encoding="utf-8")
    (examples_dir / "AGI_run_flight.py").write_text("# run\n", encoding="utf-8")
    monkeypatch.setattr(module, "_package_root", lambda: package_root)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    module._seed_example_scripts("flight")

    execute_dir = tmp_path / "home" / "log" / "execute" / "flight"
    assert (execute_dir / "AGI_install_flight.py").read_text(encoding="utf-8") == "# install\n"
    assert (execute_dir / "AGI_run_flight.py").read_text(encoding="utf-8") == "# run\n"


def test_app_dir_candidates_prefer_packaged_builtin_apps(tmp_path: Path, monkeypatch) -> None:
    module = _load_installer(monkeypatch, tmp_path)
    package_root = tmp_path / "site-packages" / "agilab"
    monkeypatch.setattr(module, "_package_root", lambda: package_root)

    assert module._app_dir_candidates("flight") == [
        package_root / "apps" / "builtin" / "flight_project",
        package_root / "apps" / "flight_project",
    ]


def test_packaged_agi_example_scripts_are_compile_safe() -> None:
    scripts = sorted(EXAMPLES_ROOT.glob("*/AGI_*.py"))

    assert scripts
    for script in scripts:
        py_compile.compile(str(script), doraise=True)


def test_packaged_run_and_install_examples_import_with_fake_home(tmp_path: Path, monkeypatch) -> None:
    agilab_path = tmp_path / ".local" / "share" / "agilab"
    agilab_path.mkdir(parents=True)
    (agilab_path / ".agilab-path").write_text(str(ROOT / "src/agilab"), encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))

    scripts = sorted(
        script
        for script in EXAMPLES_ROOT.glob("*/AGI_*.py")
        if script.name.startswith(("AGI_install_", "AGI_run_"))
    )

    assert scripts
    for script in scripts:
        module_name = f"agilab_example_{script.parent.name}_{script.stem}"
        sys.modules.pop(module_name, None)
        spec = importlib.util.spec_from_file_location(module_name, script)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        assert callable(module.main)
