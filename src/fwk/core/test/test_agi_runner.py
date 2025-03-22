import os
import socket
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest
from agi_core.managers.agi_runner import AGI
from agi_env import AgiEnv

# Set AGI verbosity low to avoid extra prints during test.
AGI._verbose = 0


def test_normalize_path():
    # Given a relative path "."
    input_path = ""
    normalized = AgiEnv.normalize_path(input_path)
    if os.name == "nt":
        assert os.path.isabs(normalized), "On Windows the normalized path should be absolute."
    else:
        # On POSIX, compare with the PurePosixPath version.
        expected = str(PurePosixPath(Path(input_path)))
        assert normalized == expected, f"Expected {expected} but got {normalized}"


def test_find_free_port():
    # Verify that find_free_port returns an integer that can be bound.
    port = AGI.find_free_port(start=5000, end=6000, attempts=10)
    assert isinstance(port, int), "find_free_port should return an integer."
    # Attempt to bind a socket to the port to ensure it is free.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("localhost", port))
        except Exception as e:
            pytest.fail(f"find_free_port returned a port that is not free: {e}")


def test_get_default_local_ip():
    # Check that get_default_local_ip returns a plausible IPv4 address.
    ip = AGI.get_default_local_ip()
    assert ip != "Unable to determine local IP", "Local IP could not be determined."
    parts = ip.split('.')
    assert len(parts) == 4, f"IP address {ip} does not have 4 parts."
    for part in parts:
        assert part.isdigit(), f"IP part '{part}' is not numeric."


def test_is_local():
    # Test that known local IP addresses are detected as local.
    assert AGI._is_local("127.0.0.1"), "127.0.0.1 should be local."
    # Use a public IP that is likely not local.
    assert not AGI._is_local("8.8.8.8"), "8.8.8.8 should not be considered local."


def test_load_module():
    # Test the _load_module static method by loading a standard module.
    # Here we load the built-in math module.
    module = AGI._load_module("math", package=None, path="")
    import math
    assert module == math, "Loaded module does not match the built-in math module."