"""Independently check and export a completed INRIA text notebook-agent run."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from agilab.agent_runtime.text_showcase import PUBLIC_FILES

COMMIT = "3d1e8cdf7df6675d8a47d352d66b29dfea36587c"
SOURCE_HASH = "f0c28461d6efd5b15a60337b4cff6973922addd90cc36e5e093a6a603df5cef2"
CORPUS_HASH = "b4546c2bfaa4499c6a079e9379e825dd4695d4382355c0ac9dd8da1a6da42818"
CORE_FILES = {"app.py", "text_core.py", "solution.ipynb", "lab_stages.toml", "pyproject.toml"}


def validate_analysis(project: Path) -> dict:
    """Check the adaptation numerically, including two common projection mistakes."""
    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics import silhouette_score
    from threadpoolctl import threadpool_limits

    spec = importlib.util.spec_from_file_location("validated_text_core", project / "text_core.py")
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    corpus = core.load_corpus()
    assert len(corpus) == 1250 and corpus.category.nunique() == 5
    result = core.analyze()
    assert result["coordinates"].shape == (1250, 2)
    with threadpool_limits(limits=2):
        vectorizer = TfidfVectorizer(min_df=5, max_df=0.8, stop_words="english", dtype=np.float32)
        original = vectorizer.fit_transform(corpus.text)
        dense = original.toarray()
        pca = PCA(n_components=50, svd_solver="randomized", random_state=42)
        retained = pca.fit_transform(dense)
        labels = KMeans(n_clusters=5, n_init=5, random_state=42).fit_predict(retained)
        np.testing.assert_array_equal(result["labels"], labels)
        np.testing.assert_allclose(result["coordinates"], retained[:, :2], atol=1e-6)
        total_variance = np.var(dense, axis=0, ddof=1).sum()
        np.testing.assert_allclose(result["displayed_variance"],
                                   np.var(retained[:, :2], axis=0, ddof=1).sum() / total_variance,
                                   rtol=2e-5)
        np.testing.assert_allclose(result["retained_variance"],
                                   np.var(retained, axis=0, ddof=1).sum() / total_variance,
                                   rtol=2e-5)
        np.testing.assert_allclose(result["silhouette"], silhouette_score(retained, labels), atol=1e-6)
        vocabulary = vectorizer.get_feature_names_out()
        assert result["vocabulary"] == vocabulary.tolist()
        for cluster in range(5):
            means = np.asarray(original[labels == cluster].mean(axis=0)).ravel()
            expected = vocabulary[np.argsort(-means, kind="stable")[:6]].tolist()
            assert result["top_terms"][str(cluster)] == expected
    # A fresh function call, not a cache hit, establishes seed reproducibility.
    again = core.analyze()
    np.testing.assert_array_equal(result["labels"], again["labels"])
    np.testing.assert_allclose(result["coordinates"], again["coordinates"], atol=1e-6)
    original_loader = core.load_corpus
    core.load_corpus = lambda: corpus.assign(category="irrelevant")
    try:
        overlay = core.analyze()
        np.testing.assert_array_equal(result["labels"], overlay["labels"])
        np.testing.assert_allclose(result["coordinates"], overlay["coordinates"], atol=1e-6)
    finally:
        core.load_corpus = original_loader
    cases = []
    for count, minimum, maximum in ((2, 2, 0.95), (8, 12, 0.60)):
        case = core.analyze(n_clusters=count, min_df=minimum, max_df=maximum)
        assert len(np.unique(case["labels"])) == count
        assert np.isfinite(case["coordinates"]).all() and np.isfinite(case["silhouette"])
        cases.append({"clusters": count, "vocabulary": len(case["vocabulary"]),
                      "silhouette": case["silhouette"]})
    assert cases[0]["vocabulary"] > len(result["vocabulary"]) > cases[1]["vocabulary"]
    for kwargs in ({"min_df": True}, {"min_df": 1}, {"n_clusters": 9}, {"seed": -1},
                   {"max_df": float("nan")}, {"max_df": 0.99}):
        try:
            core.analyze(**kwargs)
        except ValueError:
            continue
        raise AssertionError(f"Invalid inputs accepted: {kwargs}")
    notebook = json.loads((project / "results.json").read_text())["results"]
    for key in ("labels", "coordinates", "displayed_variance", "retained_variance", "silhouette"):
        np.testing.assert_allclose(notebook[key], result[key], atol=1e-6)
    assert notebook["top_terms"] == result["top_terms"]
    return {"status": "passed", "checks": [
        "pinned_source_and_corpus", "centered_pca_and_original_variance",
        "cluster_terms_from_original_tfidf", "retained_space_silhouette",
        "uncached_seed_reproducibility", "categories_excluded_from_fitting",
        "parameter_extremes_and_invalid_inputs", "notebook_core_agreement",
    ], "measurements": {"articles": len(corpus), "vocabulary": len(result["vocabulary"]),
                         "displayed_variance": result["displayed_variance"],
                         "retained_variance": result["retained_variance"],
                         "silhouette": result["silhouette"], "cases": cases}}


def export_demo(run: Path, destination: Path) -> dict:
    report = json.loads((run / "result.json").read_text())
    if report.get("status") != "passed" or report.get("verification", {}).get("status") != "passed":
        raise ValueError("A passed autonomous notebook-agent run is required")
    source = report["source"]
    if (source["repository"] != "INRIA/scikit-learn-mooc" or source["commit"] != COMMIT
            or source["sha256"] != SOURCE_HASH
            or source["url"] != f"https://github.com/INRIA/scikit-learn-mooc/blob/{COMMIT}/notebooks/dimred_text.ipynb"):
        raise ValueError("Unexpected notebook provenance")
    project = run / "notebook_app_project"
    if project.is_symlink():
        raise ValueError("Project must not be a symlink")
    payload = {}
    for name in sorted(PUBLIC_FILES):
        path = project
        for part in Path(name).parts:
            path = path / part
            if path.is_symlink():
                raise ValueError(f"Symlinked public asset: {name}")
        payload[name] = path.read_bytes()
    files = {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()}
    for name in CORE_FILES:
        if files[name] != report["files"].get(name):
            raise ValueError(f"Autonomous-run artifact changed: {name}")
    if files["source/original.ipynb"] != SOURCE_HASH or files["data/wiki_news.csv"] != CORPUS_HASH:
        raise ValueError("Pinned source or corpus changed")
    if (destination.is_symlink() or any(p.is_symlink() for p in destination.absolute().parents)
            or (destination.exists() and any(destination.iterdir()))):
        raise ValueError("Export destination must be an empty real directory")
    checks = validate_analysis(project)
    # Execution must not change any of the bytes checked and exported above.
    if any((project / name).read_bytes() != data for name, data in payload.items()):
        raise ValueError("Public assets changed during verification")
    public = {
        "schema": "agilab.notebook_agent.public_demo.v1", "status": "passed",
        "run_id": run.name, "seconds": report["seconds"], "workflow_stages": report["workflow_stages"],
        "source": {**{key: source[key] for key in ("repository", "commit", "url", "sha256", "retrieved_at")},
                   "license": "CC-BY-4.0", "author": "INRIA scikit-learn MOOC contributors"},
        "data": {"license": "CC-BY-2.5", "sha256": CORPUS_HASH,
                 "attribution": "Wikinews contributors, curated by Mega Rhyme and subsampled by INRIA"},
        "demo": {"title": "Text atlas", "description": "Explore shared vocabulary across 1,250 historical articles."},
        "verification_scope": "execution_interface_and_bounded_text_adaptation",
        "verification": {**report["verification"], "text": checks}, "files": files,
    }
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in payload.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (destination / "result.json").write_text(json.dumps(public, indent=2, allow_nan=False) + "\n")
    return public


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    result = export_demo(args.run, args.destination)
    print(json.dumps({"status": result["status"], "verification": result["verification"]["text"]}))
