"""Core analysis functions for the Text Atlas project.

Provides load_corpus() and analyze() used by both the Streamlit app
and the solution notebook.
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

_DATA_PATH = Path(__file__).resolve().parent / "data" / "wiki_news.csv"


def load_corpus() -> pd.DataFrame:
    """Load the 1,250-row Wikinews corpus.

    Returns a DataFrame with columns 'text' and 'category' in the
    original file order.
    """
    df = pd.read_csv(_DATA_PATH)
    if len(df) != 1250:
        raise ValueError(f"Expected 1250 rows, got {len(df)}")
    if not {"text", "category"}.issubset(df.columns):
        raise ValueError(
            f"Expected columns 'text' and 'category', got {list(df.columns)}"
        )
    return df.reset_index(drop=True)


def _validate_params(
    n_clusters: int, min_df: int, max_df: float, seed: int
) -> None:
    """Validate and raise on out-of-range inputs."""
    if isinstance(n_clusters, bool) or not isinstance(n_clusters, (int, np.integer)):
        raise ValueError("n_clusters must be an integer (not bool)")
    if not (2 <= n_clusters <= 8):
        raise ValueError(f"n_clusters must be in [2, 8], got {n_clusters}")

    if isinstance(min_df, bool) or not isinstance(min_df, (int, np.integer)):
        raise ValueError("min_df must be an integer (not bool)")
    if not (2 <= min_df <= 12):
        raise ValueError(f"min_df must be in [2, 12], got {min_df}")

    if isinstance(max_df, bool):
        raise ValueError("max_df must be a finite number (not bool)")
    max_df = float(max_df)
    if not np.isfinite(max_df):
        raise ValueError("max_df must be finite")
    if not (0.60 <= max_df <= 0.95):
        raise ValueError(f"max_df must be in [0.60, 0.95], got {max_df}")

    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
        raise ValueError("seed must be a non-negative integer (not bool)")
    if seed < 0:
        raise ValueError(f"seed must be non-negative, got {seed}")


def analyze(
    n_clusters: int = 5,
    min_df: int = 5,
    max_df: float = 0.8,
    seed: int = 42,
) -> dict:
    """Run the full TF-IDF → centered PCA(50) → KMeans pipeline.

    Returns a dict with keys:
        coordinates, labels, vocabulary, top_terms,
        silhouette, displayed_variance, retained_variance, parameters
    """
    _validate_params(n_clusters, min_df, max_df, seed)

    df = load_corpus()
    texts = df["text"].tolist()

    with threadpool_limits(limits=2):
        # TF-IDF vectorization with English stop-word removal
        vectorizer = TfidfVectorizer(
            min_df=min_df,
            max_df=max_df,
            stop_words="english",
            dtype=np.float32,
        )
        X_tfidf = vectorizer.fit_transform(texts)
        vocabulary = list(vectorizer.get_feature_names_out())

        # Dense float32 matrix (bounded at this corpus size)
        X_dense = X_tfidf.toarray()
        n_samples = X_dense.shape[0]

        # Total variance of original TF-IDF (ddof=1)
        total_var = float(np.var(X_dense, axis=0, ddof=1).sum())

        # Centered PCA – 50 retained components, randomized solver
        pca = PCA(n_components=50, svd_solver="randomized", random_state=seed)
        X_pca = pca.fit_transform(X_dense)

        # Variance of first two coordinates (ddof=1) relative to total
        pc1_var = float(np.var(X_pca[:, 0], ddof=1))
        pc2_var = float(np.var(X_pca[:, 1], ddof=1))
        displayed_variance = (pc1_var + pc2_var) / total_var

        # Variance retained by all 50 components (ddof=1) relative to total
        all_pc_var = float(np.var(X_pca, axis=0, ddof=1).sum())
        retained_variance = all_pc_var / total_var

        # KMeans on all 50 retained dimensions
        kmeans = KMeans(n_clusters=n_clusters, n_init=5, random_state=seed)
        labels = kmeans.fit_predict(X_pca)

        # Silhouette in the 50-D retained PCA space
        sil = float(silhouette_score(X_pca, labels))

        # Top terms from mean ORIGINAL TF-IDF weights of member documents
        top_terms: dict[str, list[str]] = {}
        for c in range(n_clusters):
            mask = labels == c
            member_tfidf = X_dense[mask]
            means = member_tfidf.mean(axis=0)
            top_idx = np.argsort(-means, kind="stable")[:6]
            top_terms[str(c)] = [vocabulary[i] for i in top_idx]

        coordinates = X_pca[:, :2]

    return {
        "coordinates": coordinates,
        "labels": labels,
        "vocabulary": vocabulary,
        "top_terms": top_terms,
        "silhouette": sil,
        "displayed_variance": float(displayed_variance),
        "retained_variance": float(retained_variance),
        "parameters": {
            "n_clusters": int(n_clusters),
            "min_df": int(min_df),
            "max_df": float(max_df),
            "seed": int(seed),
        },
    }
