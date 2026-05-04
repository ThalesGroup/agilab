from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
package_root = str(SRC_ROOT / "agilab")
pkg = sys.modules.get("agilab")
if pkg is not None and hasattr(pkg, "__path__"):
    package_path = list(pkg.__path__)
    if package_root not in package_path:
        pkg.__path__ = [package_root, *package_path]
importlib.invalidate_caches()

tracking = importlib.import_module("agilab.tracking")


class FakeMlflow:
    def __init__(self) -> None:
        self.tracking_uri = None
        self.active = None
        self.params = []
        self.metrics = []
        self.tags = []
        self.artifacts = []
        self.texts = []
        self.ended = False

    def set_tracking_uri(self, value):
        self.tracking_uri = value

    def active_run(self):
        return self.active

    def start_run(self, *, run_id):
        self.active = SimpleNamespace(info=SimpleNamespace(run_id=run_id))
        return self.active

    def end_run(self):
        self.ended = True
        self.active = None

    def log_param(self, key, value):
        self.params.append((key, value))

    def log_params(self, params):
        self.params.append(params)

    def log_metric(self, key, value, **kwargs):
        self.metrics.append((key, value, kwargs))

    def log_metrics(self, metrics, **kwargs):
        self.metrics.append((metrics, kwargs))

    def set_tag(self, key, value):
        self.tags.append((key, value))

    def set_tags(self, tags):
        self.tags.append(tags)

    def log_artifact(self, artifact, **kwargs):
        self.artifacts.append((artifact, kwargs))

    def log_text(self, text, artifact_file):
        self.texts.append((text, artifact_file))


def test_tracker_logs_to_mlflow_from_environment(monkeypatch, tmp_path):
    fake_mlflow = FakeMlflow()
    monkeypatch.setattr(tracking.importlib, "import_module", lambda name: fake_mlflow if name == "mlflow" else None)
    monkeypatch.setenv(tracking.MLFLOW_TRACKING_URI_ENV, "sqlite:///tmp/mlflow.db")
    monkeypatch.setenv(tracking.MLFLOW_RUN_ID_ENV, "run-123")
    artifact = tmp_path / "plot.png"
    artifact.write_text("image", encoding="utf-8")

    tracker = tracking.Tracker()

    assert tracker.backend == "mlflow"
    assert tracker.active_run_id is None
    assert tracker.log_param("model", "demo") is True
    assert tracker.active_run_id == "run-123"
    assert tracker.log_params({"batch": 32}) is True
    assert tracker.log_metric("accuracy", 0.94, step=2) is True
    assert tracker.log_metrics({"loss": 0.1}, step=2) is True
    assert tracker.set_tag("status", "ok") is True
    assert tracker.set_tags({"phase": "test"}) is True
    assert tracker.log_text("hello", "logs/stdout.txt") is True
    assert tracker.log_artifact(artifact, artifact_path="plots") is True
    tracker._end_started_run()

    assert fake_mlflow.tracking_uri == "sqlite:///tmp/mlflow.db"
    assert fake_mlflow.params == [("model", "demo"), {"batch": 32}]
    assert fake_mlflow.metrics == [
        ("accuracy", 0.94, {"step": 2}),
        ({"loss": 0.1}, {"step": 2}),
    ]
    assert fake_mlflow.tags == [("status", "ok"), {"phase": "test"}]
    assert fake_mlflow.texts == [("hello", "logs/stdout.txt")]
    assert fake_mlflow.artifacts == [(str(artifact), {"artifact_path": "plots"})]
    assert fake_mlflow.ended is True


def test_tracker_noops_when_mlflow_is_unavailable(monkeypatch, tmp_path):
    def fail_import(name):
        if name == "mlflow":
            raise ImportError("missing mlflow")
        raise AssertionError(name)

    monkeypatch.setattr(tracking.importlib, "import_module", fail_import)
    tracker = tracking.Tracker()

    assert tracker.backend == "none"
    assert tracker.available is False
    assert tracker.configure(tracking_uri="sqlite:///tmp/mlflow.db") is False
    assert tracker.log_param("model", "demo") is False
    assert tracker.log_params({"batch": 32}) is False
    assert tracker.log_metric("accuracy", 0.94) is False
    assert tracker.log_metrics({"loss": 0.1}) is False
    assert tracker.set_tag("status", "ok") is False
    assert tracker.set_tags({"phase": "test"}) is False
    assert tracker.log_text("hello", "logs/stdout.txt") is False
    assert tracker.log_artifact(tmp_path / "missing.txt") is False


def test_tracker_reuses_active_run_and_skips_missing_artifact(monkeypatch, tmp_path):
    fake_mlflow = FakeMlflow()
    fake_mlflow.active = SimpleNamespace(info=SimpleNamespace(run_id="existing-run"))
    monkeypatch.setattr(tracking.importlib, "import_module", lambda name: fake_mlflow if name == "mlflow" else None)

    tracker = tracking.Tracker()

    assert tracker.configure(run_id="ignored-run") is True
    assert tracker.active_run_id == "existing-run"
    assert tracker.log_artifact(Path(tmp_path / "missing.txt")) is False
    assert fake_mlflow.artifacts == []
