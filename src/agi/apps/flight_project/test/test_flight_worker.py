import pytest
from agi_apps.flight_project.src.flight_worker import FlightWorker

@pytest.fixture
def worker():
    return FlightWorker()

def test_flight_worker_starts_idle(worker):
    assert worker.state == "idle"

def test_flight_worker_can_start_task(worker):
    task = {"type": "test_task", "payload": 42}
    worker.assign_task(task)
    assert worker.state == "busy"
    assert worker.current_task == task

def test_flight_worker_completes_task(worker):
    task = {"type": "test_task", "payload": 100}
    worker.assign_task(task)
    worker.run_current_task()
    assert worker.state == "idle"
    assert worker.result == 200  # Remplace 200 par le résultat attendu selon ta logique
