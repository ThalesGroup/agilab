import pytest
from flight import FlightManager

@pytest.fixture
def manager():
    return FlightManager()

def test_flight_manager_registers_workers(manager):
    manager.add_worker("w1")
    manager.add_worker("w2")
    assert len(manager.workers) == 2

def test_flight_manager_assigns_task(manager):
    manager.add_worker("w1")
    task = {"type": "process", "payload": 55}
    manager.assign_task("w1", task)
    worker = manager.get_worker("w1")
    assert worker.current_task == task

def test_flight_manager_gathers_results(manager):
    manager.add_worker("w1")
    manager.assign_task("w1", {"type": "add", "payload": 1})
    manager.run_all()
    results = manager.get_results()
    assert "w1" in results
    assert results["w1"] is not None
