"""Model factory for the Iris decision lab.

Adapted from the Iris decision-tree example in chapter 6 of Aurélien Géron's
"Hands-On Machine Learning with Scikit-Learn, Keras & TensorFlow" (3rd ed.),
Apache-2.0 licensed. See source/original.ipynb for the upstream notebook.
"""
from __future__ import annotations

from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier


def build_models(max_depth: int = 3, seed: int = 42) -> dict:
    """Return a dict of unfitted estimators for the Iris task.

    All models accept the full four-feature Iris matrix
    (sepal length, sepal width, petal length, petal width). ``max_depth``
    regularizes the tree-based models; the logistic regression ignores it.
    """
    return {
        "decision_tree": DecisionTreeClassifier(
            max_depth=max_depth, random_state=seed
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=200,
            max_depth=max_depth,
            random_state=seed,
            n_jobs=2,
        ),
        "logistic_regression": LogisticRegression(
            max_iter=200, random_state=seed
        ),
    }


FEATURE_NAMES = [
    "sepal length (cm)",
    "sepal width (cm)",
    "petal length (cm)",
    "petal width (cm)",
]


def load_data():
    """Load the Iris dataset as a pandas frame with named feature columns."""
    import pandas as pd
    from sklearn.datasets import load_iris

    iris = load_iris(as_frame=True)
    frame = iris.frame
    X = frame[FEATURE_NAMES]
    y = frame["target"]
    return X, y, iris.target_names
