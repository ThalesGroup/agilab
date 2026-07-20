from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[1]
PAGE_ROOT = ROOT / "src/agilab/apps-pages/view_routing_model_comparison"
MODULE_PATH = (
    PAGE_ROOT
    / "src/view_routing_model_comparison/view_routing_model_comparison.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "view_routing_model_comparison_test_module",
        MODULE_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_routing_comparison_compatibility_route_delegates_to_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    calls: list[str] = []
    canonical = SimpleNamespace(main=lambda: calls.append("rendered"))

    def fake_import(name: str):
        assert name == module.CANONICAL_MODULE
        return canonical

    monkeypatch.setattr(module, "import_module", fake_import)

    assert module._load_canonical_main() is canonical.main
    module.main()
    assert calls == ["rendered"]


def test_routing_comparison_compatibility_route_requires_canonical_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "import_module", lambda _name: SimpleNamespace())

    with pytest.raises(RuntimeError, match="has no main"):
        module._load_canonical_main()


def test_routing_comparison_bundle_declares_canonical_dependency() -> None:
    payload = tomllib.loads((PAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = payload["project"]["dependencies"]

    assert any(
        dependency.startswith("agi-page-inference-report>=")
        for dependency in dependencies
    )
    assert payload["project"]["entry-points"]["agilab.pages"] == {
        "view_routing_model_comparison": "view_routing_model_comparison:bundle_root"
    }


def test_routing_comparison_bundle_root_and_readme_document_compatibility() -> None:
    package_init = PAGE_ROOT / "src/view_routing_model_comparison/__init__.py"
    spec = importlib.util.spec_from_file_location(
        "view_routing_model_comparison_package_test",
        package_init,
    )
    assert spec is not None and spec.loader is not None
    package = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(package)

    assert package.bundle_root().name == "view_routing_model_comparison"
    readme = (PAGE_ROOT / "README.md").read_text(encoding="utf-8").lower()
    assert "compatibility" in readme
    assert "view_inference_analysis" in readme
