"""Interactive, local Iris decision lab. Run with: streamlit run app.py."""

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from sklearn.metrics import ConfusionMatrixDisplay

from models import evaluate_models, load_split, train_models


st.set_page_config(page_title="Iris decision lab", page_icon=":material/local_florist:", layout="wide")
st.title("Iris decision lab")
st.caption("150 flowers · 4 measurements · 3 models | An experiment in making and checking decisions")

# Keep depth as the first interactive control.
max_depth = st.slider("Maximum tree depth", min_value=1, max_value=10, value=3,
                      help="Applies to the decision tree and each tree in the random forest. Logistic regression stays fixed.")


@st.cache_data(max_entries=10, show_spinner="Training and comparing models…")
def run_experiment(depth, seed=42):
    iris, X_train, X_test, y_train, y_test = load_split(seed)
    models = train_models(X_train, y_train, max_depth=depth, seed=seed)
    scores, predictions = evaluate_models(models, X_train, X_test, y_train, y_test)
    return iris, X_train, X_test, y_train, y_test, models, scores, predictions


iris, X_train, X_test, y_train, y_test, models, scores, predictions = run_experiment(max_depth)
best = scores.test_accuracy.max()
winners = scores.loc[scores.test_accuracy == best, "model"].tolist()
best_errors = int(scores.test_errors.min())

with st.container(horizontal=True):
    st.metric("Best held-out accuracy", f"{best:.1%}", border=True)
    st.metric("Best model errors", f"{best_errors} / {len(y_test)}", border=True)
    st.metric("Training / test flowers", f"{len(y_train)} / {len(y_test)}", border=True)

st.subheader("01 · Compare the models")
st.success(("Joint leaders: " if len(winners) > 1 else "Split winner: ") + " · ".join(winners))
st.write(f"Ranked by held-out accuracy: the leader{'s' if len(winners) > 1 else ''} correctly "
         f"classif{'y' if len(winners) > 1 else 'ies'} {len(y_test) - best_errors} of {len(y_test)} test flowers. "
         f"One flower changes this score by {100 / len(y_test):.2f} percentage points.")
st.dataframe(scores, hide_index=True, width="stretch", column_config={
    "model": "Model",
    "train_accuracy": st.column_config.NumberColumn("Train accuracy", format="percent"),
    "test_accuracy": st.column_config.NumberColumn("Test accuracy", format="percent"),
    "test_errors": "Test errors",
})
st.caption("Same stratified 70/30 split for all models; seed 42. All four features are used. "
           "Scaling is learned inside the logistic regression pipeline using training rows only.")
with st.expander("Why do their results differ?", expanded=True):
    st.write("The decision tree uses a small sequence of threshold rules. Increasing depth can fit finer "
             "patterns, including noise. The random forest averages 200 trees trained on bootstrap samples "
             "with feature subsampling. Logistic regression uses scaled measurements and linear class scores. "
             "A high training score with a lower test score suggests overfitting; it does not prove its cause.")
    st.info("This ranking describes only this split of the small Iris dataset. Ties stay ties. "
            "Trying depths after inspecting test results makes this an exploratory comparison. "
            "Use training-only cross-validation and a new untouched test set before making broader claims.")

st.subheader("02 · Inspect the decisions")
selected = st.selectbox("Model to inspect and classify with", list(models))
predicted = predictions[selected]
wrong = predicted != y_test.to_numpy()
left, right = st.columns(2)
with left:
    with st.container(border=True):
        st.markdown("**Confusion matrix · held-out flowers**")
        fig, ax = plt.subplots(figsize=(5.5, 4))
        ConfusionMatrixDisplay.from_predictions(
            y_test, predicted, labels=[0, 1, 2], display_labels=iris.target_names,
            cmap="Blues", colorbar=False, ax=ax,
        )
        ax.set_xlabel("Predicted species")
        ax.set_ylabel("Actual species")
        fig.tight_layout()
        st.pyplot(fig, width="stretch")
        plt.close(fig)
with right:
    with st.container(border=True):
        st.markdown("**Petal measurements · held-out flowers**")
        fig, ax = plt.subplots(figsize=(5.5, 4))
        for species, color, marker in zip(range(3), ["#247b7b", "#5966ba", "#d08725"], ["o", "s", "^"]):
            mask = y_test.to_numpy() == species
            ax.scatter(X_test.iloc[mask, 2], X_test.iloc[mask, 3], label=iris.target_names[species],
                       c=color, marker=marker, alpha=0.8)
        if wrong.any():
            ax.scatter(X_test.iloc[wrong, 2], X_test.iloc[wrong, 3], s=180, facecolors="none",
                       edgecolors="#b42318", linewidths=1.6, label="Misclassified")
        ax.set_xlabel("Petal length (cm)")
        ax.set_ylabel("Petal width (cm)")
        ax.legend(fontsize=8)
        fig.tight_layout()
        st.pyplot(fig, width="stretch")
        plt.close(fig)
st.caption("Colors and shapes indicate actual species; red rings mark errors. This two-feature view "
           "does not show the full four-feature decision boundary.")
errors = X_test.loc[wrong].copy()
errors.insert(0, "sample_id", errors.index)
errors["actual"] = iris.target_names[y_test.to_numpy()[wrong]]
errors["predicted"] = iris.target_names[predicted[wrong]]
st.markdown(f"**{selected}: {int(wrong.sum())} errors on held-out flowers**")
if errors.empty:
    st.success("No errors on this split. That does not establish perfect performance on new flowers.")
st.dataframe(errors, hide_index=True, width="stretch")

st.subheader("03 · Classify a flower")
st.write(f"Enter measurements in centimetres. Predictions use **{selected}**, fitted on the training split.")
with st.container(border=True):
    cols = st.columns(4)
    measurements = []
    for col, label, default in zip(cols, iris.feature_names, [5.1, 3.5, 1.4, 0.2]):
        with col:
            measurements.append(st.number_input(label.capitalize(), min_value=0.1, max_value=20.0,
                                                value=default, step=0.1))
    flower = pd.DataFrame([measurements], columns=iris.feature_names)
    model = models[selected]
    probabilities = model.predict_proba(flower)[0]
    species = int(model.predict(flower)[0])
    st.metric("Predicted species", str(iris.target_names[species]))
    st.dataframe(pd.DataFrame({"species": iris.target_names[model.classes_],
                               "model probability": probabilities}),
                 hide_index=True, width="stretch", column_config={
                     "model probability": st.column_config.NumberColumn(format="percent")})
    outside = (flower.iloc[0] < X_train.min()) | (flower.iloc[0] > X_train.max())
    if outside.any():
        st.warning("Outside the observed training range: " + ", ".join(X_train.columns[outside]) +
                   ". This prediction is an extrapolation.")
    st.caption("Probabilities are model estimates, not validated confidence or a botanical identification guarantee.")

st.divider()
st.caption("Adapted from Aurélien Géron’s handson-ml3, chapter 6, Iris decision-tree example. "
           "Changes: four features, held-out comparison, error inspection and interactive prediction. "
           "Apache-2.0; original notebook, provenance and license retained in source/.")
st.markdown("[Source notebook](https://github.com/ageron/handson-ml3/blob/"
            "e707c2d659abafb9b1f9fd927907619a128db8d7/06_decision_trees.ipynb)")
