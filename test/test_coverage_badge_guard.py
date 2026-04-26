from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


MODULE_PATH = Path("tools/coverage_badge_guard.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("coverage_badge_guard_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_changed_coverage_components_maps_gui_and_root_tests() -> None:
    module = _load_module()

    changed = module.changed_coverage_components(
        [
            "src/agilab/orchestrate_execute.py",
            "test/test_orchestrate_execute.py",
        ]
    )

    assert changed == {
        "agi-gui": [
            "src/agilab/orchestrate_execute.py",
            "test/test_orchestrate_execute.py",
        ]
    }


def test_changed_coverage_components_maps_core_tests_to_node_and_cluster() -> None:
    module = _load_module()

    changed = module.changed_coverage_components(["src/agilab/core/test/test_agi_distributor.py"])

    assert changed == {
        "agi-cluster": ["src/agilab/core/test/test_agi_distributor.py"],
        "agi-node": ["src/agilab/core/test/test_agi_distributor.py"],
    }


def test_expand_with_aggregates_adds_core_and_global_badges() -> None:
    module = _load_module()

    assert module.expand_with_aggregates(["agi-env"]) == ["agi-env", "agi-core", "agilab"]
    assert module.expand_with_aggregates(["agi-gui"]) == ["agi-gui", "agilab"]


def test_stale_xml_messages_flags_xml_older_than_changed_input(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "src" / "agilab" / "orchestrate_execute.py"
    source.parent.mkdir(parents=True)
    source.write_text("print('changed')\n", encoding="utf-8")
    xml = tmp_path / "coverage-agi-gui.xml"
    xml.write_text('<coverage lines-covered="1" lines-valid="1" />\n', encoding="utf-8")

    old = 1_700_000_000
    new = old + 60
    os.utime(xml, (old, old))
    os.utime(source, (new, new))

    messages = module.stale_xml_messages(
        {"agi-gui": ["src/agilab/orchestrate_execute.py"]},
        repo_root=tmp_path,
    )

    assert messages == [
        "agi-gui: coverage-agi-gui.xml is older than changed input src/agilab/orchestrate_execute.py"
    ]


def test_stale_xml_messages_ignores_regenerated_badge_outputs(tmp_path: Path) -> None:
    module = _load_module()
    source = tmp_path / "src" / "agilab" / "orchestrate_execute.py"
    badge = tmp_path / "badges" / "coverage-agi-gui.svg"
    source.parent.mkdir(parents=True)
    badge.parent.mkdir(parents=True)
    source.write_text("print('changed')\n", encoding="utf-8")
    badge.write_text("<svg />\n", encoding="utf-8")
    xml = tmp_path / "coverage-agi-gui.xml"
    xml.write_text('<coverage lines-covered="1" lines-valid="1" />\n', encoding="utf-8")

    old = 1_700_000_000
    os.utime(source, (old + 10, old + 10))
    os.utime(xml, (old + 20, old + 20))
    os.utime(badge, (old + 30, old + 30))

    messages = module.stale_xml_messages(
        {"agi-gui": ["badges/coverage-agi-gui.svg", "src/agilab/orchestrate_execute.py"]},
        repo_root=tmp_path,
    )

    assert messages == []
