from pathlib import Path

import pytest

import agi_env.source_analysis_support as source_analysis_module
import agi_env.source_analysis_ast as source_analysis_ast_module


def test_source_analysis_support_reexports_pure_ast_helpers():
    assert source_analysis_module.get_import_mapping is source_analysis_ast_module.get_import_mapping
    assert source_analysis_module.extract_base_info is source_analysis_ast_module.extract_base_info
    assert source_analysis_module.get_full_attribute_name is source_analysis_ast_module.get_full_attribute_name


def test_source_symbol_helpers_cover_functions_attributes_classes_and_methods(tmp_path: Path):
    source_path = tmp_path / "symbols.py"
    source_path.write_text(
        "TOP_A = 1\n"
        "TOP_B, TOP_C = 2, 3\n"
        "annot: int = 4\n"
        "def outer():\n"
        "    nested = 1\n"
        "    def inner():\n"
        "        return nested\n"
        "    return inner()\n"
        "class Demo:\n"
        "    CLASS_ATTR = 1\n"
        "    x, y = 1, 2\n"
        "    ann: int = 3\n"
        "    def __init__(self):\n"
        "        self.runtime = 5\n"
        "    def first(self):\n"
        "        return 1\n"
        "    def second(self):\n"
        "        return 2\n",
        encoding="utf-8",
    )

    top_level = source_analysis_module.get_functions_and_attributes(source_path)
    class_level = source_analysis_module.get_functions_and_attributes(source_path, class_name="Demo")

    assert top_level == {
        "functions": ["outer"],
        "attributes": ["TOP_A", "TOP_B", "TOP_C", "annot"],
    }
    assert class_level == {
        "functions": ["__init__", "first", "second"],
        "attributes": ["CLASS_ATTR", "x", "y", "ann"],
    }
    assert source_analysis_module.get_classes_name(source_path) == ["Demo"]
    assert source_analysis_module.get_class_methods(source_path, "Demo") == ["__init__", "first", "second"]


def test_source_symbol_helpers_raise_for_missing_invalid_or_unreadable_sources(tmp_path: Path):
    missing = tmp_path / "missing.py"
    broken = tmp_path / "broken.py"
    broken.write_text("def nope(:\n", encoding="utf-8")
    source_path = tmp_path / "symbols.py"
    source_path.write_text("class Demo:\n    def run(self):\n        return 1\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        source_analysis_module.get_functions_and_attributes(missing)
    with pytest.raises(SyntaxError):
        source_analysis_module.get_functions_and_attributes(broken)
    with pytest.raises(ValueError, match="Class 'Missing' not found"):
        source_analysis_module.get_functions_and_attributes(source_path, class_name="Missing")
    with pytest.raises(ValueError, match="Class 'Missing' not found"):
        source_analysis_module.get_class_methods(source_path, "Missing")
