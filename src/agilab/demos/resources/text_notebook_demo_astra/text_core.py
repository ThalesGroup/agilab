"""Bounded TF-IDF → centered PCA → KMeans adaptation of INRIA's lesson.

Categories are never used to fit or score the model. CSV row order is preserved.
See NOTICE, LICENSE, and DATA_LICENSE for source credit and modifications.
"""

from numbers import Integral, Real
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score
from threadpoolctl import threadpool_limits


CORPUS_PATH = Path(__file__).resolve().parent / "data" / "wiki_news.csv"


def load_corpus() -> pd.DataFrame:
    """Read the unchanged 1,250-document corpus in its original CSV order."""
    data = pd.read_csv(CORPUS_PATH, dtype={"text": str, "category": str})
    if len(data) != 1250 or not {"text", "category"}.issubset(data.columns):
        raise ValueError("Expected the supplied 1,250-row Wikinews corpus.")
    for column in ("text", "category"):
        if data[column].isna().any() or data[column].str.strip().eq("").any():
            raise ValueError(f"Corpus contains missing or empty {column} values.")
    return data.reset_index(drop=True)


def _integer(name: str, value: object, lower: int, upper: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError(f"{name} must be an integer from {lower} to {upper}.")
    if not lower <= value <= upper:
        raise ValueError(f"{name} must be an integer from {lower} to {upper}.")
    return int(value)


def analyze(min_df=5, max_df=0.8, n_clusters=5, seed=42) -> dict:
    """Analyze text only; return arrays aligned with load_corpus() row order.

    Variance values are fractions of the original centered TF-IDF variance,
    not fractions renormalized within the retained PCA representation.
    Silhouette uses Euclidean distances in all retained PCA components.
    """
    min_df = _integer("min_df", min_df, 2, 12)
    n_clusters = _integer("n_clusters", n_clusters, 2, 8)
    seed = _integer("seed", seed, 0, 10000)
    if (
        isinstance(max_df, bool)
        or not isinstance(max_df, Real)
        or not np.isfinite(max_df)
        or not 0.60 <= max_df <= 0.95
    ):
        raise ValueError("max_df must be a finite number from 0.60 to 0.95.")
    max_df = float(max_df)
    data = load_corpus()

    with threadpool_limits(limits=2):
        vectorizer = TfidfVectorizer(
            min_df=min_df, max_df=max_df, stop_words="english", dtype=np.float32
        )
        original = vectorizer.fit_transform(data["text"]).toarray()
        n_components = min(50, original.shape[0] - 1, original.shape[1] - 1)
        if n_components < 2:
            raise ValueError("Vocabulary filtering left too few features for PCA.")
        pca = PCA(
            n_components=n_components, svd_solver="randomized",
            random_state=seed, copy=True,
        )
        retained = pca.fit_transform(original)
        labels = KMeans(
            n_clusters=n_clusters, n_init=5, random_state=seed, algorithm="lloyd"
        ).fit_predict(retained)
        if len(np.unique(labels)) != n_clusters:
            raise ValueError("The corpus did not produce the requested distinct clusters.")
        silhouette = float(silhouette_score(retained, labels, metric="euclidean"))
        vocabulary = vectorizer.get_feature_names_out().tolist()
        top_terms = {}
        for cluster in range(n_clusters):
            mean_weights = original[labels == cluster].mean(axis=0)
            # Stable sorting resolves ties in the vectorizer's vocabulary order.
            indices = np.argsort(-mean_weights, kind="stable")[:6]
            top_terms[str(cluster)] = [vocabulary[index] for index in indices]

    return {
        "coordinates": retained[:, :2].copy(),
        "labels": labels,
        "vocabulary": vocabulary,
        "top_terms": top_terms,
        "silhouette": silhouette,
        "displayed_variance": float(pca.explained_variance_ratio_[:2].sum()),
        "retained_variance": float(pca.explained_variance_ratio_.sum()),
        "parameters": {
            "min_df": min_df, "max_df": max_df,
            "n_clusters": n_clusters, "seed": seed,
            "n_components": n_components, "stop_words": "english",
            "pca_solver": "randomized", "n_init": 5,
        },
    }
