"""Real bounded text clustering and input contracts for all shipped Text Atlas variants."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(params=["text_notebook_demo", "text_notebook_demo_astra", "text_notebook_demo_rtx"])
def text_core(request):
    path = Path(__file__).resolve().parents[1] / "src/agilab/demos/resources" / request.param / "text_core.py"
    spec = importlib.util.spec_from_file_location("_text_contract_" + request.param, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("parameter,value", [
    ("n_clusters", True), ("n_clusters", 2.5), ("n_clusters", 1), ("n_clusters", 9),
    ("min_df", False), ("min_df", 2.5), ("min_df", 1), ("min_df", 13),
    ("max_df", True), ("max_df", float("nan")), ("max_df", float("inf")),
    ("max_df", 0.59), ("max_df", 0.96), ("max_df", "not-a-number"),
    ("seed", True), ("seed", 0.5), ("seed", -1),
])
def test_invalid_text_parameters_are_rejected_before_loading_corpus(text_core, monkeypatch, parameter, value):
    def unexpected():
        pytest.fail("invalid parameters must not read the dataset")
    monkeypatch.setattr(text_core, "load_corpus", unexpected)
    with pytest.raises(ValueError):
        text_core.analyze(**{parameter: value})


def test_real_text_pipeline_is_repeatable_and_category_blind(text_core, monkeypatch):
    topics = ["orchard apple fruit harvest", "satellite rocket orbit planet", "ocean coral marine water"]
    frame = pd.DataFrame({
        "category": ["DISPLAY_ONLY_" + str(i % 3) for i in range(120)],
        "text": [topics[i % 3] + " " + " ".join(f"feature_{(i + j * 7) % 80}" for j in range(8))
                 for i in range(120)],
    })
    before = frame.copy(deep=True)
    monkeypatch.setattr(text_core, "load_corpus", lambda: frame)
    first = text_core.analyze(n_clusters=3, min_df=2, max_df=0.95, seed=7)
    pd.testing.assert_frame_equal(frame, before)
    frame["category"] = "REPLACED_CATEGORY_NEVER_A_FEATURE"
    second = text_core.analyze(n_clusters=3, min_df=2, max_df=0.95, seed=7)
    np.testing.assert_allclose(first["coordinates"], second["coordinates"], rtol=0, atol=1e-7)
    np.testing.assert_array_equal(first["labels"], second["labels"])
    assert first["coordinates"].shape == (120, 2)
    assert set(first["labels"]) == {0, 1, 2}
    assert np.isfinite(first["coordinates"]).all()
    assert -1 <= first["silhouette"] <= 1
    assert 0 <= first["displayed_variance"] <= first["retained_variance"] + 1e-6 <= 1.00001
    assert not any("category" in word.lower() or "display" in word.lower() for word in first["vocabulary"])
    assert set(first["top_terms"]) == {"0", "1", "2"}
    assert all(len(terms) == 6 and set(terms) <= set(first["vocabulary"])
               for terms in first["top_terms"].values())


@pytest.mark.parametrize("missing", ["text", "category"])
def test_corpus_load_rejects_missing_contract_column(text_core, monkeypatch, tmp_path, missing):
    frame = pd.DataFrame({"category": ["news"] * 1250, "text": ["sample article"] * 1250}).drop(columns=missing)
    marker = tmp_path / "corpus.csv"
    marker.touch()
    for name in ("_DATA_PATH", "CORPUS_PATH", "DEFAULT_CORPUS"):
        if hasattr(text_core, name):
            monkeypatch.setattr(text_core, name, marker)
    monkeypatch.setattr(text_core, "pd", SimpleNamespace(read_csv=lambda *a, **k: frame.copy()))
    with pytest.raises(ValueError):
        text_core.load_corpus()


def test_corpus_load_preserves_order_and_normalizes_index(text_core, monkeypatch, tmp_path):
    frame = pd.DataFrame({"category": ["news"] * 1250, "text": [f"article {i}" for i in range(1250)]},
                         index=list(reversed(range(1250))))
    marker = tmp_path / "corpus.csv"
    frame.to_csv(marker, index=False)
    for name in ("_DATA_PATH", "CORPUS_PATH", "DEFAULT_CORPUS"):
        if hasattr(text_core, name):
            monkeypatch.setattr(text_core, name, marker)
    result = text_core.load_corpus()
    assert result.index.tolist() == list(range(1250))
    assert result["text"].tolist() == frame["text"].tolist()
