import sys
import json
import importlib.util
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parents[3]
SRC_DIR = ROOT_DIR / 'src'
MODULE_NAME = 'agilab.core.get_supported_python_versions'
MODULE_PATH = SRC_DIR / 'agilab' / 'core' / 'get_supported_python_versions.py'
spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
gspv = importlib.util.module_from_spec(spec)
sys.modules.setdefault(MODULE_NAME, gspv)
spec.loader.exec_module(gspv)

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

def write_pyproject(tmp_path: Path, filename: str, content: str) -> Path:
    path = tmp_path / filename
    path.write_text(content, encoding="utf-8")
    return path


def test_extract_requires_python_from_project(tmp_path, capsys):
    project_toml = """
    [project]
    requires-python = ">=3.8,<3.12"
    """
    path = write_pyproject(tmp_path, "project.toml", project_toml)

    value = gspv.extract_requires_python(path)

    assert value == ">=3.8,<3.12"
    assert "Parsed requires-python" in capsys.readouterr().err


def test_extract_requires_python_from_poetry(tmp_path, capsys):
    poetry_toml = """
    [tool.poetry.dependencies]
    python = ">=3.9,<3.11"
    """
    path = write_pyproject(tmp_path, "poetry.toml", poetry_toml)

    value = gspv.extract_requires_python(path)

    assert value == ">=3.9,<3.11"
    assert "Parsed requires-python" in capsys.readouterr().err


def test_main_collects_supported_versions(tmp_path, capsys):
    paths = [
        write_pyproject(tmp_path, "pkg1.toml", """
        [project]
        requires-python = ">=3.8,<3.11"
        """),
        write_pyproject(tmp_path, "pkg2.toml", """
        [tool.poetry.dependencies]
        python = ">=3.10"
        """),
        write_pyproject(tmp_path, "pkg3.toml", """
        [project]
        name = "no-python"
        """),
    ]

    gspv.main([str(p) for p in paths])

    captured = capsys.readouterr()
    versions = json.loads(captured.out)
    expected = ["3.10", "3.11", "3.12", "3.13", "3.8", "3.9"]
    assert versions == expected
    assert "No python requirement" in captured.err


def test_main_reports_parse_error(tmp_path, capsys):
    bad_file = write_pyproject(tmp_path, "broken.toml", "[project")

    gspv.main([str(bad_file)])

    captured = capsys.readouterr()
    assert captured.out.strip() == "[]"
    assert "Error parsing" in captured.err
