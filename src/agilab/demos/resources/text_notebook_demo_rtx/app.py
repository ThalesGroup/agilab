"""Text atlas: a CPU-friendly 2D map of the Wikinews corpus.

Adapted from INRIA's scikit-learn MOOC notebook dimred_text.ipynb
(https://github.com/INRIA/scikit-learn-mooc/blob/3d1e8cdf7df6675d8a47d352d66b29dfea36587c/notebooks/dimred_text.ipynb,
CC BY 4.0). Corpus: historical Wikinews articles, CC BY 2.5, see
DATA_LICENSE and DATA_SOURCES.md.
"""
from __future__ import annotations

import pandas as pd
import altair as alt
import streamlit as st

import text_core

SOURCE_NOTEBOOK_URL = (
    "https://github.com/INRIA/scikit-learn-mooc/blob/"
    "3d1e8cdf7df6675d8a47d352d66b29dfea36587c/notebooks/dimred_text.ipynb"
)


@st.cache_data(max_entries=8)
def run_analysis(min_df: int, max_df: float, n_clusters: int, seed: int) -> dict:
    return text_core.analyze(min_df=min_df, max_df=max_df, n_clusters=n_clusters, seed=seed)


def _preview(text: str, limit: int = 140) -> str:
    flat = " ".join(str(text).split())
    return flat[:limit] + ("..." if len(flat) > limit else "")


def _terms_frame(result: dict) -> pd.DataFrame:
    labels = result["labels"]
    rows = []
    for cluster_id in sorted(result["top_terms"], key=int):
        rows.append(
            {
                "cluster": int(cluster_id),
                "documents": int((labels == int(cluster_id)).sum()),
                "top_terms": ", ".join(result["top_terms"][cluster_id]),
            }
        )
    return pd.DataFrame(rows, columns=["cluster", "documents", "top_terms"])


def _render_results(result: dict) -> None:
    params = result["parameters"]
    st.markdown(
        f"### Results (k={params['n_clusters']}, min_df={params['min_df']}, "
        f"max_df={params['max_df']}, seed={params['seed']})"
    )

    articles, vocab, silhouette, displayed = st.columns(4)
    articles.metric("Articles", f"{params['n_samples']}")
    vocab.metric("Vocabulary size", f"{len(result['vocabulary'])}")
    silhouette.metric("Silhouette (PCA space)", f"{result['silhouette']:.3f}")
    displayed.metric("Original variance in 2D", f"{result['displayed_variance'] * 100:.1f}%")

    frame = text_core.load_corpus()
    plot = pd.DataFrame(
        {
            "x": result["coordinates"][:, 0],
            "y": result["coordinates"][:, 1],
            "cluster": [str(label) for label in result["labels"]],
            "category": frame["category"],
            "text": [_preview(value) for value in frame["text"]],
            "article": [f"article {index}" for index in range(len(frame))],
        }
    )
    color_mode = st.radio(
        "Color by",
        options=["cluster", "category"],
        horizontal=True,
        key="color_mode",
    )
    color_field = "cluster" if color_mode == "cluster" else "category"
    chart = (
        alt.Chart(plot)
        .mark_point(size=14, opacity=0.7)
        .encode(
            x=alt.X("x:Q", title="PC1"),
            y=alt.Y("y:Q", title="PC2"),
            color=alt.Color(f"{color_field}:N", legend=alt.Legend(orient="right")),
            tooltip=[
                alt.Tooltip("article:N", title="Article"),
                alt.Tooltip(f"{color_field}:N", title="Group"),
                alt.Tooltip("text:N", title="Preview"),
            ],
        )
        .properties(title="TF-IDF + PCA (2D)", width="container", height=480)
    )
    st.altair_chart(chart, width="stretch")

    st.markdown(
        "Points close together share similar TF-IDF vocabulary. KMeans clusters "
        "are geometric groupings, not validated topics. The 2D view drops detail "
        f"(it keeps {result['displayed_variance'] * 100:.1f}% of the original variance; "
        f"all {params['n_components']} components keep "
        f"{result['retained_variance'] * 100:.1f}%). Silhouette is an internal "
        "clustering diagnostic, not an accuracy score."
    )

    left, right = st.columns(2)
    with left:
        st.markdown("**Cluster top words** (mean original TF-IDF weights)")
        st.dataframe(_terms_frame(result), width="stretch", height=300)
    with right:
        st.markdown("**Inspect an article**")
        options = {
            f"{index}. [{row.category}] {_preview(row.text, 60)}": index
            for index, row in frame.iterrows()
        }
        choice = st.selectbox(
            "Article",
            options=list(options),
            key="article_selector",
        )
        selected = options[choice]
        st.text(frame.loc[selected, "text"])


def main() -> None:
    st.title("Text atlas")
    st.caption(
        "Adapted from INRIA's dimred_text.ipynb "
        f"([notebook, CC BY 4.0]({SOURCE_NOTEBOOK_URL})). Corpus: historical "
        "Wikinews articles (CC BY 2.5; see DATA_LICENSE, DATA_SOURCES.md)."
    )

    with st.form("text_atlas_form", clear_on_submit=False, border=True):
        n_clusters = st.slider("Cluster count", min_value=2, max_value=8, value=5, key="n_clusters_slider")
        min_df = st.slider("Min document frequency", min_value=2, max_value=12, value=5, key="min_df_slider")
        max_df = st.slider(
            "Max document frequency (fraction)",
            min_value=0.60,
            max_value=0.95,
            value=0.80,
            step=0.05,
            key="max_df_slider",
        )
        seed = st.slider("Random seed", min_value=0, max_value=10000, value=42, key="seed_slider")
        submitted = st.form_submit_button("Run analysis")

    if submitted:
        try:
            result = run_analysis(min_df, float(max_df), n_clusters, seed)
        except ValueError as exc:
            st.error(f"Invalid parameters: {exc}")
            st.session_state.pop("last_result", None)
            result = None
        if result is not None:
            st.session_state["last_result"] = result

    stored = st.session_state.get("last_result")
    if stored is not None:
        _render_results(stored)


if __name__ == "__main__":
    main()
