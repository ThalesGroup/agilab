from pathlib import Path

import agi_env.share_runtime_support as share_runtime_module
import pytest


def test_share_runtime_helpers_cover_target_path_modes_and_ip_validation(tmp_path: Path):
    share_root = tmp_path / "clustershare"
    share_root.mkdir()

    assert share_runtime_module.share_target_name("demo_project", "ignored_project") == "demo"
    assert share_runtime_module.share_target_name(None, "demo_worker") == "demo"
    assert share_runtime_module.share_target_name(None, None) == "app"

    assert share_runtime_module.resolve_share_path(None, share_root) == share_root
    assert share_runtime_module.resolve_share_path("demo/data", share_root) == share_root / "demo" / "data"
    with pytest.raises(ValueError, match="share root"):
        share_runtime_module.resolve_share_path("/tmp/absolute", share_root)

    assert share_runtime_module.mode_to_str(0b0111, hw_rapids_capable=False) == "_dcp"
    assert share_runtime_module.mode_to_str(0b0111, hw_rapids_capable=True) == "rdcp"
    # Bit 8 (r) already set: rapids-capable must OR, not add (arithmetic + 8
    # would carry into higher bits and corrupt the label).
    assert share_runtime_module.mode_to_str(0b1111, hw_rapids_capable=False) == "rdcp"
    assert share_runtime_module.mode_to_str(0b1111, hw_rapids_capable=True) == "rdcp"
    # r|p already set: rapids-capable is idempotent and leaves the label intact.
    assert share_runtime_module.mode_to_str(0b1001, hw_rapids_capable=True) == "r__p"
    # Bitmask must match AGI constants and mode_to_str: p=1, c=2, d=4, r=8.
    assert share_runtime_module.mode_to_int("pc") == 0b0011
    assert share_runtime_module.mode_to_int("p") == 1
    assert share_runtime_module.mode_to_int("c") == 2
    assert share_runtime_module.mode_to_int("d") == 4
    assert share_runtime_module.mode_to_int("r") == 8
    assert share_runtime_module.mode_to_int("pcdr") == 0b1111
    # Round-trip with mode_to_str.
    assert share_runtime_module.mode_to_str(share_runtime_module.mode_to_int("dcp")) == "_dcp"

    assert share_runtime_module.is_valid_ip("192.168.20.130") is True
    assert share_runtime_module.is_valid_ip("999.1.1.1") is False
    assert share_runtime_module.is_valid_ip("not-an-ip") is False


def test_resolve_share_input_path_prefers_workflow_then_confined_physical_fallback(
    tmp_path: Path,
) -> None:
    physical_root = tmp_path / "cluster"
    workflow_root = physical_root / "users" / "agi" / "workflow" / "session"
    workflow_dataset = workflow_root / "workflow-only" / "dataset"
    shared_dataset = physical_root / "shared" / "dataset"
    workflow_dataset.mkdir(parents=True)
    shared_dataset.mkdir(parents=True)

    assert (
        share_runtime_module.resolve_share_input_path(
            "workflow-only/dataset", workflow_root, physical_root
        )
        == workflow_dataset
    )
    assert (
        share_runtime_module.resolve_share_input_path(
            "shared/dataset", workflow_root, physical_root
        )
        == shared_dataset
    )
    assert (
        share_runtime_module.resolve_share_input_path(
            shared_dataset, workflow_root, physical_root
        )
        == shared_dataset
    )
    with pytest.raises(ValueError, match="share root"):
        share_runtime_module.resolve_share_input_path(
            tmp_path / "outside", workflow_root, physical_root
        )


def test_resolve_share_input_path_accepts_case_alias_on_case_insensitive_volume(
    tmp_path: Path,
) -> None:
    physical_root = tmp_path / "PhysicalShare"
    workflow_root = physical_root / "workflow" / "session"
    shared_dataset = physical_root / "shared" / "dataset"
    workflow_root.mkdir(parents=True)
    shared_dataset.mkdir(parents=True)

    case_alias = tmp_path / "physicalshare"
    if not case_alias.exists():
        pytest.skip("temporary filesystem is case-sensitive")

    resolved = share_runtime_module.resolve_share_input_path(
        case_alias / "shared" / "dataset",
        workflow_root,
        physical_root,
    )

    assert resolved.samefile(shared_dataset)


def test_resolve_share_input_path_rejects_case_distinct_sibling_on_case_sensitive_volume(
    tmp_path: Path,
) -> None:
    physical_root = tmp_path / "PhysicalShare"
    workflow_root = physical_root / "workflow" / "session"
    case_distinct_root = tmp_path / "physicalshare"
    workflow_root.mkdir(parents=True)
    try:
        case_distinct_root.mkdir()
    except FileExistsError:
        pytest.skip("temporary filesystem is case-insensitive")
    if case_distinct_root.samefile(physical_root):
        pytest.skip("temporary filesystem aliases case variants")
    outside_dataset = case_distinct_root / "shared" / "dataset"
    outside_dataset.mkdir(parents=True)

    with pytest.raises(ValueError, match="share root"):
        share_runtime_module.resolve_share_input_path(
            outside_dataset,
            workflow_root,
            physical_root,
        )


@pytest.mark.parametrize(
    "value",
    ("", ".", "./", "./.", "~", "~/", "/", "//", "/./"),
)
def test_validate_worker_share_root_rejects_degenerate_roots(value: str) -> None:
    with pytest.raises(ValueError, match="Workers Data Path"):
        share_runtime_module.validate_worker_share_root(value)


@pytest.mark.parametrize(
    "value",
    (
        "/home/agi",
        "/home/agi/.",
        "//home/agi/.",
        "/HOME/agi",
        "/Users/agi",
        "/Users/agi/.",
        "/users/agi",
        "/root",
        "/root/.",
        "//ROOT/.",
        "/var/root",
        "/var/root/.",
        "//VAR/root/.",
    ),
)
def test_validate_worker_share_root_rejects_absolute_worker_home_aliases(
    value: str,
) -> None:
    with pytest.raises(ValueError, match="worker home or system root"):
        share_runtime_module.validate_worker_share_root(value)


_SENSITIVE_SYSTEM_ROOTS = (
    "/etc",
    "/usr",
    "/var",
    "/proc",
    "/sys",
    "/dev",
    "/boot",
    "/bin",
    "/sbin",
    "/lib",
    "/opt",
    "/tmp",
    "/mnt",
)


@pytest.mark.parametrize(
    "value",
    (
        *_SENSITIVE_SYSTEM_ROOTS,
        *(f"{root}/." for root in _SENSITIVE_SYSTEM_ROOTS),
    ),
)
def test_validate_worker_share_root_rejects_sensitive_system_roots(
    value: str,
) -> None:
    with pytest.raises(ValueError, match="system root"):
        share_runtime_module.validate_worker_share_root(value)


@pytest.mark.parametrize(
    "value",
    (
        "clustershare",
        "~/clustershare",
        "/mnt/agilab",
        "/var/lib/agilab",
        "/tmp/agilab",
    ),
)
def test_validate_worker_share_root_accepts_dedicated_roots(value: str) -> None:
    assert share_runtime_module.validate_worker_share_root(value) == value


@pytest.mark.parametrize(
    "value",
    ("/", "/etc", "/mnt", "/home/agi", "/Users/agi", "/var/root"),
)
def test_validate_local_share_root_rejects_ambient_roots(value: str) -> None:
    with pytest.raises(ValueError, match="AGI_CLUSTER_SHARE"):
        share_runtime_module.validate_local_share_root(value)


def test_validate_local_share_root_rejects_home_alias_and_allows_nested_share(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home" / "agi"
    home.mkdir(parents=True)
    home_alias = tmp_path / "home-alias"
    try:
        home_alias.symlink_to(home, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    with pytest.raises(ValueError, match="scheduler home"):
        share_runtime_module.validate_local_share_root(
            home_alias,
            home_roots=(home,),
        )

    dedicated = home / "clustershare"
    assert share_runtime_module.validate_local_share_root(
        dedicated,
        home_roots=(home,),
    ) == dedicated.resolve(strict=False)


def test_python_supports_free_threading_prefers_runtime_probe(monkeypatch):
    monkeypatch.setattr(share_runtime_module.sys, "_is_gil_enabled", lambda: False, raising=False)

    assert share_runtime_module.python_supports_free_threading() is True


def test_python_supports_free_threading_falls_back_to_sysconfig(monkeypatch):
    monkeypatch.delattr(share_runtime_module.sys, "_is_gil_enabled", raising=False)
    monkeypatch.setattr(
        share_runtime_module.sysconfig,
        "get_config_var",
        lambda name: 1 if name == "Py_GIL_DISABLED" else None,
    )

    assert share_runtime_module.python_supports_free_threading() is True


def test_python_supports_free_threading_handles_runtime_probe_failure(monkeypatch):
    monkeypatch.setattr(
        share_runtime_module.sys,
        "_is_gil_enabled",
        lambda: (_ for _ in ()).throw(RuntimeError("probe unavailable")),
        raising=False,
    )
    monkeypatch.setattr(
        share_runtime_module.sysconfig,
        "get_config_var",
        lambda name: 0 if name == "Py_GIL_DISABLED" else None,
    )

    assert share_runtime_module.python_supports_free_threading() is False


def test_python_supports_free_threading_propagates_unexpected_runtime_probe_bug(monkeypatch):
    monkeypatch.setattr(
        share_runtime_module.sys,
        "_is_gil_enabled",
        lambda: (_ for _ in ()).throw(ValueError("probe bug")),
        raising=False,
    )

    with pytest.raises(ValueError, match="probe bug"):
        share_runtime_module.python_supports_free_threading()


def test_python_supports_free_threading_propagates_unexpected_sysconfig_bug(monkeypatch):
    monkeypatch.delattr(share_runtime_module.sys, "_is_gil_enabled", raising=False)
    monkeypatch.setattr(
        share_runtime_module.sysconfig,
        "get_config_var",
        lambda _name: (_ for _ in ()).throw(RuntimeError("sysconfig bug")),
    )

    with pytest.raises(RuntimeError, match="sysconfig bug"):
        share_runtime_module.python_supports_free_threading()
