"""Reusable analysis for the Text atlas app.

Adapts INRIA's dimred_text.ipynb (scikit-learn MOOC, CC BY 4.0):
TF-IDF with English stop-word removal, centered PCA (at most 50 retained
components, randomized solver, fixed seed) and KMeans in the retained PCA
space. Categories are never used as model input; they are a display and
evaluation overlay only.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score
from threadpoolctl import threadpool_limits

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CORPUS = PROJECT_ROOT / "data" / "wiki_news.csv"

MAX_PCA_COMPONENTS = 50
TOP_TERMS_PER_CLUSTER = 6

MIN_DF_RANGE = (2, 12)
MAX_DF_RANGE = (0.60, 0.95)
N_CLUSTERS_RANGE = (2, 8)
SEED_RANGE = (0, 10000)


def load_corpus(path=None) -> pd.DataFrame:
    """Load the Wikinews corpus and validate it.

    The document order is the CSV row order, so repeated loads are
    deterministic.
    """
    if path is None:
        path = DEFAULT_CORPUS
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"Corpus file not found: {path}")

    frame = pd.read_csv(path)
    if list(frame.columns) != ["category", "text"]:
        raise ValueError(f"Corpus must have columns ['category', 'text'], got {list(frame.columns)}")
    if not 1 <= len(frame) <= 1_000_000:
        raise ValueError(f"Corpus row count out of bounded range: {len(frame)}")
    if frame["text"].isna().any() or frame["category"].isna().any():
        raise ValueError("Corpus contains missing values")
    text = frame["text"]
    if not text.map(lambda value: isinstance(value, str)).all():
        raise ValueError("Corpus 'text' column must contain strings")
    frame = frame.reset_index(drop=True)
    frame["category"] = frame["category"].astype(str)
    frame["text"] = text.astype(str)
    return frame


def _validate_parameters(min_df, max_df, n_clusters, seed) -> dict:
    if isinstance(min_df, bool) or not isinstance(min_df, int):
        raise ValueError(f"min_df must be an integer, got {min_df!r}")
    if not (MIN_DF_RANGE[0] <= min_df <= MIN_DF_RANGE[1]):
        raise ValueError(f"min_df must be in {MIN_DF_RANGE}, got {min_df}")
    if isinstance(max_df, bool) or not isinstance(max_df, (int, float)):
        raise ValueError(f"max_df must be a number, got {max_df!r}")
    max_df = float(max_df)
    if not np.isfinite(max_df) or not (MAX_DF_RANGE[0] <= max_df <= MAX_DF_RANGE[1]):
        raise ValueError(f"max_df must be finite and in {MAX_DF_RANGE}, got {max_df}")
    if isinstance(n_clusters, bool) or not isinstance(n_clusters, int):
        raise ValueError(f"n_clusters must be an integer, got {n_clusters!r}")
    if not (N_CLUSTERS_RANGE[0] <= n_clusters <= N_CLUSTERS_RANGE[1]):
        raise ValueError(f"n_clusters must be in {N_CLUSTERS_RANGE}, got {n_clusters}")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError(f"seed must be an integer, got {seed!r}")
    if not (SEED_RANGE[0] <= seed <= SEED_RANGE[1]):
        raise ValueError(f"seed must be in {SEED_RANGE}, got {seed}")
    return {
        "min_df": min_df,
        "max_df": max_df,
        "n_clusters": n_clusters,
        "seed": seed,
    }


def _top_terms(X_tfidf, vocabulary, labels, n_clusters) -> dict:
    top_terms = {}
    for cluster_id in range(n_clusters):
        members = X_tfidf[labels == cluster_id]
        if members.shape[0] == 0:
            top_terms[str(cluster_id)] = []
            continue
        mean_weights = members.mean(axis=0)
        order = np.argsort(-mean_weights, kind="stable")
        top_terms[str(cluster_id)] = [vocabulary[index] for index in order[:TOP_TERMS_PER_CLUSTER]]
    return top_terms


def analyze(min_df=5, max_df=0.8, n_clusters=5, seed=42) -> dict:
    """Run the full Text atlas pipeline and return display-ready results.

    Pipeline (following the pinned INRIA notebook):
    1. TF-IDF with English stop-word removal on the corpus text.
    2. Centered PCA (sklearn PCA, randomized solver, fixed seed) with at
       most MAX_PCA_COMPONENTS retained components.
    3. KMeans clustering in the retained PCA space.

    Cluster top words are computed from the mean original TF-IDF weights of
    the member documents, never from PCA centroid indices.
    """
    parameters = _validate_parameters(min_df, max_df, n_clusters, seed)
    frame = load_corpus()
    n_samples = len(frame)

    with threadpool_limits(limits=2):
        vectorizer = TfidfVectorizer(
            min_df=parameters["min_df"],
            max_df=parameters["max_df"],
            stop_words="english",
            dtype=np.float32,
        )
        X_tfidf = vectorizer.fit_transform(frame["text"]).toarray()
        n_features = X_tfidf.shape[1]
        if not np.isfinite(X_tfidf).all():
            raise ValueError("TF-IDF matrix contains non-finite values")

        n_components = min(MAX_PCA_COMPONENTS, n_samples - 1, n_features)
        pca = PCA(
            n_components=n_components,
            svd_solver="randomized",
            random_state=parameters["seed"],
        )
        X_pca = pca.fit_transform(X_tfidf)
        if not np.isfinite(X_pca).all():
            raise ValueError("PCA projection contains non-finite values")

        kmeans = KMeans(
            n_clusters=parameters["n_clusters"],
            n_init=5,
            random_state=parameters["seed"],
        )
        labels = kmeans.fit_predict(X_pca)
        silhouette = float(silhouette_score(X_pca, labels))

    vocabulary = list(vectorizer.get_feature_names_out())
    result = {
        "coordinates": X_pca[:, :2].astype(np.float64),
        "labels": labels.astype(int),
        "vocabulary": vocabulary,
        "top_terms": _top_terms(X_tfidf, vocabulary, labels, parameters["n_clusters"]),
        "silhouette": silhouette,
        "displayed_variance": float(pca.explained_variance_ratio_[:2].sum()),
        "retained_variance": float(pca.explained_variance_ratio_.sum()),
        "parameters": {
            **parameters,
            "n_samples": n_samples,
            "n_features": int(n_features),
            "n_components": int(n_components),
        },
    }
    return result
