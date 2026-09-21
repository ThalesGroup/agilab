"""Iris decision lab, adapted from Aurélien Géron's handson-ml3 chapter 6.

Source: https://github.com/ageron/handson-ml3/blob/main/06_decision_trees.ipynb
Original source is Apache-2.0 licensed; see source/LICENSE.
Adaptation: four features, held-out evaluation, and two comparison models.
"""

import pandas as pd
from sklearn.datasets import load_iris
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier


def build_models(max_depth=3, seed=42):
    """Return fresh, unfitted estimators accepting all four Iris measurements."""
    return {
        "Decision tree": DecisionTreeClassifier(max_depth=max_depth, random_state=seed),
        "Random forest": RandomForestClassifier(
            n_estimators=200, max_depth=max_depth, random_state=seed, n_jobs=1
        ),
        "Logistic regression": make_pipeline(
            StandardScaler(), LogisticRegression(max_iter=2000, random_state=seed)
        ),
    }


def load_split(seed=42):
    """Reserve 30% of Iris with identical class proportions for every model."""
    iris = load_iris(as_frame=True)
    X_train, X_test, y_train, y_test = train_test_split(
        iris.data, iris.target, test_size=0.30, stratify=iris.target, random_state=seed
    )
    return iris, X_train, X_test, y_train, y_test


def train_models(X_train, y_train, max_depth=3, seed=42):
    """Fit only on training rows, including the logistic scaling pipeline."""
    models = build_models(max_depth=max_depth, seed=seed)
    for model in models.values():
        model.fit(X_train, y_train)
    return models


def evaluate_models(models, X_train, X_test, y_train, y_test):
    """Return comparable train/test scores and held-out predictions."""
    records, predictions = [], {}
    for name, model in models.items():
        predicted = model.predict(X_test)
        predictions[name] = predicted
        records.append({
            "model": name,
            "train_accuracy": float(accuracy_score(y_train, model.predict(X_train))),
            "test_accuracy": float(accuracy_score(y_test, predicted)),
            "test_errors": int((predicted != y_test.to_numpy()).sum()),
        })
    return pd.DataFrame(records), predictions
