from __future__ import annotations

import ast
from unittest import mock

import pytest

import agi_env.source_analysis_ast as source_analysis_ast


def test_get_import_mapping_collects_import_and_import_from_aliases():
    source = """
import os
import json as js
from pathlib import Path as P
from functools import wraps
"""

    mapping = source_analysis_ast.get_import_mapping(source)

    assert mapping == {
        "os": "os",
        "js": "json",
        "P": "pathlib",
        "wraps": "functools",
    }


def test_get_import_mapping_reports_syntax_error_to_logger():
    source = "def bad(:\n"
    logger = mock.Mock()

    with pytest.raises(SyntaxError):
        source_analysis_ast.get_import_mapping(source, logger=logger)

    logger.error.assert_called_once()


def test_get_import_mapping_without_logger_keeps_raising_syntax_error():
    with pytest.raises(SyntaxError):
        source_analysis_ast.get_import_mapping("def bad(:\n")


def test_get_full_attribute_name_supports_nested_attribute_chain():
    node = ast.parse("pkg.sub.module.Class").body[0].value
    assert source_analysis_ast.get_full_attribute_name(node) == "pkg.sub.module.Class"


def test_get_full_attribute_name_handles_unknown_node():
    assert source_analysis_ast.get_full_attribute_name(ast.Constant(value=1)) == ""


def test_extract_base_info_name_and_attribute_variants():
    import_mapping = {"pkg": "package", "alias": "renamed"}
    name_base_node = ast.Name(id="Base", ctx=ast.Load())
    attr_node = ast.parse("pkg.sub.Module").body[0].value

    assert source_analysis_ast.extract_base_info(name_base_node, import_mapping) == ("Base", None)
    assert source_analysis_ast.extract_base_info(attr_node, import_mapping) == ("Module", "package")
    alias_attribute = ast.Attribute(
        value=ast.Name(id="alias", ctx=ast.Load()),
        attr="K",
        ctx=ast.Load(),
    )
    assert source_analysis_ast.extract_base_info(alias_attribute, {"alias": "package"}) == (
        "K",
        "package",
    )


def test_extract_base_info_falls_back_when_attribute_name_has_no_module(monkeypatch):
    base_node = ast.Attribute(
        value=ast.Name(id="Alias", ctx=ast.Load()),
        attr="K",
        ctx=ast.Load(),
    )
    monkeypatch.setattr(source_analysis_ast, "get_full_attribute_name", lambda _node: "Solo")
    assert source_analysis_ast.extract_base_info(base_node, {}) == ("K", None)


def test_extract_base_info_returns_none_for_unknown_nodes():
    assert source_analysis_ast.extract_base_info(ast.Constant(value=1), {"x": "y"}) is None
