from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "performance_cache.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "performance_cache_test_module", MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_cached_file_sha256_reuses_signature_and_invalidates_on_change(
    tmp_path: Path,
) -> None:
    module = _load_module()
    cache_path = tmp_path / "cache.json"
    payload = tmp_path / "payload.txt"
    payload.write_text("alpha", encoding="utf-8")

    first = module.cached_file_sha256(payload, cache_path=cache_path)
    second = module.cached_file_sha256(payload, cache_path=cache_path)

    assert first == second
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert len(cache["entries"]) == 1

    payload.write_text("beta", encoding="utf-8")
    changed = module.cached_file_sha256(payload, cache_path=cache_path)

    assert changed != first


def test_manifest_digest_is_order_stable_and_records_missing_files(
    tmp_path: Path,
) -> None:
    module = _load_module()
    left = tmp_path / "left.txt"
    right = tmp_path / "right.txt"
    missing = tmp_path / "missing.txt"
    left.write_text("left", encoding="utf-8")
    right.write_text("right", encoding="utf-8")

    first = module.manifest_digest(
        [right, missing, left], cache_path=tmp_path / "cache.json"
    )
    second = module.manifest_digest(
        [left, right, missing], cache_path=tmp_path / "cache.json"
    )

    assert first["digest"] == second["digest"]
    states = {
        Path(str(entry["path"])).name: entry["signature"]["state"]
        for entry in first["files"]
    }
    assert states == {"left.txt": "file", "right.txt": "file", "missing.txt": "missing"}
