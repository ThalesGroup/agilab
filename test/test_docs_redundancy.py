from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path("tools/docs_redundancy_check.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("docs_redundancy_check_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_current_docs_do_not_repeat_nearby_prose_lines() -> None:
    module = _load_module()

    assert module.collect_violations(Path("docs/source")) == []


def test_docs_redundancy_check_rejects_nearby_duplicate_prose(tmp_path: Path) -> None:
    module = _load_module()
    page = tmp_path / "page.rst"
    page.write_text(
        "\n".join(
            [
                "Example",
                "=======",
                "",
                "- keep expanding notebook-native analysis surfaces or packaging",
                "  without duplicating the current apps-pages logic blindly",
                "- make notebook-native analysis surfaces or packaging possible",
                "  without duplicating the current apps-pages logic blindly",
            ]
        ),
        encoding="utf-8",
    )

    violations = module.collect_violations(tmp_path)

    assert len(violations) == 1
    assert violations[0].first_line == 5
    assert violations[0].second_line == 7


def test_docs_redundancy_check_ignores_rst_code_blocks(tmp_path: Path) -> None:
    module = _load_module()
    page = tmp_path / "page.rst"
    page.write_text(
        "\n".join(
            [
                "Example",
                "=======",
                "",
                ".. code-block:: toml",
                "",
                '   entrypoint = "pytorch_playground/app_surface.py"',
                '   entrypoint = "pytorch_playground/app_surface.py"',
            ]
        ),
        encoding="utf-8",
    )

    assert module.collect_violations(tmp_path) == []
