import ast
from unittest import mock

import agi_env.content_renamer_support as content_renamer_module


def test_content_renamer_updates_ast_nodes():
    fake_logger = mock.Mock()
    source = ast.parse(
        "import foo.mod\n"
        "from foo.pkg import Foo, foo_helper\n"
        "class Foo:\n"
        "    def foo(self, foo_arg):\n"
        "        global foo\n"
        "        for foo in [foo_arg]:\n"
        "            self.foo = foo\n"
        "            return foo\n"
    )
    rename_map = {
        "foo": "bar",
        "Foo": "Baz",
        "foo_helper": "bar_helper",
        "foo_arg": "bar_arg",
    }

    transformed = content_renamer_module.ContentRenamer(rename_map, logger=fake_logger).visit(source)
    rendered = ast.unparse(transformed)

    assert "import bar.mod" in rendered
    assert "from bar.pkg import Baz, bar_helper" in rendered
    assert "class Baz" in rendered
    assert "def bar(self, bar_arg)" in rendered
    assert "global bar" in rendered
    assert "for bar in [bar_arg]" in rendered
    assert "self.bar = bar" in rendered

    nonlocal_node = ast.Nonlocal(names=["foo", "other"])
    updated_nonlocal = content_renamer_module.ContentRenamer(rename_map, logger=fake_logger).visit_nonlocal(nonlocal_node)
    assert updated_nonlocal.names == ["bar", "other"]
    assert fake_logger.info.call_count > 0


def test_content_renamer_handles_exact_import_module_prefix_imported_name_and_annassign_without_logger():
    source = ast.parse(
        "import foo\n"
        "from foo import foo_helper_extra\n"
        "value: foo.Type = foo_helper_extra\n"
    )
    rename_map = {
        "foo": "bar",
        "foo_helper": "bar_helper",
    }

    transformed = content_renamer_module.ContentRenamer(rename_map).visit(source)
    rendered = ast.unparse(transformed)

    assert "import bar" in rendered
    assert "from bar import bar_helper_extra" in rendered
    assert "value: bar.Type = foo_helper_extra" in rendered


def test_content_renamer_leaves_unmatched_symbols_unchanged():
    source = ast.parse(
        "import keep.mod\n"
        "from keep.pkg import helper\n"
        "class Keep:\n"
        "    attr: int = 1\n"
        "    def keep(self, value):\n"
        "        global keep_global\n"
        "        for idx in [value]:\n"
        "            return idx\n"
    )

    transformed = content_renamer_module.ContentRenamer({"other": "renamed"}).visit(source)
    rendered = ast.unparse(transformed)

    assert "import keep.mod" in rendered
    assert "from keep.pkg import helper" in rendered
    assert "class Keep" in rendered
    assert "def keep(self, value)" in rendered
    assert "global keep_global" in rendered
    assert "for idx in [value]" in rendered
