from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_node.agi_dispatcher import base_worker_path_support as path_support


def test_base_worker_path_support_normalized_and_share_root(monkeypatch, tmp_path):
    assert path_support.normalized_path(
        "~/demo",
        normalize_path_fn=lambda _path: (_ for _ in ()).throw(OSError("boom")),
    ) == Path("~/demo").expanduser()

    env = SimpleNamespace(
        share_root_path=lambda: (_ for _ in ()).throw(OSError("no share")),
        agi_share_path_abs=None,
        agi_share_path=Path("clustershare"),
        home_abs=tmp_path,
    )
    assert path_support.share_root_path(env) == tmp_path / "clustershare"


def test_share_root_fallback_tolerates_missing_optional_path_attributes(tmp_path):
    env = SimpleNamespace(
        share_root_path=lambda: (_ for _ in ()).throw(OSError("no share")),
        home_abs=tmp_path,
    )

    assert path_support.share_root_path(env) == tmp_path


def test_worker_share_fallback_uses_runtime_home_for_relative_share(monkeypatch, tmp_path):
    worker_home = tmp_path / "worker-home"
    manager_home = tmp_path / "manager-home"
    worker_home.mkdir()
    manager_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: worker_home))

    env = SimpleNamespace(
        is_worker_env=True,
        share_root_path=lambda: (_ for _ in ()).throw(OSError("share unavailable")),
        agi_share_path_abs=manager_home / "clustershare" / "agi",
        agi_share_path=Path("clustershare") / "agi",
        home_abs=manager_home,
        _is_managed_pc=False,
    )

    expected_share = worker_home / "clustershare" / "agi"
    assert path_support.share_root_path(env) == expected_share

    resolved = path_support.resolve_data_dir(
        env,
        Path("demo") / "data",
        share_root_path_fn=lambda current_env: path_support.share_root_path(current_env),
        remap_managed_pc_path_fn=lambda value: Path(value),
        normalized_path_fn=lambda value: Path(value),
    )
    assert resolved == (expected_share / "demo" / "data").resolve(strict=False)


def test_worker_data_dir_resolves_share_prefixed_relative_path_once(monkeypatch, tmp_path):
    worker_home = tmp_path / "worker-home"
    manager_home = tmp_path / "manager-home"
    worker_home.mkdir()
    manager_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: worker_home))

    env = SimpleNamespace(
        is_worker_env=True,
        share_root_path=lambda: (_ for _ in ()).throw(OSError("share unavailable")),
        agi_share_path_abs=manager_home / "clustershare" / "agi",
        agi_share_path=Path("clustershare") / "agi",
        home_abs=manager_home,
        _is_managed_pc=False,
    )

    resolved = path_support.resolve_data_dir(
        env,
        Path("clustershare") / "agi" / "demo_project" / "session-a" / "workers",
        share_root_path_fn=lambda current_env: path_support.share_root_path(current_env),
        remap_managed_pc_path_fn=lambda value: Path(value),
        normalized_path_fn=lambda value: Path(value),
    )
    assert resolved == (
        worker_home / "clustershare" / "agi" / "demo_project" / "session-a" / "workers"
    ).resolve(strict=False)


def test_worker_data_dir_deduplicates_share_leaf_for_any_app_module(tmp_path):
    share_root = (
        tmp_path
        / "clustershare"
        / "agi"
        / "workflows"
        / "20260618T093102Z-492de776"
        / "any_module"
    )
    env = SimpleNamespace(
        share_root_path=lambda: share_root,
        agi_share_path_abs=None,
        agi_share_path=None,
        home_abs=tmp_path / "worker-home",
        _is_managed_pc=False,
    )

    resolved = path_support.resolve_data_dir(
        env,
        Path("any_module") / "dataset",
        share_root_path_fn=lambda current_env: path_support.share_root_path(current_env),
        remap_managed_pc_path_fn=lambda value: Path(value),
        normalized_path_fn=lambda value: Path(value),
    )

    assert resolved == (share_root / "dataset").resolve(strict=False)
    assert "any_module/any_module" not in resolved.as_posix()


def test_manager_data_dir_uses_active_workflow_data_root_not_cluster_share(tmp_path):
    session_root = (
        tmp_path / "clustershare" / "agi" / "workflows" / "20260618T093102Z-492de776"
    )
    legacy_root = tmp_path / "clustershare" / "agi"
    env = SimpleNamespace(
        AGILAB_WORKFLOW_DATA_ROOT=session_root,
        share_root_path=lambda: legacy_root,
        agi_share_path_abs=legacy_root,
        agi_share_path=Path("clustershare") / "agi",
        home_abs=tmp_path,
        _is_managed_pc=False,
    )

    resolved = path_support.resolve_data_dir(
        env,
        Path("flight_trajectory") / "dataset",
        share_root_path_fn=lambda current_env: path_support.share_root_path(current_env),
        remap_managed_pc_path_fn=lambda value: Path(value),
        normalized_path_fn=lambda value: Path(value),
    )

    assert resolved == (session_root / "flight_trajectory" / "dataset").resolve(strict=False)
    assert "workflows/20260618T093102Z-492de776/flight_trajectory/dataset" in resolved.as_posix()
    assert path_support.share_root_path(env) == session_root.resolve(strict=False)


def test_input_data_dir_falls_back_to_physical_share_when_session_input_missing(tmp_path):
    session_root = tmp_path / "clustershare" / "agi" / "workflows" / "run-1"
    physical_root = tmp_path / "clustershare" / "agi"
    seeded_input = physical_root / "uav_relay_queue" / "scenarios"
    seeded_input.mkdir(parents=True)

    env = SimpleNamespace(
        AGILAB_WORKFLOW_DATA_ROOT=session_root,
        share_root_path=lambda: physical_root,
        agi_share_path_abs=physical_root,
        agi_share_path=Path("clustershare") / "agi",
        home_abs=tmp_path,
        _is_managed_pc=False,
    )

    resolved = path_support.resolve_data_dir(
        env,
        Path("uav_relay_queue") / "scenarios",
        share_root_path_fn=lambda current_env: path_support.share_root_path(current_env),
        remap_managed_pc_path_fn=lambda value: Path(value),
        normalized_path_fn=lambda value: Path(value),
    )

    assert resolved == seeded_input.resolve(strict=False)

    session_input = session_root / "uav_relay_queue" / "scenarios"
    session_input.mkdir(parents=True)
    resolved = path_support.resolve_data_dir(
        env,
        Path("uav_relay_queue") / "scenarios",
        share_root_path_fn=lambda current_env: path_support.share_root_path(current_env),
        remap_managed_pc_path_fn=lambda value: Path(value),
        normalized_path_fn=lambda value: Path(value),
    )

    assert resolved == session_input.resolve(strict=False)


@pytest.mark.parametrize(
    "value",
    (Path("../outside/pipeline"), Path("nested/../../outside")),
)
def test_data_dir_rejects_relative_escape_from_trusted_roots(tmp_path, value):
    share_root = tmp_path / "share"
    env = SimpleNamespace(
        share_root_path=lambda: share_root,
        agi_share_path_abs=share_root,
        agi_share_path=Path("share"),
        home_abs=tmp_path,
        _is_managed_pc=False,
    )

    with pytest.raises(ValueError, match="parent traversal"):
        path_support.resolve_data_dir(
            env,
            value,
            share_root_path_fn=lambda current_env: path_support.share_root_path(
                current_env
            ),
            remap_managed_pc_path_fn=lambda candidate: Path(candidate),
            normalized_path_fn=lambda candidate: Path(candidate),
        )


def test_data_dir_rejects_absolute_and_symlink_escapes(tmp_path):
    share_root = tmp_path / "share"
    outside = tmp_path / "outside"
    share_root.mkdir()
    outside.mkdir()
    symlink = share_root / "linked-outside"
    symlink.symlink_to(outside, target_is_directory=True)
    env = SimpleNamespace(
        share_root_path=lambda: share_root,
        agi_share_path_abs=share_root,
        agi_share_path=Path("share"),
        home_abs=tmp_path,
        _is_managed_pc=False,
    )

    for value in (outside / "pipeline", symlink / "pipeline"):
        with pytest.raises(ValueError, match="must stay inside"):
            path_support.resolve_data_dir(
                env,
                value,
                share_root_path_fn=lambda current_env: path_support.share_root_path(
                    current_env
                ),
                remap_managed_pc_path_fn=lambda candidate: Path(candidate),
                normalized_path_fn=lambda candidate: Path(candidate),
            )


def test_data_dir_allows_absolute_workflow_and_physical_share_paths(tmp_path):
    physical_root = tmp_path / "share"
    workflow_root = physical_root / "workflows" / "run-1"
    env = SimpleNamespace(
        AGILAB_WORKFLOW_DATA_ROOT=workflow_root,
        share_root_path=lambda: physical_root,
        agi_share_path_abs=physical_root,
        agi_share_path=Path("share"),
        home_abs=tmp_path,
        _is_managed_pc=False,
    )

    for value in (workflow_root / "app/input", physical_root / "seed/input"):
        assert path_support.resolve_data_dir(
            env,
            value,
            share_root_path_fn=lambda current_env: path_support.share_root_path(
                current_env
            ),
            remap_managed_pc_path_fn=lambda candidate: Path(candidate),
            normalized_path_fn=lambda candidate: Path(candidate),
        ) == value.resolve(strict=False)


def test_data_dir_rejects_windows_drive_relative_path(tmp_path):
    env = SimpleNamespace(
        share_root_path=lambda: tmp_path / "share",
        agi_share_path_abs=tmp_path / "share",
        agi_share_path=Path("share"),
        home_abs=tmp_path,
        _is_managed_pc=False,
    )

    with pytest.raises(ValueError, match="drive-relative"):
        path_support.resolve_data_dir(
            env,
            "C:outside/pipeline",
            share_root_path_fn=lambda current_env: path_support.share_root_path(
                current_env
            ),
            remap_managed_pc_path_fn=lambda candidate: Path(candidate),
            normalized_path_fn=lambda candidate: Path(candidate),
        )


def test_generated_artifact_path_uses_output_root_not_dataset(tmp_path):
    dataset_root = tmp_path / "flight_trajectory" / "dataset"
    output_root = tmp_path / "flight_trajectory" / "dataframe"
    dataset_root.mkdir(parents=True)
    output_root.mkdir(parents=True)

    assert path_support.resolve_generated_artifact_path(
        dataset_root,
        output_root,
        "waypoints_split/001.geojson",
        normalized_path_fn=lambda value: Path(value).expanduser(),
    ) == (output_root / "waypoints_split" / "001.geojson").resolve(strict=False)

    assert path_support.resolve_generated_artifact_path(
        dataset_root,
        output_root,
        Path("dataset") / "waypoints.geojson",
        normalized_path_fn=lambda value: Path(value).expanduser(),
    ) == (output_root / "waypoints.geojson").resolve(strict=False)

    assert path_support.resolve_generated_artifact_path(
        dataset_root,
        output_root,
        dataset_root / "CloudMapIvdl.npz",
        normalized_path_fn=lambda value: Path(value).expanduser(),
    ) == (output_root / "CloudMapIvdl.npz").resolve(strict=False)


def test_generated_artifact_path_rejects_output_root_inside_dataset(tmp_path):
    dataset_root = tmp_path / "link_sim" / "dataset"
    output_root = dataset_root / "generated"

    with pytest.raises(ValueError, match="read-only data_in"):
        path_support.resolve_generated_artifact_path(
            dataset_root,
            output_root,
            "CloudMapSat.npz",
            normalized_path_fn=lambda value: Path(value).expanduser(),
        )


def test_generated_artifact_path_rejects_relative_parent_escape(tmp_path):
    # Regression: a relative artifact path with ".." parts must not climb out
    # of data_out (previously only "" and "." parts were filtered out).
    dataset_root = tmp_path / "flight_trajectory" / "dataset"
    output_root = tmp_path / "flight_trajectory" / "dataframe"
    dataset_root.mkdir(parents=True)
    output_root.mkdir(parents=True)

    with pytest.raises(ValueError, match="'\\.\\.'"):
        path_support.resolve_generated_artifact_path(
            dataset_root,
            output_root,
            "../../../evil.parquet",
            normalized_path_fn=lambda value: Path(value).expanduser(),
        )


def test_generated_artifact_path_rejects_absolute_outside_output(tmp_path):
    dataset_root = tmp_path / "flight_trajectory" / "dataset"
    output_root = tmp_path / "flight_trajectory" / "dataframe"
    outside = tmp_path / "outside" / "evil.parquet"

    with pytest.raises(ValueError, match="stay under data_out"):
        path_support.resolve_generated_artifact_path(
            dataset_root,
            output_root,
            outside,
            normalized_path_fn=lambda value: Path(value).expanduser(),
        )


def test_generated_artifact_path_rejects_windows_drive_relative_path(tmp_path):
    with pytest.raises(ValueError, match="drive-relative"):
        path_support.resolve_generated_artifact_path(
            tmp_path / "dataset",
            tmp_path / "dataframe",
            "C:outside/evil.parquet",
            normalized_path_fn=lambda value: Path(value).expanduser(),
        )


def test_share_output_path_verifies_even_lenient_runtime_resolver(tmp_path):
    share_root = tmp_path / "share"

    def _lenient_resolver(value):
        candidate = Path(value)
        return candidate if candidate.is_absolute() else share_root / candidate

    env = SimpleNamespace(resolve_share_path=_lenient_resolver)

    assert path_support.resolve_share_output_path(env, "app/evidence") == (
        share_root / "app/evidence"
    ).resolve(strict=False)
    with pytest.raises(ValueError, match="active share root"):
        path_support.resolve_share_output_path(env, tmp_path / "outside")


def test_safe_reset_path_requires_a_descendant_of_a_trusted_root(tmp_path):
    share_root = tmp_path / "share"
    target = share_root / "app/evidence"

    assert path_support.safe_reset_path(
        target,
        roots=(share_root,),
        label="data_out",
    ) == target.resolve(strict=False)
    with pytest.raises(ValueError, match="confinement root"):
        path_support.safe_reset_path(
            share_root,
            roots=(share_root,),
            label="data_out",
        )
    with pytest.raises(ValueError, match="trusted root"):
        path_support.safe_reset_path(
            tmp_path / "outside",
            roots=(share_root,),
            label="data_out",
        )


@pytest.mark.parametrize("relation", ("ancestor", "descendant"))
def test_safe_reset_path_rejects_overlap_with_protected_input(tmp_path, relation):
    share_root = tmp_path / "share"
    protected = share_root / "app" / "input"
    protected.mkdir(parents=True)
    target = share_root / "app" if relation == "ancestor" else protected / "generated"

    with pytest.raises(ValueError, match="must not overlap protected input"):
        path_support.safe_reset_path(
            target,
            roots=(share_root,),
            protected_paths=(protected,),
            label="data_out",
        )


def test_case_alias_uses_filesystem_identity_for_containment_and_relative_suffix(tmp_path):
    share_root = tmp_path / "WorkflowRoot"
    share_root.mkdir()
    case_variant = tmp_path / "workflowroot"
    if not case_variant.exists():
        pytest.skip("temporary filesystem is case-sensitive")

    alias_child = case_variant / "inputs" / "dataset.csv"
    assert path_support._path_is_relative_to(alias_child, share_root)
    assert path_support._relative_path_under(alias_child, share_root) == Path(
        "inputs/dataset.csv"
    )

    with pytest.raises(ValueError, match="confinement root"):
        path_support.safe_reset_path(
            case_variant,
            roots=(share_root,),
            label="data_out",
        )


def test_case_distinct_sibling_is_not_authorized_on_case_sensitive_volume(tmp_path):
    share_root = tmp_path / "WorkflowRoot"
    share_root.mkdir()
    case_variant = tmp_path / "workflowroot"
    try:
        case_variant.mkdir()
    except FileExistsError:
        pytest.skip("temporary filesystem is case-insensitive")
    if case_variant.samefile(share_root):
        pytest.skip("temporary filesystem aliases case variants")

    target = case_variant / "output"
    assert not path_support._path_is_relative_to(target, share_root)
    with pytest.raises(ValueError, match="trusted root"):
        path_support.safe_reset_path(target, roots=(share_root,), label="data_out")


def test_generated_artifact_path_catches_case_variant_of_data_in(tmp_path):
    # Regression: on case-insensitive filesystems a case-variant spelling of
    # data_in (e.g. .../DATASET) must still be recognised as aliasing the
    # read-only input tree instead of passing the guard.
    dataset_root = tmp_path / "link_sim" / "dataset"
    output_root = tmp_path / "link_sim" / "dataframe"
    dataset_root.mkdir(parents=True)
    output_root.mkdir(parents=True)

    case_variant_input = tmp_path / "link_sim" / "DATASET" / "x.parquet"
    if not case_variant_input.parent.exists():
        pytest.skip("temporary filesystem is case-sensitive")

    resolved = path_support.resolve_generated_artifact_path(
        dataset_root,
        output_root,
        case_variant_input,
        normalized_path_fn=lambda value: Path(value).expanduser(),
    )
    # The dataset prefix (case-insensitively matched) is rerooted under
    # data_out rather than left pointing at the read-only input tree.
    assert resolved == (output_root / "x.parquet").resolve(strict=False)
    assert not path_support._path_is_relative_to(resolved, dataset_root.resolve(strict=False))


def test_path_is_relative_to_matches_exact_case_on_all_platforms():
    parent = Path("/data/dataset")
    child = Path("/data/dataset/sub/x.parquet")
    assert path_support._path_is_relative_to(child, parent) is True
    assert path_support._path_is_relative_to(Path("/data/other"), parent) is False


def test_artifact_dir_prefers_export_root_then_share_resolver(tmp_path):
    export_root = tmp_path / "explicit-export"
    env = SimpleNamespace(
        AGILAB_EXPORT_ABS=export_root,
        target="demo_project",
        resolve_share_path=lambda relative: tmp_path / "share" / relative,
        home_abs=tmp_path / "home",
        _is_managed_pc=False,
    )

    assert path_support.resolve_artifact_dir(env, "analysis") == export_root / "demo_project" / "analysis"

    env.AGILAB_EXPORT_ABS = None
    assert path_support.resolve_artifact_dir(env, "analysis") == (
        tmp_path / "share" / "demo_project" / "analysis"
    ).resolve(strict=False)


def test_artifact_dir_uses_workflow_root_before_process_home(monkeypatch, tmp_path):
    process_home = tmp_path / "polluted-home"
    process_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: process_home))

    workflow_root = tmp_path / "clustershare" / "workflow-a"
    env = SimpleNamespace(
        AGILAB_WORKFLOW_DATA_ROOT=workflow_root,
        target="demo_project",
        share_root_path=lambda: tmp_path / "legacy-share",
        agi_share_path_abs=None,
        agi_share_path=None,
        home_abs=tmp_path / "env-home",
        _is_managed_pc=False,
    )

    assert path_support.resolve_artifact_dir(env, "analysis") == (
        workflow_root / "demo_project" / "analysis"
    ).resolve(strict=False)


def test_artifact_dir_local_fallback_uses_env_home_abs(monkeypatch, tmp_path):
    process_home = tmp_path / "polluted-home"
    env_home = tmp_path / "env-home"
    process_home.mkdir()
    env_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: process_home))

    env = SimpleNamespace(
        target="demo_project",
        share_root_path=lambda: (_ for _ in ()).throw(OSError("no share")),
        agi_share_path_abs=None,
        agi_share_path=None,
        home_abs=env_home,
        _is_managed_pc=False,
    )

    assert path_support.resolve_artifact_dir(env, "analysis") == (
        env_home / "export" / "demo_project" / "analysis"
    )
    assert path_support.resolve_artifact_dir(env, ".") == env_home / "export" / "demo_project"


def test_base_worker_path_support_data_dir_aliases_and_home_remap(monkeypatch, tmp_path):
    class _BrokenPath:
        def __fspath__(self):
            raise OSError("boom")

    env = SimpleNamespace(
        AGILAB_SHARE_HINT=Path("clustershare/link_sim"),
        AGILAB_SHARE_REL=_BrokenPath(),
        agi_share_path=_BrokenPath(),
        share_root_path=lambda: tmp_path / "share",
        agi_share_path_abs=tmp_path / "share",
        home_abs=tmp_path / "home",
        _is_managed_pc=False,
    )
    (tmp_path / "share").mkdir()

    aliases = path_support.collect_share_aliases(env, tmp_path / "share")
    assert {"share", "clustershare", "data", "datashare", "link_sim"} <= aliases

    fallback = path_support.resolve_data_dir(
        env,
        Path("dataset") / "inputs",
        share_root_path_fn=lambda current_env: path_support.share_root_path(current_env),
        remap_managed_pc_path_fn=lambda value: Path(value),
        normalized_path_fn=lambda value: Path(value),
    )
    assert fallback == (tmp_path / "share" / "dataset" / "inputs").resolve(strict=False)

    home_path = Path("/Users/demo/data/file.csv")
    assert path_support.relative_to_user_home(home_path) == Path("data/file.csv")
    assert path_support.relative_to_user_home(Path("/tmp/data/file.csv")) is None
    assert path_support.remap_user_home(home_path, username="other") == Path("/Users/other/data/file.csv")
    assert path_support.remap_user_home(Path("/tmp/data/file.csv"), username="other") is None
    assert path_support.strip_share_prefix(Path("clustershare/demo/file.csv"), {"clustershare"}) == Path("demo/file.csv")


def test_base_worker_path_support_unexpected_runtime_bugs_propagate(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="normalize bug"):
        path_support.normalized_path(
            "~/demo",
            normalize_path_fn=lambda _path: (_ for _ in ()).throw(RuntimeError("normalize bug")),
        )

    env = SimpleNamespace(
        share_root_path=lambda: (_ for _ in ()).throw(RuntimeError("share bug")),
        agi_share_path_abs=None,
        agi_share_path=Path("clustershare"),
        home_abs=tmp_path,
    )
    with pytest.raises(RuntimeError, match="share bug"):
        path_support.share_root_path(env)

    class _BrokenRuntimePath:
        def __fspath__(self):
            raise RuntimeError("alias bug")

    env_alias = SimpleNamespace(
        AGILAB_SHARE_HINT=Path("clustershare/link_sim"),
        AGILAB_SHARE_REL=_BrokenRuntimePath(),
        agi_share_path=Path("clustershare"),
    )
    with pytest.raises(RuntimeError, match="alias bug"):
        path_support.collect_share_aliases(env_alias, tmp_path / "share")

    monkeypatch.setattr(
        Path,
        "unlink",
        lambda self, *args, **kwargs: (_ for _ in ()).throw(RuntimeError("cleanup bug")),
    )
    with pytest.raises(RuntimeError, match="cleanup bug"):
        path_support.can_create_path(tmp_path / "output" / "data.csv")


def test_base_worker_path_support_managed_pc_fallbacks_and_direct_input_success(tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    class _FlakyPathFactory:
        def __init__(self):
            self.calls = 0

        def __call__(self, value):
            self.calls += 1
            if self.calls == 1:
                raise OSError("boom")
            return Path(value)

    env = SimpleNamespace(
        _is_managed_pc=True,
        agi_share_path=fake_home / "clustershare",
    )
    original_share = env.agi_share_path
    sample = fake_home / "dataset" / "file.csv"

    assert path_support.remap_managed_pc_path(
        sample,
        env=env,
        path_cls=_FlakyPathFactory(),
        home_factory=lambda: fake_home,
    ) == sample

    path_support.ensure_managed_pc_share_dir(
        env,
        path_cls=_FlakyPathFactory(),
        home_factory=lambda: fake_home,
    )
    assert env.agi_share_path == original_share

    flights_dir = tmp_path / "dataset" / "flights"
    flights_dir.mkdir(parents=True)
    (flights_dir / "a.csv").write_text("x\n1\n", encoding="utf-8")
    (flights_dir / "b.csv").write_text("x\n2\n", encoding="utf-8")

    resolved = path_support.resolve_input_folder(
        None,
        tmp_path / "dataset",
        "flights",
        descriptor="demo generator",
        fallback_subdirs=("csv",),
        min_files=2,
        patterns=("*.csv",),
        required_label="csv files",
        normalized_path_fn=lambda value: Path(value).expanduser(),
        has_min_input_files_fn=lambda folder, min_files=1, patterns=None: path_support.has_min_input_files(
            folder,
            min_files=min_files,
            patterns=patterns,
        ),
        candidate_named_dataset_roots_fn=lambda _env, _root, namespace=None: [],
    )

    assert resolved == flights_dir.resolve(strict=False)
    assert path_support.remap_user_home(Path("demo"), username="other") is None


def test_base_worker_path_support_candidate_roots_and_resolve_input_folder(tmp_path):
    share_root = tmp_path / "share"
    dataset_root = tmp_path / "runtime" / "dataset"
    flights_dir = share_root / "link_sim" / "dataset" / "flights"
    flights_dir.mkdir(parents=True)
    (flights_dir / "plane0.csv").write_text("plane_id,time_s\n0,0\n")
    (flights_dir / "plane1.csv").write_text("plane_id,time_s\n1,1\n")

    env = SimpleNamespace(
        share_root_path=lambda: share_root,
        agi_share_path_abs=share_root,
        agi_share_path=share_root,
        home_abs=Path.home(),
        AGILAB_SHARE_HINT=None,
        AGILAB_SHARE_REL=None,
        _is_managed_pc=False,
    )

    candidates = path_support.candidate_named_dataset_roots(
        env,
        dataset_root,
        namespace="link_sim",
        normalized_path_fn=lambda value: Path(value).expanduser(),
        share_root_path_fn=lambda current_env: path_support.share_root_path(current_env),
    )
    assert share_root / "link_sim" in candidates
    assert share_root / "link_sim" / "dataset" in candidates

    warnings: list[str] = []
    resolved = path_support.resolve_input_folder(
        env,
        dataset_root,
        "flight_trajectory/pipeline",
        descriptor="flight_trajectory",
        fallback_subdirs=("flights",),
        dataset_namespace="link_sim",
        min_files=2,
        required_label="plane trajectory files",
        normalized_path_fn=lambda value: Path(value).expanduser(),
        has_min_input_files_fn=lambda folder, min_files=1, patterns=None: path_support.has_min_input_files(
            folder,
            min_files=min_files,
            patterns=patterns,
        ),
        candidate_named_dataset_roots_fn=lambda current_env, root, namespace=None: path_support.candidate_named_dataset_roots(
            current_env,
            root,
            namespace=namespace,
            normalized_path_fn=lambda value: Path(value).expanduser(),
            share_root_path_fn=lambda support_env: path_support.share_root_path(support_env),
        ),
        warn_fn=lambda msg, *args: warnings.append(msg % args),
    )

    assert resolved == flights_dir
    assert warnings


def test_base_worker_path_support_iter_input_files_and_can_create_path(tmp_path, monkeypatch):
    folder = tmp_path / "dataset"
    folder.mkdir()
    (folder / "a.csv").write_text("x\n1\n", encoding="utf-8")
    (folder / "b.parquet").write_text("pq", encoding="utf-8")
    (folder / "._hidden.csv").write_text("hidden", encoding="utf-8")

    files = path_support.iter_input_files(folder)
    assert [path.name for path in files] == ["a.csv", "b.parquet"]
    assert path_support.has_min_input_files(folder, min_files=2, patterns=("*.csv", "*.parquet")) is True

    writable_target = tmp_path / "output" / "data.csv"
    assert path_support.can_create_path(writable_target) is True

    monkeypatch.setattr(
        Path,
        "touch",
        lambda self, *args, **kwargs: (_ for _ in ()).throw(PermissionError("denied")),
    )
    assert path_support.can_create_path(tmp_path / "blocked" / "data.csv") is False
