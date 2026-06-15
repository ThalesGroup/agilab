from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = REPO_ROOT / "tools"
MODULE_PATH = REPO_ROOT / "tools/pypi_release_version_policy.py"
sys.path.insert(0, str(TOOLS_ROOT))


def _load_policy():
    spec = importlib.util.spec_from_file_location("pypi_release_version_policy_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_release_version_policy_accepts_stable_versions() -> None:
    policy = _load_policy()

    result = policy.validate_public_release_versions(
        {
            "agilab": "2026.05.18",
            "agi-core": "2026.05.18",
        }
    )

    assert "release_mode=stable accepted" in result


def test_release_version_policy_accepts_hotfix_versions() -> None:
    policy = _load_policy()

    result = policy.validate_public_release_versions(
        {
            "agilab": "2026.05.18.1",
            "agi-core": "2026.05.18.1",
        },
        release_mode="hotfix",
    )

    assert "release_mode=hotfix accepted" in result


def test_release_version_policy_accepts_candidate_versions() -> None:
    policy = _load_policy()

    result = policy.validate_public_release_versions(
        {"agilab": "2026.05.18rc1"},
        release_mode="candidate",
    )

    assert "release_mode=candidate accepted" in result


def test_release_version_policy_rejects_public_post_release_even_with_hotfix_mode() -> None:
    policy = _load_policy()

    with pytest.raises(policy.ReleaseVersionPolicyError) as excinfo:
        policy.validate_public_release_versions(
            {"agilab": "2026.05.18.post1"},
            release_mode="hotfix",
        )

    message = str(excinfo.value)
    assert ".postN releases are forbidden" in message
    assert "release_mode=hotfix with package version YYYY.MM.DD.N" in message
    assert "release tag vYYYY.MM.DD_N" in message


def test_release_version_policy_rejects_stable_shape_in_hotfix_mode() -> None:
    policy = _load_policy()

    with pytest.raises(policy.ReleaseVersionPolicyError) as excinfo:
        policy.validate_public_release_versions(
            {"agilab": "2026.05.18"},
            release_mode="hotfix",
        )

    assert "release_mode=hotfix rejected version shape" in str(excinfo.value)


def test_release_version_policy_repair_mode_rejects_pypi_publications() -> None:
    policy = _load_policy()

    with pytest.raises(policy.ReleaseVersionPolicyError) as excinfo:
        policy.validate_public_release_versions(
            {"agilab": "2026.05.18"},
            release_mode="repair",
        )

    assert "release_mode=repair must not publish PyPI package distributions" in str(excinfo.value)


def test_selected_public_versions_reads_filtered_package_versions(tmp_path, monkeypatch) -> None:
    policy = _load_policy()

    root_pyproject = tmp_path / "pyproject.toml"
    root_pyproject.write_text(
        "[project]\nname = 'agilab'\nversion = '2026.05.18rc1'\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        policy,
        "public_package_entries",
        lambda **_kwargs: [{"package": "agilab", "project": "."}],
    )

    assert policy.selected_public_versions(tmp_path, package_names=("agilab",)) == {
        "agilab": "2026.05.18rc1"
    }


def test_public_package_entries_can_reuse_release_plan_skip_existing_mode(
    tmp_path, monkeypatch
) -> None:
    policy = _load_policy()
    observed = {}

    def fake_release_plan(**kwargs):
        observed.update(kwargs)
        return {
            "library_matrix": [{"package": "agi-env", "publish_to_pypi": "true"}],
            "umbrella_package": {"package": "agilab", "publish_to_pypi": "true"},
            "umbrella_selected": "false",
        }

    monkeypatch.setattr(policy, "release_plan", fake_release_plan)

    entries = policy.public_package_entries(
        repo_root=tmp_path,
        package_names=("agi-env",),
        roles=("runtime-component",),
        skip_existing_pypi=True,
    )

    assert entries == [{"package": "agi-env", "publish_to_pypi": "true"}]
    assert observed["repo_root"] == tmp_path
    assert observed["package_names"] == ("agi-env",)
    assert observed["roles"] == ("runtime-component",)
    assert observed["skip_existing_pypi"] is True


def test_public_package_entries_passes_impact_base_ref_to_release_plan(
    tmp_path, monkeypatch
) -> None:
    policy = _load_policy()
    observed = {}

    def fake_release_plan(**kwargs):
        observed.update(kwargs)
        return {
            "library_matrix": [
                {"package": "agi-app-pytorch-playground", "publish_to_pypi": "true"}
            ],
            "umbrella_package": {"package": "agilab", "publish_to_pypi": "true"},
            "umbrella_selected": "true",
        }

    monkeypatch.setattr(policy, "release_plan", fake_release_plan)

    entries = policy.public_package_entries(
        repo_root=tmp_path,
        impact_base_ref="v2026.05.31",
    )

    assert entries == [
        {"package": "agi-app-pytorch-playground", "publish_to_pypi": "true"},
        {"package": "agilab", "publish_to_pypi": "true"},
    ]
    assert observed["impact_base_ref"] == "v2026.05.31"
