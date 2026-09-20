"""AGILAB – Iris Decision Lab (Streamlit UI).

Adapted from Aurélien Géron, *Hands-On Machine Learning with Scikit-Learn,
Keras & TensorFlow*, 3rd ed., Chapter 6.
License: Apache-2.0  Source: https://github.com/ageron/handson-ml3
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st

from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split
from sklearn.metrics import confusion_matrix, accuracy_score

import models as m

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="AGILAB Iris Decision Lab", layout="wide")
st.title("AGILAB – Iris Decision Lab")
st.caption(
    "Adapted from Aurélien Géron, *Hands-On Machine Learning with Scikit-Learn, "
    "Keras & TensorFlow*, 3rd ed., Ch. 6.  "
    "Source: https://github.com/ageron/handson-ml3 (Apache-2.0)"
)

# ── Controls (slider first) ──────────────────────────────────────────────────
max_depth = st.slider("Max Tree Depth", min_value=1, max_value=10, value=3, step=1)

# ── Cached training / evaluation ─────────────────────────────────────────────
@st.cache_data(show_spinner="Training models…")
def _train(max_depth: int, seed: int = 42):
    iris = load_iris(as_frame=True)
    X = iris.data
    y = iris.target
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, stratify=y, random_state=seed
    )
    model_dict = m.build_models(max_depth=max_depth, seed=seed)
    results = {}
    for name, clf in model_dict.items():
        clf.fit(X_train, y_train)
        y_pred = clf.predict(X_test)
        results[name] = {
            "model": clf,
            "y_pred": y_pred,
            "train_acc": float(accuracy_score(y_train, clf.predict(X_train))),
            "test_acc": float(accuracy_score(y_test, y_pred)),
            "cm": confusion_matrix(y_test, y_pred),
        }
    return results, X_train, X_test, y_train, y_test, iris

results, X_train, X_test, y_train, y_test, iris = _train(max_depth)

# ── Classifier selector ──────────────────────────────────────────────────────
selected = st.selectbox("Classifier", list(results.keys()))

# ── Comparison table ─────────────────────────────────────────────────────────
rows = []
for name, r in results.items():
    rows.append({"Model": name, "Train Acc": r["train_acc"], "Test Acc": r["test_acc"]})
df = pd.DataFrame(rows)
st.dataframe(df, width="stretch")

# ── Winner identification (all tied for highest held-out accuracy) ──────────
best_acc = df["Test Acc"].max()
winners = df[df["Test Acc"] == best_acc]["Model"].tolist()
n_test = len(X_test)
if len(winners) == 1:
    st.info(
        f"🏆 **{winners[0]}** achieves the highest held-out accuracy "
        f"({best_acc:.4f}) on this split of {n_test} test samples. "
        "This is an exploratory result — final performance requires a separate, untouched test set."
    )
else:
    names_str = ", ".join(winners)
    st.info(
        f"🏆 **{names_str}** are tied for the highest held-out accuracy "
        f"({best_acc:.4f}) on this split of {n_test} test samples. "
        "This is an exploratory result — final performance requires a separate, untouched test set."
    )

# ── Headline metric ──────────────────────────────────────────────────────────
st.metric("Test Accuracy", f"{results[selected]['test_acc']:.4f}")

# ── Confusion matrix ─────────────────────────────────────────────────────────
cm = results[selected]["cm"]
fig, ax = plt.subplots(figsize=(6, 5))
ax.imshow(cm, interpolation="nearest", cmap=plt.cm.Blues)
ax.set_xlabel("Predicted")
ax.set_ylabel("True")
ax.set_title(f"Confusion Matrix – {selected}")
ticks = np.arange(len(iris.target_names))
ax.set_xticks(ticks)
ax.set_yticks(ticks)
ax.set_xticklabels(iris.target_names)
ax.set_yticklabels(iris.target_names)
for i in range(cm.shape[0]):
    for j in range(cm.shape[1]):
        color = "white" if cm[i, j] > cm.max() / 2 else "black"
        ax.text(j, i, str(cm[i, j]), ha="center", va="center", color=color)
plt.tight_layout()
st.pyplot(fig, width="stretch")
plt.close(fig)

# ── Feature scatter (actual species) ─────────────────────────────────────────
fig, ax = plt.subplots(figsize=(7, 5))
Xt = X_test.to_numpy()
yt = y_test.to_numpy()
for idx, name in enumerate(iris.target_names):
    mask = yt == idx
    ax.scatter(Xt[mask, 2], Xt[mask, 3], label=f"Iris {name}", alpha=0.75, s=30)
ax.set_xlabel("Petal Length (cm)")
ax.set_ylabel("Petal Width (cm)")
ax.set_title("Test Set – Actual Species")
ax.legend()
plt.tight_layout()
st.pyplot(fig, width="stretch")
plt.close(fig)

# ── Prediction inputs ────────────────────────────────────────────────────────
st.subheader("Classify a Flower")
c1, c2, c3, c4 = st.columns(4)
sl = c1.number_input("Sepal Length (cm)", min_value=0.1, max_value=10.0, value=5.1, step=0.1)
sw = c2.number_input("Sepal Width (cm)", min_value=0.1, max_value=10.0, value=3.5, step=0.1)
pl = c3.number_input("Petal Length (cm)", min_value=0.1, max_value=10.0, value=1.4, step=0.1)
pw = c4.number_input("Petal Width (cm)", min_value=0.1, max_value=10.0, value=0.2, step=0.1)

if st.button("Predict"):
    X_new = pd.DataFrame([[sl, sw, pl, pw]], columns=X_train.columns)
    pred = results[selected]["model"].predict(X_new)
    proba = results[selected]["model"].predict_proba(X_new)
    st.success(
        f"**{selected}** predicts: *Iris {iris.target_names[pred[0]]}* "
        f"(model probability {proba[0].max():.2%})"
    )
    st.caption(
        "⚠️ Model probabilities are uncalibrated estimates. "
        "They are not a guarantee of correctness and do not constitute botanical identification advice."
    )

# ── Caveat ───────────────────────────────────────────────────────────────────
st.warning(
    "⚠️ Tuning on the displayed holdout makes results **exploratory**. "
    "Final performance requires a separate, untouched test set."
)
