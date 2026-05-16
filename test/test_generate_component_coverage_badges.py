from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path("tools/generate_component_coverage_badges.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("generate_component_coverage_badges_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_format_percent_truncates_for_ci_stability() -> None:
    module = _load_module()

    assert module.format_percent(83.5298) == "83%"
    assert module.format_percent(83.4999) == "83%"
    assert module.format_percent(86.5596) == "86%"


def test_selected_component_items_preserves_requested_subset_order() -> None:
    module = _load_module()

    selected = module.selected_component_items(["agi-gui", "agi-env"])

    assert [name for name, _ in selected] == ["agi-gui", "agi-env"]


def test_selected_component_items_defaults_to_all_components() -> None:
    module = _load_module()

    selected = module.selected_component_items(None)

    assert [name for name, _ in selected] == list(module.COMPONENTS)


def test_component_badges_use_component_name_in_label() -> None:
    module = _load_module()

    assert module.COMPONENTS["agilab"]["label"] == "agilab coverage"
    assert module.COMPONENTS["agi-env"]["label"] == "agi-env coverage"
    assert module.COMPONENTS["agi-node"]["label"] == "agi-node coverage"
    assert module.COMPONENTS["agi-cluster"]["label"] == "agi-cluster coverage"
    assert module.COMPONENTS["agi-gui"]["label"] == "agi-gui coverage"
    assert module.COMPONENTS["agi-core"]["label"] == "agi-core coverage"


def test_resolve_component_counts_falls_back_to_aggregate_xml(tmp_path: Path) -> None:
    module = _load_module()

    combined_xml = tmp_path / "coverage-agi-core.xml"
    combined_xml.write_text(
        """
<coverage>
  <packages>
    <package name="agi-node">
      <classes>
        <class filename="src/agilab/core/agi-node/src/agi_node/example.py">
          <lines>
            <line number="1" hits="1" />
            <line number="2" hits="0" />
            <line number="3" hits="1" />
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
""".strip()
    )

    original = module.COMPONENTS["agi-node"].copy()
    try:
        module.COMPONENTS["agi-node"] = {
            **original,
            "xml": tmp_path / "missing-node.xml",
            "fallback_xmls": (combined_xml,),
        }
        assert module.resolve_component_counts("agi-node", tmp_path / "unused.xml") == (2, 3)
    finally:
        module.COMPONENTS["agi-node"] = original


def test_compute_aggregate_percent_uses_component_fallback_counts(tmp_path: Path) -> None:
    module = _load_module()

    env_xml = tmp_path / "coverage-agi-env.xml"
    env_xml.write_text('<coverage lines-covered="4" lines-valid="5" line-rate="0.8" />')

    combined_xml = tmp_path / "coverage-agi-core.xml"
    combined_xml.write_text(
        """
<coverage>
  <packages>
    <package name="agi-node">
      <classes>
        <class filename="src/agilab/core/agi-node/src/agi_node/example.py">
          <lines>
            <line number="1" hits="1" />
            <line number="2" hits="1" />
          </lines>
        </class>
      </classes>
    </package>
    <package name="agi-cluster">
      <classes>
        <class filename="src/agilab/core/agi-cluster/src/agi_cluster/example.py">
          <lines>
            <line number="1" hits="1" />
            <line number="2" hits="0" />
            <line number="3" hits="1" />
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
""".strip()
    )

    originals = {
        key: module.COMPONENTS[key].copy()
        for key in ("agi-env", "agi-node", "agi-cluster")
    }
    try:
        module.COMPONENTS["agi-env"] = {
            **originals["agi-env"],
            "xml": env_xml,
            "fallback_xmls": (),
        }
        module.COMPONENTS["agi-node"] = {
            **originals["agi-node"],
            "xml": tmp_path / "missing-node.xml",
            "fallback_xmls": (combined_xml,),
        }
        module.COMPONENTS["agi-cluster"] = {
            **originals["agi-cluster"],
            "xml": tmp_path / "missing-cluster.xml",
            "fallback_xmls": (combined_xml,),
        }
        percent = module.compute_aggregate_percent(("agi-env", "agi-node", "agi-cluster"), tmp_path / "unused.xml")
        assert percent == 80.0
    finally:
        for key, value in originals.items():
            module.COMPONENTS[key] = value


def test_compute_aggregate_percent_can_use_minimum_component_policy(tmp_path: Path) -> None:
    module = _load_module()

    env_xml = tmp_path / "coverage-agi-env.xml"
    node_xml = tmp_path / "coverage-agi-node.xml"
    cluster_xml = tmp_path / "coverage-agi-cluster.xml"
    env_xml.write_text('<coverage lines-covered="99" lines-valid="100" line-rate="0.99" />')
    node_xml.write_text('<coverage lines-covered="99" lines-valid="100" line-rate="0.99" />')
    cluster_xml.write_text('<coverage lines-covered="97" lines-valid="100" line-rate="0.97" />')

    originals = {
        key: module.COMPONENTS[key].copy()
        for key in ("agi-env", "agi-node", "agi-cluster")
    }
    try:
        module.COMPONENTS["agi-env"] = {**originals["agi-env"], "xml": env_xml}
        module.COMPONENTS["agi-node"] = {**originals["agi-node"], "xml": node_xml}
        module.COMPONENTS["agi-cluster"] = {**originals["agi-cluster"], "xml": cluster_xml}

        weighted = module.compute_aggregate_percent(("agi-env", "agi-node", "agi-cluster"), tmp_path / "unused.xml")
        minimum = module.compute_aggregate_percent(
            ("agi-env", "agi-node", "agi-cluster"),
            tmp_path / "unused.xml",
            policy="minimum",
        )

        assert module.format_percent(weighted) == "98%"
        assert minimum == 97.0
    finally:
        for key, value in originals.items():
            module.COMPONENTS[key] = value


def test_node_and_cluster_default_to_explicit_component_or_combined_reports_only() -> None:
    module = _load_module()

    assert "fallback_xmls" not in module.COMPONENTS["agi-node"]
    assert "fallback_xmls" not in module.COMPONENTS["agi-cluster"]
    assert module.COMPONENTS["agi-node"].get("allow_combined_fallback") is None
    assert module.COMPONENTS["agi-cluster"].get("allow_combined_fallback") is None
    assert module.COMPONENTS["agi-env"].get("allow_combined_fallback") is None
    assert module.COMPONENTS["agi-gui"].get("allow_combined_fallback") is None


def test_resolve_component_counts_does_not_use_combined_xml_without_opt_in(tmp_path: Path) -> None:
    module = _load_module()
    combined_xml = tmp_path / "coverage-agilab.combined.xml"
    combined_xml.write_text(
        """
<coverage>
  <packages>
    <package name="agi-env">
      <classes>
        <class filename="src/agilab/core/agi-env/src/agi_env/example.py">
          <lines>
            <line number="1" hits="1" />
            <line number="2" hits="1" />
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
""".strip()
    )

    original = module.COMPONENTS["agi-env"].copy()
    try:
        module.COMPONENTS["agi-env"] = {
            **original,
            "xml": tmp_path / "missing-env.xml",
        }
        assert module.resolve_component_counts("agi-env", combined_xml) is None
    finally:
        module.COMPONENTS["agi-env"] = original


def test_resolve_component_counts_can_use_combined_xml_when_explicitly_enabled(tmp_path: Path) -> None:
    module = _load_module()
    combined_xml = tmp_path / "coverage-agilab.combined.xml"
    combined_xml.write_text(
        """
<coverage>
  <packages>
    <package name="agi-gui">
      <classes>
        <class filename="src/agilab/example.py">
          <lines>
            <line number="1" hits="1" />
            <line number="2" hits="0" />
            <line number="3" hits="1" />
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
""".strip()
    )

    original = module.COMPONENTS["agi-gui"].copy()
    try:
        module.COMPONENTS["agi-gui"] = {
            **original,
            "xml": tmp_path / "missing-gui.xml",
            "allow_combined_fallback": True,
        }
        assert module.resolve_component_counts("agi-gui", combined_xml) == (2, 3)
    finally:
        module.COMPONENTS["agi-gui"] = original
