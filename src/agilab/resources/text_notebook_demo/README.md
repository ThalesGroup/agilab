# Text atlas

A native Streamlit explorer and executable workflow for the actual 1,250-row
historical Wikinews corpus used by INRIA's scikit-learn MOOC. This is the third
Tokki + AGILAB public notebook demo.

Pinned source notebook:
https://github.com/INRIA/scikit-learn-mooc/blob/3d1e8cdf7df6675d8a47d352d66b29dfea36587c/notebooks/dimred_text.ipynb

The lesson was introduced on 2026-08-05; the pinned notebook was updated on
2026-09-02. `source/original.ipynb` and its provenance are preserved as source
material, never imported or executed.

## Run

Python 3.12–3.14 is supported. From this project directory, to create a local
environment and install declared dependencies with uv:

```sh
uv sync
uv run streamlit run app.py
```

For an existing environment with these packages already installed:

```sh
python -m streamlit run app.py
```

No install is needed in the supplied AGILAB environment. No API, credential,
data download, or external service is used by the analysis or app.

To execute the three Python stages of `solution.ipynb` from any directory,
set `PROJECT_ROOT` to the project directory. This lightweight runner needs
only the declared dependencies and Python's standard library:

```sh
export PROJECT_ROOT=/path/to/text-atlas
uv run --project "$PROJECT_ROOT" python - <<'PY'
import json
import os
from pathlib import Path

root = Path(os.environ["PROJECT_ROOT"]).resolve()
namespace = {"PROJECT_ROOT": root, "__name__": "__main__"}
notebook = json.loads((root / "solution.ipynb").read_text())
for cell in notebook["cells"]:
    if cell["cell_type"] == "code":
        exec(compile("".join(cell["source"]), "solution.ipynb", "exec"), namespace)
PY
```

The notebook writes a fresh `results.json` to its execution directory, including
metrics, submitted parameters, coordinates, labels, vocabulary, and top terms.
It also accepts `PROJECT_ROOT` supplied directly in its Python namespace, as in
AGILAB's verifier.

## Analysis and interpretation

`text_core.load_corpus()` returns a DataFrame in unchanged CSV row order.
`text_core.analyze(min_df=5, max_df=0.8, n_clusters=5, seed=42)` uses the lesson's
English stop-word TF-IDF variant, dense float32 data, **centered PCA** with a
randomized solver and fixed seed, then KMeans with five initializations.
PCA retains at most 50 components, adapting the lesson's wider 2-, 4-, 300-,
and 900-component experiments for bounded CPU use. The t-SNE experiments are
omitted. All fitting and silhouette computation run within
`threadpoolctl.threadpool_limits(limits=2)`.

KMeans and silhouette use the full retained PCA space. Only the first two
coordinates are displayed. `displayed_variance` and `retained_variance` are
fractions of the **original centered TF-IDF variance**, not renormalized within
the retained space. Cluster top terms are the six largest mean original TF-IDF
weights of member documents, replacing inverse-transformed centroid inspection.
Vocabulary ties use a stable sort; document order follows the CSV.

Input limits: integer `min_df` 2–12, finite `max_df` 0.60–0.95, integer
`n_clusters` 2–8, integer `seed` 0–10000. Invalid inputs raise `ValueError`.
Categories are a display overlay only and never enter model fitting or silhouette.

Nearby points reflect vocabulary similarity; clusters are not validated topics.
The 2D map loses detail. Silhouette is an internal diagnostic, not accuracy.
The app computes only on **Run analysis**, keeps the last submitted result
labelled with its parameters, and caches at most eight analyses. Color and
article selection do not refit models. Article content is displayed as plain text.

## Source credit and separate licenses

- Notebook: INRIA scikit-learn MOOC contributors, **CC BY 4.0**. The supplied
  `LICENSE` is copied byte-for-byte.
- Corpus: Wikinews contributors, curated by **The Mega Rhyme Rhyming Dictionary**
  and subsampled by INRIA, **CC BY 2.5**. See the unchanged `DATA_LICENSE`
  and `DATA_SOURCES.md`; the latter contains the upstream collection's notices,
  with `wiki_news` identifying this corpus.

`data/wiki_news.csv` is an unchanged copy of the supplied data. These are
historical articles, not a live news feed. See `NOTICE` for modifications.

The supplied independent verifier checks fresh notebook execution, results output,
app startup, and the Run analysis interaction. Those checks establish execution
and interface behavior; they do not establish scientific equivalence to the lesson.
