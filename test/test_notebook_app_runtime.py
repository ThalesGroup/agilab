import sys
from pathlib import Path
from types import ModuleType

import pytest

from agilab.demos.notebook_app_runtime import app_session_state, run_app


def test_each_project_gets_fresh_imports_and_its_own_directory(tmp_path):
    original = ModuleType("analysis")
    old = sys.modules.get("analysis")
    sys.modules["analysis"] = original
    cwd = Path.cwd()
    try:
        for value in (10, 20):
            project = tmp_path / str(value)
            project.mkdir()
            (project / "analysis.py").write_text(f"value = {value}\n")
            (project / "app.py").write_text("from analysis import value\nfrom pathlib import Path\nPath('rendered.txt').write_text(str(value))\n")
            run_app(project)
            assert (project / "rendered.txt").read_text() == str(value)
            assert sys.modules["analysis"] is original
            assert Path.cwd() == cwd
    finally:
        sys.modules.pop("analysis", None)
        if old is not None:
            sys.modules["analysis"] = old


def test_render_failure_restores_process_state(tmp_path):
    (tmp_path / "app.py").write_text("raise RuntimeError('app failed')")
    cwd, paths = Path.cwd(), sys.path[:]
    with pytest.raises(RuntimeError, match="app failed"):
        run_app(tmp_path)
    assert Path.cwd() == cwd
    assert sys.path == paths


def test_demo_results_survive_switches_and_restore_ambient_state_on_error():
    ambient = {"analysis": {"outer": True}, "widget": 42}
    for name in ("forecast", "threading"):
        with pytest.raises(RuntimeError, match="render failed"):
            with app_session_state(ambient, name, ("analysis",)):
                assert "analysis" not in ambient
                ambient["analysis"] = {"owner": name}
                raise RuntimeError("render failed")
        assert ambient["analysis"] == {"outer": True}
        assert ambient["widget"] == 42
    for name in ("forecast", "threading", "forecast"):
        with app_session_state(ambient, name, ("analysis",)):
            assert ambient["analysis"] == {"owner": name}
    assert ambient["analysis"] == {"outer": True}


@pytest.fixture
def isolated_project_package_modules():
    """Keep failed isolation regressions from leaking imports into later tests."""
    root = "_agilab_notebook_runtime_package_probe"
    previous = {
        name: module for name, module in sys.modules.copy().items()
        if name == root or name.startswith(root + ".")
    }
    for name in previous:
        sys.modules.pop(name, None)
    try:
        yield root
    finally:
        for name in list(sys.modules):
            if name == root or name.startswith(root + "."):
                sys.modules.pop(name, None)
        sys.modules.update(previous)


@pytest.mark.parametrize("regular_package", [False, True], ids=["namespace", "regular"])
@pytest.mark.parametrize("nested", [False, True], ids=["shallow", "nested"])
def test_package_projects_get_distinct_results_without_leaking_imports(
    tmp_path, isolated_project_package_modules, regular_package, nested
):
    root = isolated_project_package_modules
    module_parent = root + (".nested" if nested else "")
    outputs, retained_modules = [], []
    cwd, paths = Path.cwd(), sys.path[:]
    for value in (10, 20):
        project = tmp_path / str(value)
        package = project / root
        leaf = package / "nested" if nested else package
        leaf.mkdir(parents=True)
        if regular_package:
            for directory in {package, leaf}:
                (directory / "__init__.py").write_text("")
        (leaf / "values.py").write_text(f"value = {value}\n")
        (project / "app.py").write_text(
            f"from {module_parent}.values import value\n"
            "from pathlib import Path\n"
            "Path('rendered.txt').write_text(str(value))\n"
        )
        run_app(project)
        outputs.append((project / "rendered.txt").read_text())
        retained_modules.append({
            name for name in sys.modules
            if name == root or name.startswith(root + ".")
        })
        assert Path.cwd() == cwd
        assert sys.path == paths

    assert outputs == ["10", "20"]
    assert retained_modules == [set(), set()]


@pytest.mark.parametrize("nested", [False, True], ids=["shallow", "nested"])
@pytest.mark.parametrize("fails", [False, True], ids=["success", "failure"])
def test_namespace_app_restores_ambient_module_identities(
    tmp_path, isolated_project_package_modules, nested, fails
):
    root = isolated_project_package_modules
    module_parent = root + (".nested" if nested else "")
    names = [root]
    if nested:
        names.append(module_parent)
    names.append(module_parent + ".values")
    originals = {name: ModuleType(name) for name in names}
    for name, module in originals.items():
        if name != names[-1]:
            module.__path__ = []
        sys.modules[name] = module
    if nested:
        originals[root].nested = originals[module_parent]
    originals[module_parent].values = originals[names[-1]]
    originals[names[-1]].value = 999

    package = tmp_path / root
    leaf = package / "nested" if nested else package
    leaf.mkdir(parents=True)
    (leaf / "values.py").write_text("value = 42\n")
    (leaf / "fresh.py").write_text("marker = 'fresh import'\n")
    app = (
        f"from {module_parent}.values import value\n"
        f"from {module_parent}.fresh import marker\n"
        "from pathlib import Path\n"
        "assert value == 42\n"
        "assert marker == 'fresh import'\n"
        "Path('rendered.txt').write_text(str(value))\n"
    )
    if fails:
        app += "raise RuntimeError('namespace app failed')\n"
    (tmp_path / "app.py").write_text(app)
    cwd, paths = Path.cwd(), sys.path[:]
    if fails:
        with pytest.raises(RuntimeError, match="namespace app failed"):
            run_app(tmp_path)
    else:
        run_app(tmp_path)

    assert (tmp_path / "rendered.txt").read_text() == "42"
    current = {
        name: module for name, module in sys.modules.items()
        if name == root or name.startswith(root + ".")
    }
    assert current.keys() == originals.keys()
    assert all(current[name] is module for name, module in originals.items())
    assert originals[module_parent].values is originals[names[-1]]
    if nested:
        assert originals[root].nested is originals[module_parent]
    assert originals[names[-1]].value == 999
    assert Path.cwd() == cwd
    assert sys.path == paths
