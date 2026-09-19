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
    assert report["workflow_stages"] == 3
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
    assert {item.label: item.value for item in at.metric}["Autonomous build"] == "7.73 min"
    assert all(item.label != "Autonomous build" for expander in at.expander for item in expander.metric)
    assert any("Run analysis" in item.value for item in at.info)
    assert not any(item.label == "Articles" for item in at.metric)
    at.button(key="run_analysis").click().run()
    assert not at.exception and not at.error
    assert {item.label: item.value for item in at.metric}["Articles"] == "1,250"
    assert len(at.dataframe[0].value) == 5
    at.slider(key="cluster_count").set_value(3).run()
    assert len(at.dataframe[0].value) == 5
    assert any("5 clusters" in item.value for item in at.caption)
    at.button(key="run_analysis").click().run()
    assert not at.exception and not at.error
    assert len(at.dataframe[0].value) == 3
    at.radio(key="color_by").set_value("Original category").run()
    at.selectbox(key="article_selection").select(11).run()
    assert not at.exception and not at.error
    assert any("Article 0012" in item.value for item in at.text)


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
