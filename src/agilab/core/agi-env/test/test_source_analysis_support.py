import ast
from unittest import mock

import pytest

import agi_env.source_analysis_support as source_analysis_module


def test_source_analysis_helpers_cover_import_mapping_and_base_info():
    source = (
        "import pkg.module as mod\n"
        "from demo.worker import DemoWorker\n"
        "from another.pkg import helper\n"
    )
    mapping = source_analysis_module.get_import_mapping(source)
    assert mapping["mod"] == "pkg.module"
    assert mapping["DemoWorker"] == "demo.worker"
    assert mapping["helper"] == "another.pkg"

    name_base = ast.parse("class Child(Base):\n    pass\n").body[0].bases[0]
    attr_base = ast.parse("class Child(mod.DemoWorker):\n    pass\n").body[0].bases[0]
    assert source_analysis_module.extract_base_info(name_base, mapping) == ("Base", None)
    assert source_analysis_module.extract_base_info(attr_base, mapping) == ("DemoWorker", "pkg.module")
    assert source_analysis_module.get_full_attribute_name(attr_base) == "mod.DemoWorker"


def test_get_import_mapping_logs_syntax_errors():
    fake_logger = mock.Mock()
    with pytest.raises(SyntaxError):
        source_analysis_module.get_import_mapping("def broken(:\n", logger=fake_logger)
    assert fake_logger.error.called
