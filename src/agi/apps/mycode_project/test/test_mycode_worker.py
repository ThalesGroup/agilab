import pytest
from mycode.worker import MyCodeWorker

@pytest.fixture
def worker():
    return MyCodeWorker()

def test_mycode_worker_default_state(worker):
    assert worker.status == "ready"

def test_mycode_worker_compute(worker):
    result = worker.compute(3, 7)
    assert result == 10  # Change le résultat selon ta logique réelle

def test_mycode_worker_raises_on_invalid_input(worker):
    with pytest.raises(ValueError):
        worker.compute(None, 5)
