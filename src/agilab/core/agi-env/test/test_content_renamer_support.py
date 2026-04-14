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
