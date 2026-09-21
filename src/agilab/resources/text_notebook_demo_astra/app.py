"""Native Streamlit explorer for the historical Wikinews corpus."""

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from text_core import analyze, load_corpus


st.set_page_config(page_title="Text atlas", page_icon=":material/hub:", layout="wide")
st.title("Text atlas")
st.caption(
    "INRIA scikit-learn MOOC · notebook CC BY 4.0 · "
    "Historical Wikinews corpus: contributors, curated by Mega Rhyme · CC BY 2.5"
)
st.markdown("Explore how shared vocabulary brings 1,250 historical articles together.")


@st.cache_data(max_entries=8, show_spinner=False)
def cached_analysis(min_df, max_df, n_clusters, seed):
    return analyze(min_df=min_df, max_df=max_df, n_clusters=n_clusters, seed=seed)


with st.form("analysis_form", border=True):
    with st.container(horizontal=True, wrap=True, gap="medium"):
        n_clusters = st.slider("Clusters", 2, 8, 5, key="cluster_count", width=240)
        min_df = st.slider(
            "Minimum documents per word", 2, 12, 5,
            key="minimum_frequency", width=240,
        )
        max_df = st.slider(
            "Maximum document share per word", 0.60, 0.95, 0.80, 0.01,
            key="maximum_frequency", width=280, format="%.2f",
        )
        seed = st.number_input(
            "Random seed", min_value=0, max_value=10000, value=42, step=1,
            key="random_seed", width=180,
        )
    submitted = st.form_submit_button(
        "Run analysis", key="run_analysis", type="primary", width="content"
    )
    st.caption("Controls take effect on submit. The map keeps the last successful result.")

if submitted:
    try:
        with st.spinner("Mapping article vocabulary…"):
            result = cached_analysis(min_df, max_df, n_clusters, seed)
        st.session_state["analysis_result"] = result
    except (ValueError, OSError) as exc:
        st.error(f"Analysis could not finish: {exc}")

if "analysis_result" not in st.session_state:
    st.info("Choose your settings and select Run analysis to build the map.")
else:
    result = st.session_state["analysis_result"]
    corpus = load_corpus()
    params = result["parameters"]
    st.subheader("Vocabulary map")
    st.caption(
        f"Last submitted analysis · {params['n_clusters']} clusters · "
        f"min_df={params['min_df']} · max_df={params['max_df']:.2f} · "
        f"seed={params['seed']} · {params['n_components']} retained PCA components"
    )
    color_by = st.radio(
        "Color articles by", ["Cluster", "Original category"],
        horizontal=True, key="color_by",
    )
    plot_data = pd.DataFrame({
        "PC1": result["coordinates"][:, 0],
        "PC2": result["coordinates"][:, 1],
        "Article": np.arange(1, len(corpus) + 1),
        "Cluster": [f"Cluster {label}" for label in result["labels"]],
        "Original category": corpus["category"],
        "Preview": [" ".join(text.split())[:157] + "…" for text in corpus["text"]],
    })
    chart = (
        alt.Chart(plot_data)
        .mark_circle(size=38, opacity=0.65)
        .encode(
            x=alt.X("PC1:Q", title="Principal component 1"),
            y=alt.Y("PC2:Q", title="Principal component 2"),
            color=alt.Color(
                f"{color_by}:N", scale=alt.Scale(scheme="tableau10"),
                legend=alt.Legend(orient="bottom", title=None),
            ),
            tooltip=[
                alt.Tooltip("Article:Q", format="d"),
                alt.Tooltip("Cluster:N"),
                alt.Tooltip("Original category:N"),
                alt.Tooltip("Preview:N"),
            ],
        )
        .properties(height=480)
        .interactive()
    )
    st.altair_chart(chart, width="stretch", key="vocabulary_map")
    st.caption(
        "Nearby points reflect shared vocabulary. Clusters are not validated topics. "
        "The 2D projection drops detail; original categories are a display overlay only."
    )
    with st.container(horizontal=True, wrap=True, gap="medium"):
        st.metric("Articles", f"{len(corpus):,}", border=True, width=210)
        st.metric("Vocabulary size", f"{len(result['vocabulary']):,}", border=True, width=210)
        st.metric(
            "Silhouette", f"{result['silhouette']:.3f}", border=True, width=210,
            help="An internal diagnostic in the retained PCA space, from −1 to 1. Not accuracy.",
        )
        st.metric(
            "Original variance visible in 2D", f"{result['displayed_variance']:.1%}",
            border=True, width=290,
        )
    st.caption(
        f"All {params['n_components']} retained components explain "
        f"{result['retained_variance']:.1%} of original TF-IDF variance. "
        "Silhouette is an internal diagnostic of separation in that retained space."
    )

    st.subheader("Words within each cluster")
    st.caption("Six words with the highest mean original TF-IDF weight among member articles.")
    terms_table = pd.DataFrame([
        {
            "Cluster": f"Cluster {cluster}",
            "Documents": int(np.count_nonzero(result["labels"] == int(cluster))),
            "Top words": ", ".join(words),
        }
        for cluster, words in result["top_terms"].items()
    ])
    st.dataframe(terms_table, hide_index=True, width="stretch", key="cluster_terms")

    st.subheader("Read an article")
    article = st.selectbox(
        "Article in original corpus order", range(len(corpus)),
        format_func=lambda index: f"Article {index + 1:04d}", key="article_selection",
    )
    with st.container(border=True):
        st.text(
            f"Article {article + 1:04d} · Cluster {result['labels'][article]} · "
            f"Original category: {corpus.iloc[article]['category']}"
        )
        st.text(corpus.iloc[article]["text"], width="stretch")

with st.expander("About the source and method"):
    st.markdown(
        "Adapted from INRIA's [Dimensionality reduction of text data]"
        "(https://github.com/INRIA/scikit-learn-mooc/blob/"
        "3d1e8cdf7df6675d8a47d352d66b29dfea36587c/notebooks/dimred_text.ipynb). "
        "English stop-word TF-IDF → centered randomized PCA (up to 50 components) "
        "→ KMeans in the retained space. CPU thread pools are limited to two threads."
    )
    st.caption(
        "The historical corpus is reproduced unchanged. See LICENSE for the notebook's "
        "CC BY 4.0 terms, DATA_LICENSE for the corpus's separate CC BY 2.5 notice, "
        "and NOTICE for adaptation details."
    )
