"""Spawn helpers must prefer this checkout over an installed-package shadow."""

from pathlib import Path
import subprocess
import sys


def test_spawn_worker_repairs_polluted_source_precedence(tmp_path):
    root = Path(__file__).resolve().parents[1]
    foreign = tmp_path / "foreign"
    (foreign / "agilab").mkdir(parents=True)
    (foreign / "agilab" / "__init__.py").write_text("# incomplete foreign install\n")
    script = f"""import sys
sys.path.insert(0, {str(root / 'test')!r})
from _agent_run_process_support import agent_run_process
source = {str(root / 'src')!r}
sys.path[:] = [{str(foreign)!r}, *[p for p in sys.path if p != source], source]
class Start:
    def wait(self, timeout): return True
class Results:
    def put(self, value):
        assert value[0] == 'ok', value
        assert value[1] == 0, value
agent_run_process({str(tmp_path / 'run')!r}, Start(), Results())
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True,
                            text=True, timeout=20)
    assert result.returncode == 0, result.stderr
