"""Workflow data paths retain the session root and respect existing share ownership."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agi_cluster.agi_distributor.runtime import runtime_misc_support as runtime


class _BytesPath:
    def __fspath__(self):
        return b"module/input"


@pytest.mark.parametrize("value,expected", [
    (None, None), (42, None), (_BytesPath(), None), ("   ", None),
    ("/absolute/module/input", None), ("../escape", None), (".", None),
    ("module/input", "module"), ("module\\input", "module"),
    ("C:\\module\\input", None), ("./module/input", "module"),
])
def test_module_candidate_requires_nonempty_relative_text_path(value, expected):
    assert runtime._first_relative_data_path_segment(value) == expected


@pytest.mark.parametrize("root,args,expected", [
    (None, {}, None), ("  ", {"data_in": "module/input"}, "  "),
    ("module", {"data_in": "module/input"}, "module"),
    ("session/module", {"data_in": "module/input"}, "session"),
    ("session", {"data_in": "module/input"}, "session"),
    ("C:\\share\\session\\module", {"data_in": "module\\input"}, "C:\\share\\session"),
])
def test_worker_data_normalization_only_removes_redundant_module_suffix(root, args, expected):
    assert runtime.normalize_workers_data_path(root, args=args, worker_args=None) == expected


def test_module_candidates_ignore_absent_and_non_mapping_worker_args():
    assert runtime._worker_data_path_module_candidates(None, [], {"data_in": "a/input", "data_out": "b/output"}) == {"a", "b"}


def test_unresolvable_share_root_keeps_normalized_home_relative_path(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "resolve", Mock(side_effect=OSError("unavailable mount")))
    assert runtime._absolute_workers_data_share_root(
        SimpleNamespace(home_abs=tmp_path), "share/../session"
    ) == tmp_path / "session"


def test_missing_environment_home_uses_current_user_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert runtime._absolute_workers_data_share_root(SimpleNamespace(), "session") == (tmp_path / "session").resolve()


@pytest.mark.parametrize("root", [None, "", "   "])
def test_empty_worker_data_path_does_not_rebind_environment(root):
    env = SimpleNamespace(AGI_CLUSTER_SHARE="existing", envars={"keep": "value"})
    before = deepcopy(vars(env))
    runtime._apply_workers_data_path_to_env(env, root)
    assert vars(env) == before


def test_worker_path_outside_existing_share_is_not_rebound(tmp_path):
    env = SimpleNamespace(home_abs=tmp_path, AGI_CLUSTER_SHARE=str(tmp_path / "share"),
                          envars={"keep": "value"})
    before = deepcopy(vars(env))
    runtime._apply_workers_data_path_to_env(env, str(tmp_path / "elsewhere/session"))
    assert vars(env) == before
