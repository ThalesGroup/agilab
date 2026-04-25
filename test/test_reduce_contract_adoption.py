from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILTIN_APPS_ROOT = REPO_ROOT / "src" / "agilab" / "apps" / "builtin"
TEMPLATE_ONLY_BUILTIN_APPS = {
    "mycode_project": "starter template with placeholder worker hooks and no concrete merge output",
}


def _load_kpi_bundle_module():
    module_path = REPO_ROOT / "tools" / "kpi_evidence_bundle.py"
    spec = importlib.util.spec_from_file_location("kpi_evidence_bundle_guardrail_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _builtin_projects() -> list[Path]:
    return sorted(
        path
        for path in BUILTIN_APPS_ROOT.glob("*_project")
        if (path / "pyproject.toml").is_file()
    )


def test_non_template_builtin_apps_expose_reduce_contracts() -> None:
    module = _load_kpi_bundle_module()

    check = module._check_reduce_contract_adoption_guardrail(REPO_ROOT)

    assert check["status"] == "pass", "\n".join(check["details"].get("failures", []))
    assert check["id"] == "reduce_contract_adoption_guardrail"
    assert check["details"]["checked_apps"] == [
        "execution_pandas_project",
        "execution_polars_project",
        "flight_project",
        "meteo_forecast_project",
        "uav_queue_project",
        "uav_relay_queue_project",
    ]
    assert check["details"]["template_only_exemptions"] == TEMPLATE_ONLY_BUILTIN_APPS


def test_template_only_builtin_apps_are_explicitly_exempted() -> None:
    discovered = {path.name for path in _builtin_projects()}

    assert set(TEMPLATE_ONLY_BUILTIN_APPS) <= discovered

    mycode_docs = (REPO_ROOT / "docs" / "source" / "mycode-project.rst").read_text(
        encoding="utf-8"
    )
    normalized_docs = re.sub(r"\s+", " ", mycode_docs.lower())
    assert "template-only" in normalized_docs
    assert "no concrete merge output" in normalized_docs
    assert "reduce_summary_worker_<id>.json" in mycode_docs
