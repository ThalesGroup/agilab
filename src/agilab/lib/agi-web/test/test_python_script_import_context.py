"""File views can import sibling modules without changing their caller's path."""

from pathlib import Path
import sys

import pytest

from agi_web.python_view_session import ViewSession


@pytest.fixture
def script_with_sibling(tmp_path, monkeypatch):
    module_name = "agilab_script_context_regression_helper"
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    (tmp_path / f"{module_name}.py").write_text("MESSAGE = 'sibling helper loaded'\n")
    script = tmp_path / "view.py"
    monkeypatch.chdir(tmp_path.parent)
    yield script, module_name
    sys.modules.pop(module_name, None)


def test_file_view_imports_sibling_from_another_working_directory(script_with_sibling):
    script, module_name = script_with_sibling
    script.write_text(
        f"from agi_web import python_ui as ui\nimport {module_name}\n"
        f"ui.write({module_name}.MESSAGE)\n"
    )
    original_path, path_values, original_argv = sys.path, sys.path[:], sys.argv
    caller_cwd = Path.cwd()

    payload = ViewSession(script).render()

    assert payload["error"] == ""
    assert payload["nodes"]["main"][0]["props"]["body"] == "sibling helper loaded"
    assert sys.path is original_path
    assert sys.path == path_values
    assert sys.argv is original_argv
    assert Path.cwd() == caller_cwd


@pytest.mark.parametrize("mutation", ["sys.path.clear()", "sys.path = ['view replacement']"])
@pytest.mark.parametrize("raises", [False, True])
def test_file_view_restores_path_identity_contents_and_argv_after_user_changes(
    script_with_sibling, mutation, raises
):
    script, module_name = script_with_sibling
    script.write_text(
        f"import sys\nimport {module_name}\n{mutation}\n"
        "sys.argv = ['view replacement']\n"
        + ("raise RuntimeError('view failed after import')\n" if raises else "")
    )
    original_path, path_values, original_argv = sys.path, sys.path[:], sys.argv
    caller_cwd = Path.cwd()

    payload = ViewSession(script).render()

    assert payload["error"] == ("RuntimeError: view failed after import" if raises else "")
    assert sys.path is original_path
    assert sys.path == path_values
    assert sys.argv is original_argv
    assert Path.cwd() == caller_cwd


def test_file_view_parent_takes_precedence_over_an_unimported_search_path_entry(
    script_with_sibling, tmp_path, monkeypatch
):
    script, module_name = script_with_sibling
    other = tmp_path / "other_project"
    other.mkdir()
    (other / f"{module_name}.py").write_text("MESSAGE = 'other project'\n")
    monkeypatch.syspath_prepend(str(other))
    script.write_text(
        f"from agi_web import python_ui as ui\nimport {module_name}\n"
        f"ui.write({module_name}.MESSAGE)\n"
    )
    original_path, path_values = sys.path, sys.path[:]

    payload = ViewSession(script).render()

    assert payload["error"] == ""
    assert payload["nodes"]["main"][0]["props"]["body"] == "sibling helper loaded"
    assert sys.path is original_path
    assert sys.path == path_values
