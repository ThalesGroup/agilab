"""AGILAB Iris Decision Lab – model factory.

Adapted from Aurélien Géron, *Hands-On Machine Learning with Scikit-Learn,
Keras & TensorFlow*, 3rd ed., Chapter 6.
License: Apache-2.0
Source: https://github.com/ageron/handson-ml3
"""

from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression


def build_models(max_depth: int = 3, seed: int = 42) -> dict:
    """Return a dict of unfitted sklearn estimators keyed by display name.

    All models accept the full four-feature Iris matrix
    (sepal length, sepal width, petal length, petal width).
    """
    return {
        "Decision Tree": DecisionTreeClassifier(
            max_depth=max_depth, random_state=seed
        ),
        "Random Forest": RandomForestClassifier(
            max_depth=max_depth, n_estimators=100, random_state=seed
        ),
        "Logistic Regression": LogisticRegression(
            max_iter=2000, random_state=seed
        ),
    }
