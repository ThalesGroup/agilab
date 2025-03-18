import os
import subprocess
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest
from agi_core.workers.agi_worker import AgiWorker
from agi_env import AgiEnv


# DummyWorker can be defined if needed for instance methods test.
class DummyWorker(AgiWorker):
    def works(self, workers_tree, workers_tree_info):
        # Minimal dummy implementation for testing purposes.
        pass


# def test_normalize_path():
#     # Test that normalize_path returns an absolute, resolved path.
#     test_path = ""
#     normalized = AgiEnv.normalize_path(test_path)
#     assert os.path.isabs(normalized), "normalize_path should return an absolute path."
#     expected = str(Path(test_path).resolve())
#     assert normalized == expected, f"Expected {expected} but got {normalized}"

def test_expand():
    # Test expansion of a path starting with '~'
    expanded = AgiWorker.expand("~")
    expected = str(Path("~").expanduser().resolve())
    assert expanded == expected, f"Expected {expected} but got {expanded}"

    # Test expansion of a relative path with a provided base directory.
    base_dir = tempfile.gettempdir()
    rel_path = "subdir"
    expanded = AgiWorker.expand(rel_path, base_directory=base_dir)
    expected = str((Path(base_dir) / rel_path).resolve())
    assert expanded == expected, f"Expected {expected} but got {expanded}"


def test_join():
    # Test joining of two paths using the join method.
    path1 = "~"
    path2 = "subdir"
    joined = AgiWorker.join(path1, path2)
    expected = os.path.join(Path("~").expanduser().resolve(), "subdir")
    if os.name != "nt":
        expected = expected.replace("\\", "/")
    assert joined == expected, f"Expected {expected} but got {joined}"


def test_expand_and_join():
    # Test expand_and_join.
    path1 = "~/data"
    path2 = "file.txt"
    joined = AgiWorker.expand_and_join(path1, path2)
    expected = os.path.join(AgiWorker.expand(path1), path2)
    if os.name != "nt":
        expected = expected.replace("\\", "/")
    assert joined == expected, f"Expected {expected} but got {joined}"


def test_get_stdout():
    # Test the _get_stdout method by capturing printed output and the return value.
    def sample_func(x):
        print("Hello from sample_func!")
        return x + 1

    captured_output, result = AgiWorker._get_stdout(sample_func, 5)
    assert captured_output.strip() == "Hello from sample_func!", (
            "Expected output 'Hello from sample_func!' but got " + captured_output
    )
    assert result == 6, f"Expected return value 6 but got {result}"


def test_exec_success():
    # Test the exec method with a simple command.
    cmd = "echo Hello"
    current_dir = os.getcwd()
    result = AgiWorker.exec(cmd, current_dir, worker="test_worker")
    assert result.returncode == 0, f"Command '{cmd}' did not return 0"
    # The stdout may include a newline; check for substring.
    assert "Hello" in result.stdout, f"Expected 'Hello' in output but got: {result.stdout}"