from __future__ import annotations

import ast
from pathlib import Path


ENTRYPOINT_FILES = {"__init__.py", "bridge_cli.py", "lab_run.py", "main_page.py"}


def _target_module_from_shim(path: Path) -> str:
    module = ast.parse(path.read_text(encoding="utf-8"))
    for node in module.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "_TARGET_MODULE"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    raise AssertionError(f"{path} does not declare _TARGET_MODULE")


def test_top_level_agilab_modules_are_classified_or_entrypoints():
    root = Path(__file__).resolve().parents[1] / "src" / "agilab"
    top_level_modules = sorted(path for path in root.glob("*.py"))

    assert {path.name for path in top_level_modules if path.name in ENTRYPOINT_FILES} == ENTRYPOINT_FILES

    for path in top_level_modules:
        if path.name in ENTRYPOINT_FILES:
            continue
        target_module = _target_module_from_shim(path)
        assert target_module.startswith("agilab.")
        relative_target = Path(*target_module.split(".")[1:]).with_suffix(".py")
        assert (root.parent / relative_target).is_file(), (path, target_module)
        text = path.read_text(encoding="utf-8")
        assert "activate_compat_module" in text
        assert "classified package layout" in text
