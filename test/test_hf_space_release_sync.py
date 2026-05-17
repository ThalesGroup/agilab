from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "hf_space_release_sync.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("hf_space_release_sync_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_runtime_url_matches_hf_space_subdomain() -> None:
    module = _load_module()

    assert module.runtime_url_for_space("jpmorard/agilab") == "https://jpmorard-agilab.hf.space"
    assert module.runtime_url_for_space("team-name/agilab-demo") == "https://team-name-agilab-demo.hf.space"


def test_parse_upload_commit_url() -> None:
    module = _load_module()

    assert module.parse_commit_sha(
        "url=https://huggingface.co/spaces/jpmorard/agilab/commit/"
        "0123456789abcdef0123456789abcdef01234567"
    ) == "0123456789abcdef0123456789abcdef01234567"


def test_generated_space_readme_uses_valid_hf_emoji_metadata() -> None:
    module = _load_module()

    assert "emoji: 🧪" in module.README_TEMPLATE
    assert "emoji: lab_coat" not in module.README_TEMPLATE
