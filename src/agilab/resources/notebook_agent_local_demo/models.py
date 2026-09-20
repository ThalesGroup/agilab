from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score


def build_models(max_depth=3, seed=42):
    return {
        "decision_tree": DecisionTreeClassifier(max_depth=max_depth, random_state=seed),
        "random_forest": RandomForestClassifier(
            n_estimators=100, max_depth=max_depth, random_state=seed
        ),
        "logistic_regression": LogisticRegression(random_state=seed, max_iter=1000),
    }


def evaluate_models(max_depth=3, seed=42):
    # Load iris dataset with numpy arrays and all four features
    X, y = load_iris(return_X_y=True)

    # Stratified train_test_split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, random_state=seed, stratify=y
    )

    # Build models
    models = build_models(max_depth=max_depth, seed=seed)

    # Fit models on training data only
    for name, model in models.items():
        model.fit(X_train, y_train)

    # Evaluate test accuracy
    metrics = []
    for name, model in models.items():
        accuracy = accuracy_score(y_test, model.predict(X_test))
        metrics.append({"model": name, "accuracy": float(accuracy)})

    return {
        "models": models,
        "metrics": metrics,
        "X_test": X_test,
        "y_test": y_test,
        "X": X,
        "y": y,
    }
