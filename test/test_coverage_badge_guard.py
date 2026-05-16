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


def test_changed_coverage_components_ignores_coverage_tooling_tests() -> None:
    module = _load_module()

    changed = module.changed_coverage_components(["test/test_coverage_badge_guard.py"])

    assert changed == {}


def test_changed_coverage_components_ignores_release_and_public_docs_tests() -> None:
    module = _load_module()

    changed = module.changed_coverage_components(
        [
            "test/test_beta_readiness.py",
            "test/test_public_demo_links.py",
            "test/test_pypi_publish.py",
            "test/test_pypi_publish_workflow.py",
        ]
    )

    assert changed == {}


def test_changed_coverage_components_ignores_workflow_policy_tests() -> None:
    module = _load_module()

    changed = module.changed_coverage_components(
        [
            ".github/workflows/coverage.yml",
            "test/conftest.py",
            "test/test_ci_workflow.py",
            "test/test_coverage_workflow.py",
            "test/test_impact_validate.py",
            "test/test_pypi_publish_workflow.py",
            "test/test_workflow_parity.py",
        ]
    )

    assert changed == {}


def test_changed_coverage_components_ignores_package_metadata() -> None:
    module = _load_module()

    changed = module.changed_coverage_components(
        [
            "pyproject.toml",
            "src/agilab/core/agi-env/pyproject.toml",
            "src/agilab/core/agi-node/pyproject.toml",
            "src/agilab/core/agi-cluster/pyproject.toml",
            "src/agilab/core/agi-core/pyproject.toml",
            "src/agilab/lib/agi-gui/pyproject.toml",
            "src/agilab/apps/builtin/flight_telemetry_project/pyproject.toml",
        ]
    )

    assert changed == {}


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


def test_expected_svg_uses_generator_aggregate_policy() -> None:
    module = _load_module()
    calls = []

    class FakeGenerator:
        COMPONENTS = {
            "agi-core": {
                "aggregate": ("agi-env", "agi-node", "agi-cluster"),
                "aggregate_policy": "minimum",
                "label": "agi-core coverage",
            }
        }

        @staticmethod
        def compute_aggregate_percent(components, combined_xml, *, policy="weighted"):
            calls.append((components, combined_xml.name, policy))
            return 97.0 if policy == "minimum" else 98.0

        @staticmethod
        def format_percent(percent):
            return f"{int(percent)}%"

        @staticmethod
        def badge_color(percent):
            return "green"

        @staticmethod
        def render_badge(label, value, color):
            return f"{label}: {value} ({color})"

    assert module._expected_svg(FakeGenerator, "agi-core") == "agi-core coverage: 97% (green)"
    assert calls == [
        (
            ("agi-env", "agi-node", "agi-cluster"),
            "coverage-agilab.combined.xml",
            "minimum",
        )
    ]


def test_guard_commands_use_combined_core_coverage_profile() -> None:
    module = _load_module()

    commands = module._guard_commands(["agi-node", "agi-cluster"])

    assert commands[0] == (
        "uv --preview-features extra-build-dependencies run python "
        "tools/workflow_parity.py --profile agi-core-combined"
    )
    assert "--profile agi-node --profile agi-cluster" not in "\n".join(commands)


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


def test_badge_only_update_messages_blocks_badge_only_changes() -> None:
    module = _load_module()

    messages = module.badge_only_update_messages(
        {"agi-node": ["badges/coverage-agi-node.svg"]},
    )

    assert len(messages) == 1
    assert "badge-only coverage update blocked" in messages[0]
    assert "AGILAB_ALLOW_BADGE_ONLY_UPDATE=1" in messages[0]


def test_badge_only_update_messages_allows_paired_coverage_inputs() -> None:
    module = _load_module()

    messages = module.badge_only_update_messages(
        {
            "agi-node": [
                "badges/coverage-agi-node.svg",
                "src/agilab/core/agi-node/src/agi_node/example.py",
            ],
        },
    )

    assert messages == []


def test_badge_only_update_messages_allows_explicit_override() -> None:
    module = _load_module()

    messages = module.badge_only_update_messages(
        {"agi-node": ["badges/coverage-agi-node.svg"]},
        allow=True,
    )

    assert messages == []
