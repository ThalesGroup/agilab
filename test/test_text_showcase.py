"""Publication boundaries and real interactions of the third notebook demo."""
import hashlib
import io
import json
import shutil
import sys
from types import ModuleType
import zipfile

import pytest
from streamlit.testing.v1 import AppTest

from agilab.agent_runtime import text_showcase as showcase


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    root = tmp_path / "bundle"
    shutil.copytree(showcase.DEMO_ROOT, root, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(showcase, "DEMO_ROOT", root)
    return root


def page():
    from agilab.agent_runtime.text_showcase import render
    render()


def test_download_is_complete_and_matches_verified_bytes():
    report = showcase.load_report()
    assert report["workflow_stages"] == 1
    assert report["build_model"]["id"] == "ddalcu/Qwen3.8-27B-MLX-Serve-4bit"
    assert report["build_model"]["cloud_codegen_fallback"] is False
    assert report["verification"]["workflow"]["stage_count"] == report["workflow_stages"]
    assert report["source"]["license"] == "CC-BY-4.0"
    assert report["data"]["license"] == "CC-BY-2.5"
    with zipfile.ZipFile(io.BytesIO(showcase.download_bundle())) as archive:
        assert set(archive.namelist()) == showcase.PUBLIC_FILES | {"result.json"}
        for name, digest in report["files"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest


@pytest.mark.parametrize("name", ["app.py", "text_core.py", "data/wiki_news.csv", "DATA_LICENSE"])
def test_changed_assets_block_execution_and_download(bundle, name):
    (bundle / name).write_text("changed")
    with pytest.raises(ValueError, match="changed since verification"):
        showcase.download_bundle()
    at = AppTest.from_function(page).run()
    assert not at.exception and at.error
    assert not at.title and not at.slider


@pytest.mark.parametrize("name", ["../outside.py", "/outside.py", "./app.py", "data//wiki_news.csv"])
def test_manifest_paths_fail_closed(bundle, name):
    report = showcase.load_report()
    report["files"][name] = "0" * 64
    (bundle / "result.json").write_text(json.dumps(report))
    with pytest.raises(ValueError, match="manifest"):
        showcase.download_bundle()


@pytest.mark.parametrize("name", ["app.py", "result.json", "data"])
def test_symlinks_fail_closed(bundle, name):
    target = bundle.parent / (name + "-outside")
    (bundle / name).rename(target)
    (bundle / name).symlink_to(target, target_is_directory=target.is_dir())
    with pytest.raises(ValueError, match="symlink"):
        showcase.download_bundle()


@pytest.mark.parametrize("change", ["missing", "extra", "verification", "provenance"])
def test_incomplete_or_unverified_bundles_fail_closed(bundle, change):
    report = showcase.load_report()
    if change == "missing":
        del report["files"]["app.py"]
    elif change == "extra":
        (bundle / "surprise.py").write_text("raise AssertionError")
    elif change == "verification":
        report["verification"]["text"]["status"] = "failed"
    else:
        report["source"]["sha256"] = "0" * 64
    (bundle / "result.json").write_text(json.dumps(report))
    with pytest.raises(ValueError):
        showcase.load_report()


def test_verified_executor_restores_import_state_even_on_failure(monkeypatch):
    previous = ModuleType("text_core")
    monkeypatch.setitem(sys.modules, "text_core", previous)
    with pytest.raises(RuntimeError, match="fixture"):
        showcase._run_verified_app({"text_core.py": b"VALUE = 8", "app.py": b"raise RuntimeError('fixture')"})
    assert sys.modules["text_core"] is previous


def test_real_app_submits_changes_and_keeps_submitted_parameters():
    pytest.importorskip("sklearn")
    at = AppTest.from_function(page, default_timeout=90).run()
    assert not at.exception and not at.error
    assert sum(title.value == "Built by an autonomous agent" for title in at.title) == 1
    assert {item.label: item.value for item in at.metric}["Autonomous build"] == f"{showcase.load_report()['seconds'] / 60:.2f} min"
    assert all(item.label != "Autonomous build" for expander in at.expander for item in expander.metric)
    assert any(item.label == "Run analysis" for item in at.button)
    assert any("Qwen3.8-27B" in item.value for item in at.caption)
    assert not any(item.label == "Articles" for item in at.metric)
    next(item for item in at.button if item.label == "Run analysis").click().run()
    assert not at.exception and not at.error
    assert {item.label: item.value for item in at.metric}["Articles"] == "1250"
    assert at.dataframe[0].value["Cluster"].nunique() == 5
    at.slider(key="qwen_text_atlas_n_clusters").set_value(3).run()
    assert at.dataframe[0].value["Cluster"].nunique() == 5
    assert any("n_clusters=5" in item.value for item in at.caption)
    next(item for item in at.button if item.label == "Run analysis").click().run()
    assert not at.exception and not at.error
    assert at.dataframe[0].value["Cluster"].nunique() == 3
    at.radio(key="qwen_text_atlas_color_mode").set_value("Category").run()
    at.selectbox(key="qwen_text_atlas_article_selector").select(11).run()
    assert not at.exception and not at.error
    import pandas as pd
    expected_article = pd.read_csv(showcase.DEMO_ROOT / "data/wiki_news.csv").iloc[11]["text"]
    assert any(item.value.strip() == expected_article.strip() for item in at.text)
    assert at.dataframe[0].value["Cluster"].nunique() == 3
    assert {item.label: item.value for item in at.metric}["Articles"] == "1250"


def test_export_rejects_modified_autonomous_run(tmp_path):
    from tools.demos.export_text_notebook_demo import export_demo
    run = tmp_path / "run"
    project = run / "notebook_app_project"
    shutil.copytree(showcase.DEMO_ROOT, project, ignore=shutil.ignore_patterns("__pycache__"))
    (run / "result.json").write_bytes((project / "result.json").read_bytes())
    (project / "text_core.py").write_text("changed")
    with pytest.raises(ValueError, match="Autonomous-run artifact changed"):
        export_demo(run, tmp_path / "public")
    assert not (tmp_path / "public").exists()


@pytest.mark.parametrize("record_model", [True, False])
def test_exported_receipt_renders_with_optional_build_model(bundle, tmp_path, monkeypatch, record_model):
    from tools.demos import export_text_notebook_demo as exporter

    report = json.loads((bundle / "result.json").read_text())
    if not record_model:
        report.pop("build_model")
    else:
        report["build_model"]["private_endpoint"] = "must-not-be-exported"
    run = tmp_path / "run"
    shutil.copytree(bundle, run / "notebook_app_project")
    (run / "result.json").write_text(json.dumps(report))
    monkeypatch.setattr(exporter, "validate_analysis", lambda project: report["verification"]["text"])
    destination = tmp_path / "exported"
    exported = exporter.export_demo(run, destination)
    monkeypatch.setattr(showcase, "DEMO_ROOT", destination)
    app = AppTest.from_function(page).run(timeout=30)
    assert not app.exception
    labels = " ".join(item.value for item in app.caption)
    if record_model:
        assert exported["build_model"]["id"] in labels
        assert "private_endpoint" not in exported["build_model"]
    else:
        assert "build_model" not in exported
        assert "Build model:" not in labels


@pytest.mark.parametrize("model", [[], {"id": ""}, {"id": "Qwen", "provider": 1, "execution": "local"}])
def test_invalid_build_model_is_rejected(bundle, model):
    receipt = bundle / "result.json"
    report = json.loads(receipt.read_text())
    report["build_model"] = model
    receipt.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="build model metadata"):
        showcase.load_report()
