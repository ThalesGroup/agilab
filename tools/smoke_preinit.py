#!/usr/bin/env python3
"""
Minimal pre-init smoke checks for AgiEnv static/class helpers.

Safe to run without initialising AgiEnv(); only touches a temp directory.
Prints "OK" on success, or "SKIP:" if dependencies to import agi_env are missing.
"""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_SRC = ROOT / "src/agilab/core/agi-env/src"
sys.path.insert(0, str(ENV_SRC))

try:
    from agi_env.agi_env import AgiEnv
except Exception as e:  # pragma: no cover - dependency-light guard
    print(f"SKIP: cannot import agi_env (missing deps?): {e}")
    sys.exit(0)

# Ensure clean singleton
AgiEnv.reset()

tmp = Path(tempfile.mkdtemp(prefix="agi-preinit-"))
try:
    # Point resources_path to temp and clear envars for a self-contained check
    AgiEnv.resources_path = tmp
    AgiEnv.envars = {}

    # set_env_var should not require an instance and should persist to .env
    AgiEnv.set_env_var("AGI_TEST_VAR", "1")
    assert AgiEnv.envars.get("AGI_TEST_VAR") == "1"
    assert (tmp / ".env").exists(), "expected .env to be created in temp resources_path"

    # read_agilab_path exists and should not crash without initialisation
    _ = AgiEnv.read_agilab_path()

    # _build_env available pre-init
    env = AgiEnv._build_env(venv=None)
    assert isinstance(env, dict)

    # log_info should not fail pre-init (falls back to print)
    AgiEnv.log_info("preinit smoke: hello")

    # On Windows, exercise junction/symlink helpers (no-op without admin)
    if sys.platform.startswith("win"):
        src = tmp / "srcdir"; dst = tmp / "dstlink"
        src.mkdir(exist_ok=True)
        try:
            AgiEnv.create_junction_windows(src, dst)
            AgiEnv.create_symlink_windows(src, dst)
        except Exception as e:
            print(f"SKIP: windows link helpers raised: {e}")

    print("OK")
finally:
    # leave temp dir on disk for inspection; remove if you prefer cleanup
    pass
