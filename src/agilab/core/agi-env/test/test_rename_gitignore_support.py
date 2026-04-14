from pathlib import Path

import agi_env.rename_gitignore_support as rename_support_module


def test_rename_gitignore_support_helpers_cover_text_gitignore_and_relative_paths(tmp_path: Path):
    txt = "foo foo_bar barfoo bar Foo foo."
    rename_map = {"foo": "baz", "bar": "qux", "Foo": "Baz"}
    assert rename_support_module.replace_text_content(txt, rename_map) == "baz foo_bar barfoo qux Baz baz."

    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("*.pyc\nbuild/\n", encoding="utf-8")
    spec = rename_support_module.load_gitignore_spec(gitignore)
    assert spec.match_file("module.pyc") is True
    assert spec.match_file("build/output.txt") is True
    assert spec.match_file("README.md") is False

    parent = tmp_path / "parent"
    child = parent / "child"
    child.mkdir(parents=True)
    assert rename_support_module.is_relative_to(child, parent) is True
    assert rename_support_module.is_relative_to(tmp_path / "other", parent) is False
