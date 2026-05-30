from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest


PAGE_PATH = (
    "src/agilab/apps-pages/view_shap_explanation/src/"
    "view_shap_explanation/view_shap_explanation.py"
)


def _create_demo_project(tmp_path: Path) -> Path:
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    project_dir = apps_dir / "minimal_app_project"
    (project_dir / "src" / "minimal_app").mkdir(parents=True)
    (project_dir / "pyproject.toml").write_text("[project]\nname='minimal_app_project'\n", encoding="utf-8")
    (project_dir / "src" / "app_settings.toml").write_text("[args]\n", encoding="utf-8")
    (project_dir / "src" / "minimal_app" / "__init__.py").write_text("", encoding="utf-8")
    return project_dir


def _run_shap_page(
    tmp_path: Path,
    monkeypatch,
    project_dir: Path,
    *,
    default_timeout: int = 20,
) -> AppTest:
    argv = [Path(PAGE_PATH).name, "--active-app", str(project_dir)]
    with patch.object(sys, "argv", argv):
        monkeypatch.setenv("AGI_EXPORT_DIR", str(tmp_path / "export"))
        monkeypatch.setenv("AGI_LOCAL_SHARE", str(tmp_path / "localshare"))
        monkeypatch.setenv("AGI_CLUSTER_SHARE", str(tmp_path / "clustershare"))
        monkeypatch.setenv("OPENAI_API_KEY", "dummy")
        monkeypatch.setenv("IS_SOURCE_ENV", "1")
        at = AppTest.from_file(PAGE_PATH, default_timeout=default_timeout)
        at.run()
    return at


def _load_shap_helpers() -> ModuleType:
    source = Path(PAGE_PATH).read_text(encoding="utf-8")
    prefix = source.split("\nconfigure_streamlit_page(st,", 1)[0]
    module = ModuleType("view_shap_explanation_test_module")
    module.__file__ = str(Path(PAGE_PATH).resolve())
    module.__package__ = None
    exec(compile(prefix, str(Path(PAGE_PATH)), "exec"), module.__dict__)
    return module


def test_view_shap_explanation_renders_exported_artifacts(tmp_path: Path, monkeypatch) -> None:
    project_dir = _create_demo_project(tmp_path)
    artifact_dir = tmp_path / "export" / "minimal_app" / "shap_explanation"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "shap_values.csv").write_text(
        "feature,shap_value\nage,0.46\npriors_count,-0.09\nethnicity,0.15\n",
        encoding="utf-8",
    )
    (artifact_dir / "feature_values.csv").write_text(
        "feature,feature_value\nage,21\npriors_count,0\nethnicity,group_a\n",
        encoding="utf-8",
    )
    (artifact_dir / "explanation_summary.json").write_text(
        json.dumps(
            {
                "model_name": "modern shap explainer demo",
                "target": "recidivism_probability",
                "instance_id": "person-001",
                "explainer": "shap",
                "prediction": 0.70,
                "base_value": 0.14,
            }
        ),
        encoding="utf-8",
    )

    at = _run_shap_page(tmp_path, monkeypatch, project_dir, default_timeout=60)

    assert not at.exception
    assert any(title.value == "SHAP explanation" for title in at.title)
    assert any(metric.label == "Top driver" and metric.value == "age" for metric in at.metric)
    assert any(metric.label == "Prediction - base" and metric.value == "+0.5600" for metric in at.metric)
    assert len(at.dataframe) == 1


def test_view_shap_explanation_warns_when_artifact_directory_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_dir = _create_demo_project(tmp_path)

    at = _run_shap_page(tmp_path, monkeypatch, project_dir)

    assert not at.exception
    assert any("Artifact directory does not exist yet" in warning.value for warning in at.warning)


def test_view_shap_explanation_resets_stale_app_scoped_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_shap_helpers()
    project_dir = _create_demo_project(tmp_path)
    old_project = project_dir.parent / "old_minimal_app_project"
    old_project.mkdir()
    argv = [Path(PAGE_PATH).name, "--active-app", str(project_dir)]

    with patch.object(sys, "argv", argv):
        monkeypatch.setenv("AGI_EXPORT_DIR", str(tmp_path / "export"))
        monkeypatch.setenv("AGI_LOCAL_SHARE", str(tmp_path / "localshare"))
        monkeypatch.setenv("AGI_CLUSTER_SHARE", str(tmp_path / "clustershare"))
        monkeypatch.setenv("OPENAI_API_KEY", "dummy")
        monkeypatch.setenv("IS_SOURCE_ENV", "1")
        at = AppTest.from_file(PAGE_PATH, default_timeout=20)
        at.session_state[module.APP_SCOPE_KEY] = str(old_project.resolve())
        at.session_state["env"] = SimpleNamespace(
            apps_path=old_project.parent,
            app=old_project.name,
            AGILAB_EXPORT_ABS=str(tmp_path / "old-export"),
            target="old_minimal_app",
        )
        at.session_state["shap_explanation_datadir"] = str(tmp_path / "old-export" / "old_minimal_app")
        at.session_state["shap_values_glob"] = "old_values.csv"
        at.session_state["shap_feature_values_glob"] = "old_features.csv"
        at.session_state["shap_metadata_glob"] = "old_metadata.json"
        at.run()

    assert not at.exception
    assert at.session_state[module.APP_SCOPE_KEY] == str(project_dir.resolve())
    assert at.session_state["shap_explanation_datadir"] == str(
        tmp_path / "export" / "minimal_app" / "shap_explanation"
    )
    assert at.session_state["shap_values_glob"] == "**/shap_values.*"
    assert at.session_state["shap_feature_values_glob"] == "**/feature_values.*"
    assert at.session_state["shap_metadata_glob"] == "**/explanation_summary.json"
    assert any("Artifact directory does not exist yet" in warning.value for warning in at.warning)


def test_view_shap_explanation_warns_when_shap_values_are_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_dir = _create_demo_project(tmp_path)
    artifact_dir = tmp_path / "export" / "minimal_app" / "shap_explanation"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "explanation_summary.json").write_text("{}", encoding="utf-8")

    at = _run_shap_page(tmp_path, monkeypatch, project_dir)

    assert not at.exception
    assert any("No SHAP values file found" in warning.value for warning in at.warning)


def test_view_shap_explanation_helper_branches(monkeypatch, tmp_path: Path) -> None:
    module = _load_shap_helpers()

    repo_root = tmp_path / "repo"
    src_root = repo_root / "src"
    module_path = (
        src_root
        / "agilab"
        / "apps-pages"
        / "view_shap_explanation"
        / "src"
        / "view_shap_explanation"
        / "view_shap_explanation.py"
    )
    module_path.parent.mkdir(parents=True)
    module_path.write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(module, "__file__", str(module_path))
    monkeypatch.setattr(sys, "path", [])
    module._ensure_repo_on_path()
    assert str(src_root) in sys.path
    assert str(repo_root) in sys.path

    errors: list[str] = []

    def stop_now():
        raise RuntimeError("stop")

    module.st = SimpleNamespace(error=errors.append, stop=stop_now)
    monkeypatch.setattr(sys, "argv", [Path(PAGE_PATH).name, "--active-app", str(tmp_path / "missing_app")])
    with pytest.raises(RuntimeError, match="stop"):
        module._resolve_active_app()
    assert any("Provided --active-app path not found" in message for message in errors)

    assert module._discover_files(tmp_path / "missing", "[") == []
    assert module._safe_float(object()) is None
    assert module._load_json(None) == {}
    assert module._load_json(tmp_path / "missing.json") == {}

    class BadBase:
        def glob(self, _pattern):
            raise OSError("bad glob")

    assert module._discover_files(BadBase(), "*.csv") == []

    parquet_path = tmp_path / "values.parquet"
    monkeypatch.setattr(module.pd, "read_parquet", lambda path: pd.DataFrame({"feature": ["age"], "shap_value": [1.0]}))
    assert module._load_table(parquet_path)["feature"].tolist() == ["age"]


def test_view_shap_explanation_normalizes_long_and_wide_artifacts() -> None:
    module = _load_shap_helpers()

    long_frame = pd.DataFrame(
        {
            "column": ["age", "priors_count"],
            "contribution": ["0.46", "-0.09"],
            "raw_value": [21, 0],
        }
    )
    normalized = module._coerce_shap_frame(long_frame)
    assert normalized["feature"].tolist() == ["age", "priors_count"]
    assert normalized["shap_value"].tolist() == [0.46, -0.09]
    assert normalized["feature_value"].tolist() == [21, 0]

    wide_frame = pd.DataFrame([{"age": 0.46, "priors_count": -0.09, "prediction": 0.70, "note": "skip"}])
    wide = module._coerce_shap_frame(wide_frame)
    assert wide["feature"].tolist() == ["age", "priors_count"]

    assert module._coerce_shap_frame(pd.DataFrame()).columns.tolist() == [
        "feature",
        "shap_value",
        "abs_shap_value",
    ]
    non_numeric = module._coerce_shap_frame(pd.DataFrame([{"feature": "age", "shap_value": "bad"}]))
    assert non_numeric.empty

    shap_frame = pd.DataFrame({"feature": ["age"], "shap_value": [0.46], "abs_shap_value": [0.46]})
    feature_frame = pd.DataFrame({"feature": ["age"], "feature_value": [21]})
    merged = module._merge_feature_values(shap_frame, feature_frame)
    assert merged["feature_value"].tolist() == [21]
    assert module._merge_feature_values(pd.DataFrame(), feature_frame).empty
    assert module._merge_feature_values(shap_frame.assign(feature_value=[99]), feature_frame)["feature_value"].tolist() == [99]

    assert module._coerce_feature_values(pd.DataFrame()).columns.tolist() == ["feature", "feature_value"]
    wide_values = module._coerce_feature_values(pd.DataFrame([{"age": 21, "priors_count": 0}]))
    assert wide_values.to_dict(orient="records") == [
        {"feature": "age", "feature_value": 21},
        {"feature": "priors_count", "feature_value": 0},
    ]
    assert module._metadata_value({"model_output": 0.7}, "prediction", "model_output") == 0.7
    assert module._metadata_value({"prediction": ""}, "prediction") is None


def test_view_shap_explanation_state_text_input_initializes_default(monkeypatch) -> None:
    module = _load_shap_helpers()
    calls: list[tuple[str, str]] = []
    session_state: dict[str, str] = {}

    def text_input(label: str, *, key: str):
        calls.append((label, key))
        return session_state[key]

    module.st = SimpleNamespace(session_state=session_state, sidebar=SimpleNamespace(text_input=text_input))

    assert module._state_text_input("demo_key", "Demo label", "default") == "default"
    assert session_state["demo_key"] == "default"
    session_state["demo_key"] = "kept"
    assert module._state_text_input("demo_key", "Demo label", "other") == "kept"
    assert calls == [("Demo label", "demo_key"), ("Demo label", "demo_key")]
