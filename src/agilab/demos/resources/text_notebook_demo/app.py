"""Text Atlas \u2013 Streamlit application."""

import streamlit as st
import altair as alt
import numpy as np
import pandas as pd

from text_core import load_corpus, analyze

st.title("Text Atlas")
st.caption(
    "Source: INRIA scikit-learn MOOC, *Dimensionality reduction of text data* "
    "(CC BY 4.0, INRIA scikit-learn MOOC contributors). "
    "Corpus: Wikinews (CC BY 2.5, Wikinews contributors, curated by Mega Rhyme)."
)

df = load_corpus()

KEY_RESULT = "qwen_text_atlas_result"
KEY_PARAMS = "qwen_text_atlas_params"

with st.form("analysis_form", border=True):
    n_clusters = st.slider(
        "Number of clusters", min_value=2, max_value=8, value=5, step=1,
        key="qwen_text_atlas_n_clusters",
    )
    min_df = st.slider(
        "Min document frequency", min_value=2, max_value=12, value=5, step=1,
        key="qwen_text_atlas_min_df",
    )
    max_df = st.slider(
        "Max document frequency", min_value=0.60, max_value=0.95, value=0.80, step=0.05,
        key="qwen_text_atlas_max_df",
    )
    seed = st.number_input(
        "Random seed", min_value=0, max_value=10000, value=42, step=1,
        key="qwen_text_atlas_seed",
    )
    submitted = st.form_submit_button("Run analysis")

if submitted:
    result = analyze(n_clusters=n_clusters, min_df=min_df, max_df=max_df, seed=seed)
    st.session_state[KEY_RESULT] = result
    st.session_state[KEY_PARAMS] = result["parameters"]

# Warn if pending form controls differ from committed parameters
committed = st.session_state.get(KEY_PARAMS)
if committed is not None:
    pending = {"n_clusters": n_clusters, "min_df": min_df, "max_df": max_df, "seed": seed}
    if pending != committed:
        st.warning(
            f"Committed parameters: n_clusters={committed['n_clusters']}, "
            f"min_df={committed['min_df']}, max_df={committed['max_df']:.2f}, "
            f"seed={committed['seed']} \u2014 click 'Run analysis' to apply changes."
        )

# Render persisted results (survives visual-control reruns)
if KEY_RESULT in st.session_state:
    result = st.session_state[KEY_RESULT]
    params = st.session_state[KEY_PARAMS]

    st.subheader("Results")
    st.caption(
        f"Parameters: n_clusters={params['n_clusters']}, "
        f"min_df={params['min_df']}, max_df={params['max_df']:.2f}, "
        f"seed={params['seed']}"
    )

    # Metrics row
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Articles", len(result["coordinates"]))
    m2.metric("Vocabulary size", len(result["vocabulary"]))
    m3.metric("Silhouette (50-D)", f"{result['silhouette']:.4f}")
    m4.metric("Variance visible in 2-D", f"{result['displayed_variance']:.2%}")

    # Color selector (visual control \u2013 does not retrigger analysis)
    color_mode = st.radio(
        "Color by", ["Cluster", "Category"], key="qwen_text_atlas_color_mode"
    )

    # Build chart dataframe
    coords = result["coordinates"]
    previews = [
        t[:60] + "\u2026" if len(t) > 60 else t for t in df["text"].values
    ]
    chart_df = pd.DataFrame(
        {
            "PC1": coords[:, 0],
            "PC2": coords[:, 1],
            "cluster": [str(l) for l in result["labels"]],
            "category": df["category"].values,
            "preview": previews,
        }
    )

    color_field = "cluster" if color_mode == "Cluster" else "category"

    chart = (
        alt.Chart(chart_df)
        .mark_point(size=10, opacity=0.7)
        .encode(
            x=alt.X("PC1:Q", title="PC 1"),
            y=alt.Y("PC2:Q", title="PC 2"),
            color=alt.Color(f"{color_field}:N", title=color_mode),
            tooltip=[
                alt.Tooltip(f"{color_field}:N", title=color_mode),
                alt.Tooltip("preview:N", title="Preview"),
            ],
        )
        .properties(width=550, height=400)
    )

    st.altair_chart(chart, width="stretch")

    # Terms table with document counts
    st.subheader("Top terms per cluster")
    terms_rows = []
    for cid, words in result["top_terms"].items():
        count = int((result["labels"] == int(cid)).sum())
        for w in words:
            terms_rows.append({"Cluster": cid, "Term": w, "Documents": count})
    terms_df = pd.DataFrame(terms_rows)
    st.dataframe(terms_df, width="stretch", hide_index=True)

    # Article selector
    st.subheader("Article inspection")
    article_idx = st.selectbox(
        "Select an article",
        range(len(df)),
        format_func=lambda i: f"#{i} \u2013 {df['category'].iloc[i]}: {df['text'].iloc[i][:50]}\u2026",
        key="qwen_text_atlas_article_selector",
    )
    st.text(df["text"].iloc[article_idx])

    # Explanations
    st.info(
        "Nearby points share similar vocabulary. Clusters are not validated topics; "
        "they reflect vocabulary similarity in the reduced space. The 2-D projection "
        "drops most of the retained variance. Silhouette is an internal diagnostic, "
        "not a measure of topical accuracy."
    )
