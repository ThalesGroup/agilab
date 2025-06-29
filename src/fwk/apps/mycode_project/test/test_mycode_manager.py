import pytest
from mycode.manager import MyCodeManager

@pytest.fixture
def manager():
    return MyCodeManager()

def test_mycode_manager_init(manager):
    assert manager is not None

def test_mycode_manager_job_handling(manager):
    job = {"data": 123}
    manager.submit(job)
    manager.process_next()
    assert manager.last_result == 246  # Exemple : adapte selon logique réelle

def test_mycode_manager_reset(manager):
    job = {"data": 555}
    manager.submit(job)
    manager.reset()
    assert manager.last_result is None
    assert len(manager.queue) == 0
