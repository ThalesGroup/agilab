"""Iris Decision Lab.

An interactive decision lab adapted from the Iris decision-tree example in
chapter 6 of Aurélien Géron's "Hands-On Machine Learning with Scikit-Learn,
Keras & TensorFlow" (3rd edition, Apache-2.0):
https://github.com/ageron/handson-ml3/blob/e707c2d659abafb9b1f9fd927907619a128db8d7/06_decision_trees.ipynb

Run with: streamlit run app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
from matplotlib.colors import ListedColormap
from sklearn.metrics import accuracy_score, confusion_matrix
from sklearn.model_selection import train_test_split

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from models import FEATURE_NAMES, build_models, load_data

SOURCE_URL = (
    "https://github.com/ageron/handson-ml3/blob/"
    "e707c2d659abafb9b1f9fd927907619a128db8d7/06_decision_trees.ipynb"
)
CUSTOM_CMAP = ListedColormap(["#fafab0", "#9898ff", "#a0faa0"])

st.set_page_config(page_title="Iris Decision Lab", layout="wide")


@st.cache_data(show_spinner="Training models on a held-out split…")
def train_and_evaluate(max_depth: int, seed: int, split_seed: int) -> dict:
    """Fit each candidate model on 70% of the data, score on the 30% holdout."""
    X, y, names = load_data()
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, stratify=y, random_state=split_seed
    )
    fitted = {}
    for name, estimator in build_models(max_depth=max_depth, seed=seed).items():
        fitted[name] = estimator.fit(X_train, y_train)
    rows = []
    for name, model in fitted.items():
        rows.append(
            {
                "model": name,
                "train accuracy": round(float(accuracy_score(y_train, model.predict(X_train))), 3),
                "test accuracy": round(float(accuracy_score(y_test, model.predict(X_test))), 3),
            }
        )
    comparison = pd.DataFrame(rows).set_index("model")
    best = comparison["test accuracy"].idxmax()
    return {
        "X": X,
        "y": y,
        "X_train": X_train,
        "y_train": y_train,
        "X_test": X_test,
        "y_test": y_test,
        "fitted": fitted,
        "comparison": comparison,
        "best": best,
        "names": list(names),
    }


def plot_feature_pairs(X: pd.DataFrame, y, names, fitted_tree) -> None:
    """Scatter of the two petal features with the tree's decision regions.

    Adapted from Figure 6-2 of the source notebook (petal length/width view).
    """
    petal_idx = [FEATURE_NAMES.index("petal length (cm)"), FEATURE_NAMES.index("petal width (cm)")]
    x1 = X[FEATURE_NAMES[petal_idx[0]]].to_numpy()
    x2 = X[FEATURE_NAMES[petal_idx[1]]].to_numpy()
    lengths, widths = np.meshgrid(np.linspace(0, 7.2, 100), np.linspace(0, 3, 100))
    grid = np.c_[lengths.ravel(), widths.ravel()]
    full_grid = np.column_stack(
        [np.full(len(grid), 0.0)] * len(FEATURE_NAMES)
    )
    full_grid[:, petal_idx[0]] = grid[:, 0]
    full_grid[:, petal_idx[1]] = grid[:, 1]
    y_pred = fitted_tree.predict(pd.DataFrame(full_grid, columns=FEATURE_NAMES)).reshape(lengths.shape)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    axes[0].contourf(lengths, widths, y_pred, alpha=0.35, cmap=CUSTOM_CMAP)
    styles = ("yo", "bs", "g^")
    for idx, (name, style) in enumerate(zip(names, styles)):
        mask = y.to_numpy() == idx
        axes[0].plot(x1[mask], x2[mask], style, label=f"Iris {name}", markersize=6)
    axes[0].set_xlabel("Petal length (cm)")
    axes[0].set_ylabel("Petal width (cm)")
    axes[0].set_title("Petal view + decision regions")
    axes[0].axis([0, 7.2, 0, 3])
    axes[0].legend(loc="upper center", fontsize=8, ncol=3)

    sl = X[FEATURE_NAMES[0]].to_numpy()
    sw = X[FEATURE_NAMES[1]].to_numpy()
    for idx, name in enumerate(names):
        mask = y.to_numpy() == idx
        axes[1].scatter(sl[mask], sw[mask], label=f"Iris {name}", alpha=0.75, s=18)
    axes[1].set_xlabel("Sepal length (cm)")
    axes[1].set_ylabel("Sepal width (cm)")
    axes[1].set_title("Sepal view (other features)")
    axes[1].legend(loc="best", fontsize=8)
    fig.tight_layout()
    st.pyplot(fig)


def plot_confusion_matrix(model, X_test, y_test, names) -> None:
    cm = confusion_matrix(y_test, model.predict(X_test), labels=list(range(len(names))))
    fig, ax = plt.subplots(figsize=(5.2, 4.4))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(len(names)), names, rotation=30, ha="right")
    ax.set_yticks(range(len(names)), names)
    ax.set_xlabel("Predicted species")
    ax.set_ylabel("True species")
    for i in range(len(names)):
        for j in range(len(names)):
            ax.text(
                j, i, cm[i, j], ha="center", va="center",
                color="white" if cm[i, j] > cm.max() / 2 else "black",
            )
    fig.colorbar(im, ax=ax, ticks=range(cm.max() + 1))
    fig.tight_layout()
    st.pyplot(fig)


st.title("Iris Decision Lab")
st.caption(
    "Compare a decision tree, a random forest, and logistic regression on a "
    "held-out split of the Iris dataset. Adapted from Aurélien Géron's "
    f"decision-tree chapter (Apache-2.0): [source notebook]({SOURCE_URL}). "
    "Results describe this small 150-sample dataset only."
)

max_depth = st.slider(
    "Max tree depth",
    min_value=1,
    max_value=10,
    value=3,
    step=1,
    help="Depth cap for the decision tree and the random forest. Deeper "
    "models fit the training data more closely but may overfit.",
)
seed = st.number_input(
    "Random seed", min_value=0, max_value=9999, value=42, step=1,
    help="Shared seed for model training and the train/test split.",
)

results = train_and_evaluate(max_depth=max_depth, seed=seed, split_seed=seed)
comparison = results["comparison"]
best = results["best"]
names = results["names"]

st.subheader("Train vs. held-out test accuracy")
st.dataframe(comparison, width="stretch")

best_row = comparison.loc[best]
train_mean = comparison["train accuracy"].mean()
test_mean = comparison["test accuracy"].mean()
col_a, col_b, col_c = st.columns(3)
col_a.metric(
    f"Winner: {best}",
    f"{best_row['test accuracy']:.1%}",
    delta=f"{best_row['train accuracy'] - best_row['test accuracy']:+.1%} train gap",
)
col_b.metric("Mean train accuracy", f"{train_mean:.1%}")
col_c.metric("Mean test accuracy", f"{test_mean:.1%}")

losers = "`, `".join(name for name in comparison.index if name != best)
st.markdown(
    f"**Why it wins (on this split):** `{best}` reaches "
    f"{best_row['test accuracy']:.1%} on the 30% held-out set while `{losers}` "
    "score lower. The train/test gap shows how much each model memorized the "
    "training rows. On a dataset this small the gap between models is narrow, "
    "so treat the ranking as illustrative rather than definitive."
)

st.subheader("Inspecting errors")
st.markdown("Confusion matrix for the winning model on the held-out set:")
plot_confusion_matrix(results["fitted"][best], results["X_test"], results["y_test"], names)

st.subheader("Where the models look at the data")
plot_feature_pairs(results["X"], results["y"], names, results["fitted"]["decision_tree"])

st.subheader("Classify a flower")
st.caption("Enter the four measurements of a flower; the lab votes with the trained models.")
inputs = st.columns(4)
values = []
for i, feature in enumerate(FEATURE_NAMES):
    lo, hi = float(results["X"][feature].min()), float(results["X"][feature].max())
    values.append(
        inputs[i].number_input(
            feature, min_value=0.0, max_value=10.0, value=round((lo + hi) / 2, 1), step=0.1
        )
    )
if st.button("Classify", type="primary"):
    sample = pd.DataFrame([values], columns=FEATURE_NAMES)
    votes = {}
    for name, model in results["fitted"].items():
        pred = int(model.predict(sample)[0])
        proba = model.predict_proba(sample)[0]
        votes[name] = (names[pred], round(float(proba.max()), 3))
    vote_df = pd.DataFrame(
        [(n, species, proba) for n, (species, proba) in votes.items()],
        columns=["model", "prediction", "confidence"],
    )
    st.dataframe(vote_df, width="stretch")
    consensus = max(votes.values(), key=lambda item: item[1])[0]
    agree = sum(1 for _, (species, _) in votes.items() if species == consensus)
    st.metric("Consensus", f"Iris {consensus}", delta=f"{agree} of {len(votes)} models agree")

st.caption(
    "Built with native Streamlit. Source: Hands-On Machine Learning (3e), "
    f"chapter 6 — {SOURCE_URL} (Apache-2.0, © Aurélien Géron). "
    "This lab adapts its Iris example to a small comparison; no data left this machine."
)
