# Text atlas

A polished, CPU-friendly 2D "atlas" of the 1,250-article historical Wikinews
corpus. It adapts INRIA's scikit-learn MOOC dimensionality-reduction lesson on
text: TF-IDF with English stop-word removal, centered PCA, and KMeans in the
retained PCA space. Categories are a display/evaluation overlay only and are
never used as model input.

## Pinned source notebook

The analysis is adapted from this exact pinned notebook (do not fetch or
execute it; the local corpus and `text_core.py` are the source of truth):

<https://github.com/INRIA/scikit-learn-mooc/blob/3d1e8cdf7df6675d8a47d352d66b29dfea36587c/notebooks/dimred_text.ipynb>

- Repository: `INRIA/scikit-learn-mooc`
- Commit: `3d1e8cdf7df6675d8a47d352d66b29dfea36587c`
- Lesson introduced 2026-08-05; pinned notebook updated 2026-09-02.

## Licenses (kept separate)

- **Notebook / code:** CC BY 4.0 — INRIA scikit-learn MOOC contributors. Full
  text in [`LICENSE`](LICENSE).
- **Corpus:** CC BY 2.5 — Wikinews contributors, curated by The Mega Rhyme
  Rhyming Dictionary, then subsampled by the INRIA scikit-learn MOOC. Full
  notice in [`DATA_LICENSE`](DATA_LICENSE); provenance in
  [`DATA_SOURCES.md`](DATA_SOURCES.md). The corpus is redistributed unchanged
  as `data/wiki_news.csv`.

## Pipeline

`text_core.py` (shared by `app.py` and `solution.ipynb`):

1. `load_corpus()` reads `data/wiki_news.csv` (columns `category`, `text`) in
   its original row order, so results are deterministic.
2. `TfidfVectorizer(min_df, max_df, stop_words="english")` → dense `float32`
   matrix (bounded at this corpus size).
3. Centered PCA (`svd_solver="randomized"`, fixed `random_state=seed`) with at
   most **50 retained components**.
4. KMeans (`random_state=seed`) in the retained PCA space.
5. Cluster top words are the top terms of the **mean original TF-IDF weights**
   of each cluster's member documents (not PCA centroid indices).
6. `threadpoolctl.threadpool_limits(limits=2)` bounds CPU use.

`analyze(min_df=5, max_df=0.8, n_clusters=5, seed=42)` returns a dict with
`coordinates` (N×2), `labels`, `vocabulary`, `top_terms`, `silhouette`
(computed on the retained PCA space), `displayed_variance` (variance of the
first two PCs relative to the original TF-IDF data), `retained_variance`
(variance kept by all retained components), and `parameters`. Input bounds:
`min_df` 2..12, `max_df` 0.60..0.95, `n_clusters` 2..8, `seed` 0..10000;
out-of-range values are rejected cleanly.

## Run with uv

```bash
uv venv
uv pip install -r requirements.txt
uv run streamlit run app.py
```

Or run the notebook (it writes a fresh `results.json` to the current
directory):

```bash
uv run jupyter notebook solution.ipynb
```

## App

`app.py` is a native Streamlit page: a bordered form with sliders for cluster
count and vocabulary filtering, a **Run analysis** button, an Altair scatter
map (color by cluster or original category), a terms table with document
counts, an article selector showing plain text, and metrics for articles,
vocabulary size, silhouette, and original variance visible in 2D. Analysis is
computed only on submit and cached with a bounded `st.cache_data(max_entries=8)`.

## Interpretation

- Nearby points share similar TF-IDF vocabulary.
- KMeans clusters are geometric groupings, **not** validated topics.
- The 2D view drops detail (it keeps only `displayed_variance` of the original
  variance).
- Silhouette is an internal clustering diagnostic, not an accuracy score.

See [NOTICE](NOTICE) for the specific modifications made relative to the
upstream lesson.
