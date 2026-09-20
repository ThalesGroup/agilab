import streamlit as st
from models import evaluate_models
import numpy as np
from sklearn.metrics import confusion_matrix
import matplotlib.pyplot as plt
from sklearn.datasets import load_iris


@st.cache_resource
def cached_evaluation(depth):
    return evaluate_models(max_depth=depth, seed=42)


st.title("Iris decision lab")

depth = st.slider("Tree depth", 1, 8, 3)
result = cached_evaluation(depth)

st.dataframe(result["metrics"], width="stretch")

max_accuracy = max([m["accuracy"] for m in result["metrics"]])
st.metric("Max Accuracy", f"{max_accuracy:.2%}")

# Find all models tied for highest accuracy
models_with_max_acc = [
    m for m in result["metrics"] if abs(m["accuracy"] - max_accuracy) < 1e-6
]
tied_models_names = ", ".join([m["model"] for m in models_with_max_acc])
st.caption(
    f"Tied for Max Accuracy: {tied_models_names}. Tree depth controls complexity and the comparison applies only to this split."
)

selected_name = st.selectbox("Classifier", list(result["models"]))

st.caption("Held-out evaluation on a small educational dataset")
st.markdown(
    "[Source](https://github.com/ageron/handson-ml3/blob/e707c2d659abafb9b1f9fd927907619a128db8d7/06_decision_trees.ipynb)"
)
st.markdown("Apache-2.0 License")

st.caption(
    "Changing tree depth reuses the same held-out split. Treat these comparisons as exploratory; final performance needs a separate untouched test set."
)


# Get the selected model
selected_model = result["models"][selected_name]

# Compute predictions on test data
y_pred = selected_model.predict(result["X_test"])

# Create confusion matrix plot
fig, ax = plt.subplots()
cm = confusion_matrix(y_true=result["y_test"], y_pred=y_pred)
ax.imshow(cm, interpolation="nearest", cmap=plt.cm.Blues)
ax.set_xlabel("Predicted")
ax.set_ylabel("True")
ax.set_title(f"Confusion Matrix for {selected_name}")

# Add tick labels
tick_marks = ["setosa", "versicolor", "virginica"]
ax.set_xticks(np.arange(len(tick_marks)))
ax.set_yticks(np.arange(len(tick_marks)))
ax.set_xticklabels(tick_marks, rotation=45, ha="right")
ax.set_yticklabels(tick_marks)

# Add value labels to the matrix - FIXED: use cm[j, i] for [row, column] indexing
for j in range(cm.shape[0]):
    for i in range(cm.shape[1]):
        ax.text(
            i,
            j,
            cm[j, i],
            ha="center",
            va="center",
            color="white" if cm[j, i] > 5 else "black",
        )

# Render and close
st.pyplot(fig)
plt.close(fig)

# Create scatter plot for petal features
fig2, ax2 = plt.subplots()
ax2.scatter(result["X"][:, 2], result["X"][:, 3], c=result["y"], cmap=plt.cm.Blues)
ax2.set_xlabel("Petal Length (cm)")
ax2.set_ylabel("Petal Width (cm)")
ax2.set_title("Iris petal measurements")

# Add caption explaining colors represent actual species, not predictions
ax2.text(
    0.1,
    0.95,
    "Colors show actual species (y_true), not predictions",
    transform=ax2.transAxes,
    fontsize=10,
    verticalalignment="bottom",
    horizontalalignment="left",
    bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5),
)

# Render and close
st.pyplot(fig2)
plt.close(fig2)


# Get input values
sepal_length = st.number_input(
    "Sepal Length (cm)", min_value=1.0, max_value=10.0, step=0.1, value=5.1
)
sepal_width = st.number_input(
    "Sepal Width (cm)", min_value=0.1, max_value=6.0, step=0.1, value=3.5
)
petal_length = st.number_input(
    "Petal Length (cm)", min_value=0.1, max_value=10.0, step=0.1, value=1.4
)
petal_width = st.number_input(
    "Petal Width (cm)", min_value=0.1, max_value=4.0, step=0.1, value=0.2
)

# Create button
if st.button("Predict"):
    # Load iris dataset to get target names
    iris = load_iris()

    # Get the selected model
    selected_model = result["models"][selected_name]

    # Prepare input array in the correct order: sepal length, sepal width, petal length, petal width
    input_array = np.array([[sepal_length, sepal_width, petal_length, petal_width]])

    # Make prediction
    predicted_class = selected_model.predict(input_array)[0]

    # Get species name from target names
    species_name = iris.target_names[predicted_class]

    # Display result
    st.success("Predicted species: " + str(species_name))
