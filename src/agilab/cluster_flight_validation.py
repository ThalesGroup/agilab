"""Repeatable two-node Flight cluster validation helper."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from agilab.cluster_lan_discovery import (
    DiscoveryOptions,
    default_cache_path,
    discover_lan_nodes,
    parse_cidr_values,
    print_discovery_report,
)


DEFAULT_APP = "flight_telemetry_project"
DEFAULT_DATASET_REL = Path("localshare/flight_cluster_validation/dataset/csv")
DEFAULT_OUTPUT_REL = Path("flight_cluster_validation/dataframe_cluster_validation")
DEFAULT_AIRCRAFT = tuple(range(60, 76))
SHARE_SENTINEL_DIR = Path(".agilab_cluster_doctor")
SSHFS_INSTALL_HINT = (
    "sshfs is required to mount AGI_CLUSTER_SHARE on this worker. "
    "Install sshfs first: Debian/Ubuntu: sudo apt-get install -y sshfs; "
    "macOS: install macFUSE/FUSE-T SSHFS and ensure sshfs is visible to non-interactive SSH."
)
SSHFS_OPTIONS = (
    "reconnect",
    "ServerAliveInterval=15",
    "ServerAliveCountMax=3",
    "BatchMode=yes",
    "StrictHostKeyChecking=yes",
    "noexec",
)


@dataclass(frozen=True)
class WorkerSpec:
    host: str
    count: int = 1
    user: str | None = None

    @property
    def ssh_target(self) -> str:
        return f"{self.user}@{self.host}" if self.user else self.host


@dataclass(frozen=True)
class ValidationPlan:
    app: str
    apps_path: Path
    scheduler: str
    workers: dict[str, int]
    worker_specs: tuple[WorkerSpec, ...]
    remote_user: str
    local_share_setting: str
    local_cluster_share_setting: str
    remote_cluster_share_setting: str
    local_dataset_dir: Path
    dataset_rel_to_home: Path
    output_rel: Path
    aircraft: tuple[int, ...]
    rows_per_aircraft: int
    modes_enabled: int

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "apps_path",
            "local_dataset_dir",
            "dataset_rel_to_home",
            "output_rel",
        ):
            payload[key] = str(payload[key])
        return payload


@dataclass(frozen=True)
class OutputSummary:
    location: str
    path: str
    parquet_files: tuple[str, ...]
    reduce_artifacts: tuple[str, ...]
    row_count: int
    aircraft: tuple[str, ...]

    @property
    def has_result(self) -> bool:
        return bool(self.parquet_files or self.reduce_artifacts)


@dataclass(frozen=True)
class ShareProbeSummary:
    location: str
    path: str


@dataclass(frozen=True)
class ShareSetupSummary:
    location: str
    action: str
    path: str


def _default_apps_path() -> Path:
    return Path(__file__).resolve().parent / "apps" / "builtin"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the built-in Flight app on a small AGILAB cluster using "
            "synthetic CSV inputs and explicit local/remote path reporting."
        )
    )
    parser.add_argument(
        "--cluster",
        action="store_true",
        help="Run the cluster validation. Required for the doctor subcommand.",
    )
    parser.add_argument("--scheduler", default="", help="Scheduler host or IP.")
    parser.add_argument(
        "--workers",
        default="",
        help=(
            "Comma-separated workers. Forms: host, host:count, user@host, "
            "or user@host:count."
        ),
    )
    parser.add_argument("--remote-user", default="", help="SSH user when not embedded in --workers.")
    parser.add_argument("--ssh-key", default="", help="Optional SSH private key path for AGI.")
    parser.add_argument("--app", default=DEFAULT_APP, help=f"App name. Default: {DEFAULT_APP}.")
    parser.add_argument(
        "--apps-path",
        default=str(_default_apps_path()),
        help="Directory containing app projects. Defaults to packaged built-in apps.",
    )
    parser.add_argument(
        "--local-share",
        default="localshare",
        help=(
            "Local input-share setting. Keep it under $HOME so Flight worker "
            "file paths stay portable. Default: localshare."
        ),
    )
    parser.add_argument(
        "--cluster-share",
        default="",
        help=(
            "Local cluster-share setting. Defaults to AGI_CLUSTER_SHARE or "
            "clustershare/$USER."
        ),
    )
    parser.add_argument(
        "--remote-cluster-share",
        default="clustershare",
        help=(
            "Remote worker AGI_CLUSTER_SHARE setting written during install. "
            "Relative values resolve under the remote user's home. Default: clustershare."
        ),
    )
    parser.add_argument(
        "--dataset-rel",
        default=str(DEFAULT_DATASET_REL.relative_to("localshare")),
        help="Dataset path relative to --local-share. Default: flight_cluster_validation/dataset/csv.",
    )
    parser.add_argument(
        "--output-rel",
        default=str(DEFAULT_OUTPUT_REL),
        help="Output path relative to the cluster share.",
    )
    parser.add_argument(
        "--aircraft",
        default=",".join(str(item) for item in DEFAULT_AIRCRAFT),
        help="Comma-separated two-digit aircraft IDs to synthesize. Default: 60-75.",
    )
    parser.add_argument(
        "--rows-per-aircraft",
        type=int,
        default=3,
        help="Rows written per synthetic aircraft CSV. Default: 3.",
    )
    parser.add_argument(
        "--modes-enabled",
        type=int,
        default=15,
        help="AGI.install modes_enabled bitmask. Default: 15.",
    )
    parser.add_argument("--timeout", type=int, default=180, help="AGI timeout in seconds.")
    parser.add_argument("--verbose", type=int, default=1, help="AGI verbosity.")
    parser.add_argument(
        "--summary-json",
        default="",
        help="Optional file path for a machine-readable validation summary.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Prepare inputs and print the resolved plan without SSH or AGI execution.",
    )
    parser.add_argument(
        "--share-check-only",
        action="store_true",
        help="Validate only the shared cluster-share sentinel; skip Flight install/run.",
    )
    parser.add_argument(
        "--print-share-setup",
        choices=("sshfs",),
        default="",
        help="Print cluster-share setup commands for the selected mount backend and exit.",
    )
    parser.add_argument(
        "--setup-share",
        choices=("sshfs",),
        default="",
        help="Set up the shared cluster path using the selected backend.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute --setup-share changes. Without this flag setup commands are not applied.",
    )
    parser.add_argument(
        "--discover-lan",
        action="store_true",
        help="Discover candidate LAN cluster nodes and exit.",
    )
    parser.add_argument(
        "--cidr",
        default="",
        help="Comma-separated CIDRs to scan during --discover-lan. Defaults to local private /24 networks.",
    )
    parser.add_argument(
        "--passive-only",
        action="store_true",
        help="For --discover-lan, skip bounded TCP scanning and use passive sources only.",
    )
    parser.add_argument(
        "--discovery-timeout",
        type=float,
        default=0.35,
        help="TCP timeout in seconds for LAN discovery probes. Default: 0.35.",
    )
    parser.add_argument(
        "--ssh-probe-timeout",
        type=int,
        default=5,
        help="SSH BatchMode probe timeout in seconds for LAN discovery. Default: 5.",
    )
    parser.add_argument(
        "--discovery-limit",
        type=int,
        default=256,
        help="Maximum active LAN hosts to probe. Default: 256.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON for --discover-lan.",
    )
    parser.add_argument(
        "--no-discovery-cache",
        action="store_true",
        help="Do not read or write ~/.agilab/lan_nodes.json during --discover-lan.",
    )
    return parser


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.cluster and not args.discover_lan:
        parser.error("--cluster is required; this doctor currently validates cluster mode only")
    if args.cluster and not args.discover_lan and not args.scheduler:
        parser.error("--scheduler is required unless --discover-lan is used")
    if args.cluster and not args.discover_lan and not args.workers:
        parser.error("--workers is required unless --discover-lan is used")
    if args.rows_per_aircraft <= 0:
        parser.error("--rows-per-aircraft must be positive")
    if args.discovery_limit <= 0:
        parser.error("--discovery-limit must be positive")
    if args.discovery_timeout <= 0:
        parser.error("--discovery-timeout must be positive")
    if args.ssh_probe_timeout <= 0:
        parser.error("--ssh-probe-timeout must be positive")
    if args.cidr:
        try:
            parse_cidr_values(args.cidr)
        except ValueError as exc:
            parser.error(f"--cidr must contain valid CIDR values: {exc}")
    if not args.discover_lan and (
        args.cidr or args.passive_only or args.json or args.no_discovery_cache
    ):
        parser.error("LAN discovery options require --discover-lan")
    if args.discover_lan and (
        args.cluster
        or args.share_check_only
        or args.setup_share
        or args.print_share_setup
        or args.dry_run
    ):
        parser.error("--discover-lan cannot be combined with cluster validation or share setup modes")
    if args.share_check_only and args.dry_run:
        parser.error("--share-check-only cannot be combined with --dry-run")
    if args.share_check_only and args.print_share_setup:
        parser.error("--share-check-only cannot be combined with --print-share-setup")
    if args.apply and not args.setup_share:
        parser.error("--apply requires --setup-share")
    if args.setup_share and not args.apply:
        parser.error("--setup-share requires --apply; use --print-share-setup to preview")
    if args.setup_share and args.dry_run:
        parser.error("--setup-share cannot be combined with --dry-run")
    if args.setup_share and args.share_check_only:
        parser.error("--setup-share already runs the share check")
    if args.setup_share and args.print_share_setup:
        parser.error("--setup-share cannot be combined with --print-share-setup")
    return args


def parse_worker_specs(value: str) -> tuple[WorkerSpec, ...]:
    specs: list[WorkerSpec] = []
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue

        count = 1
        host_part = item
        left, sep, right = item.rpartition(":")
        if sep and right.isdigit() and left:
            host_part = left
            count = int(right)
        if count <= 0:
            raise ValueError(f"worker count must be positive: {item!r}")

        user = None
        host = host_part
        if "@" in host_part:
            user, host = host_part.split("@", 1)
            user = user.strip() or None
        host = host.strip()
        if not host:
            raise ValueError(f"worker host is missing: {item!r}")
        specs.append(WorkerSpec(host=host, count=count, user=user))

    if not specs:
        raise ValueError("--workers did not contain any usable worker")
    return tuple(specs)


def _parse_aircraft(value: str) -> tuple[int, ...]:
    aircraft: list[int] = []
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue
        plane = int(item)
        if plane < 0 or plane > 99:
            raise ValueError(f"aircraft IDs must be two-digit values: {item!r}")
        aircraft.append(plane)
    if not aircraft:
        raise ValueError("--aircraft did not contain any IDs")
    return tuple(aircraft)


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def _merged_agilab_env(home: Path, environ: Mapping[str, str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in (
        home / ".agilab" / ".env",
        home / ".local" / "share" / "agilab" / ".env",
    ):
        values.update(_read_dotenv(path))
    values.update({key: value for key, value in environ.items() if key.startswith("AGI")})
    return values


def _default_share_user(environ: Mapping[str, str]) -> str:
    user = environ.get("AGILAB_SHARE_USER") or environ.get("USER") or environ.get("USERNAME") or "user"
    cleaned = "".join(char if char.isalnum() or char in "_.-" else "_" for char in user).strip("_")
    return cleaned or "user"


def _resolve_path_setting(setting: str, *, home: Path) -> Path:
    path = Path(setting).expanduser()
    if not path.is_absolute():
        path = home / path
    return path.resolve(strict=False)


def _require_home_relative(path: Path, *, home: Path, label: str) -> Path:
    try:
        return path.resolve(strict=False).relative_to(home.resolve(strict=False))
    except ValueError as exc:
        raise ValueError(
            f"{label} must resolve under HOME for this Flight cluster validation. "
            f"Got {path}; pass --local-share localshare or another HOME-relative path."
        ) from exc


def build_workers_map(scheduler: str, specs: Sequence[WorkerSpec]) -> dict[str, int]:
    workers: dict[str, int] = {}
    for spec in specs:
        workers[spec.host] = workers.get(spec.host, 0) + spec.count
    return dict(sorted(workers.items()))


def resolve_remote_user(
    specs: Sequence[WorkerSpec],
    *,
    remote_user: str,
    environ: Mapping[str, str],
) -> str:
    users = {spec.user for spec in specs if spec.user}
    if len(users) > 1:
        raise ValueError(f"AGILAB supports one SSH user per validation run; got {sorted(users)}")
    if users:
        return next(iter(users)) or ""
    if remote_user.strip():
        return remote_user.strip()
    return environ.get("USER") or environ.get("USERNAME") or "agi"


def build_validation_plan(
    args: argparse.Namespace,
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> ValidationPlan:
    home = (home or Path.home()).resolve(strict=False)
    environ = environ or os.environ
    env_values = _merged_agilab_env(home, environ)
    specs = parse_worker_specs(args.workers)
    remote_user = resolve_remote_user(specs, remote_user=args.remote_user, environ=environ)
    local_share_setting = str(args.local_share or env_values.get("AGI_LOCAL_SHARE") or "localshare")
    local_cluster_share_setting = str(
        args.cluster_share
        or env_values.get("AGI_CLUSTER_SHARE")
        or f"clustershare/{_default_share_user(environ)}"
    )
    local_share_root = _resolve_path_setting(local_share_setting, home=home)
    dataset_rel = Path(args.dataset_rel)
    if dataset_rel.is_absolute():
        raise ValueError("--dataset-rel must be relative to --local-share")
    local_dataset_dir = (local_share_root / dataset_rel).resolve(strict=False)
    dataset_rel_to_home = _require_home_relative(
        local_dataset_dir,
        home=home,
        label="local dataset directory",
    )
    output_rel = Path(args.output_rel)
    if output_rel.is_absolute():
        raise ValueError("--output-rel must be relative to the cluster share")
    return ValidationPlan(
        app=args.app,
        apps_path=Path(args.apps_path).expanduser().resolve(strict=False),
        scheduler=args.scheduler,
        workers=build_workers_map(args.scheduler, specs),
        worker_specs=tuple(specs),
        remote_user=remote_user,
        local_share_setting=local_share_setting,
        local_cluster_share_setting=local_cluster_share_setting,
        remote_cluster_share_setting=str(args.remote_cluster_share or "clustershare"),
        local_dataset_dir=local_dataset_dir,
        dataset_rel_to_home=dataset_rel_to_home,
        output_rel=output_rel,
        aircraft=_parse_aircraft(args.aircraft),
        rows_per_aircraft=int(args.rows_per_aircraft),
        modes_enabled=int(args.modes_enabled),
    )


def write_synthetic_flight_dataset(
    dataset_dir: Path,
    *,
    aircraft: Sequence[int],
    rows_per_aircraft: int,
) -> tuple[Path, ...]:
    dataset_dir.mkdir(parents=True, exist_ok=True)
    for stale_csv in dataset_dir.glob("*.csv"):
        if stale_csv.is_file():
            stale_csv.unlink()
    written: list[Path] = []
    for plane in aircraft:
        output = dataset_dir / f"{plane:02d}_cluster_validation.csv"
        rows = ["aircraft,date,lat,long"]
        for index in range(rows_per_aircraft):
            minute = index % 60
            rows.append(
                f"{plane},2020-01-01 00:{minute:02d}:00,"
                f"{48.0 + (plane / 1000.0) + (index / 10000.0):.6f},"
                f"{2.0 + (plane / 1000.0) + (index / 10000.0):.6f}"
            )
        output.write_text("\n".join(rows) + "\n", encoding="utf-8")
        written.append(output)
    return tuple(written)


def local_share_root(plan: ValidationPlan, *, home: Path | None = None) -> Path:
    return _resolve_path_setting(plan.local_share_setting, home=(home or Path.home()))


def local_cluster_share_root(plan: ValidationPlan, *, home: Path | None = None) -> Path:
    return _resolve_path_setting(plan.local_cluster_share_setting, home=(home or Path.home()))


def _validate_distinct_cluster_share(plan: ValidationPlan, *, home: Path | None = None) -> None:
    local_root = local_share_root(plan, home=home)
    cluster_root = local_cluster_share_root(plan, home=home)
    if local_root == cluster_root:
        raise ValueError(
            "AGI_CLUSTER_SHARE must be distinct from AGI_LOCAL_SHARE for cluster validation. "
            f"Both resolve to {cluster_root}."
        )


def write_cluster_share_sentinel(
    plan: ValidationPlan,
    *,
    home: Path | None = None,
    token: str | None = None,
) -> tuple[Path, str]:
    _validate_distinct_cluster_share(plan, home=home)
    cluster_root = local_cluster_share_root(plan, home=home)
    marker_dir = cluster_root / SHARE_SENTINEL_DIR
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker_token = token or uuid.uuid4().hex
    marker_path = marker_dir / f"{marker_token}.json"
    marker_path.write_text(
        json.dumps(
            {
                "token": marker_token,
                "scheduler": plan.scheduler,
                "workers": plan.workers,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return marker_path, marker_token


def _is_local_host(host: str, *, scheduler: str) -> bool:
    normalized = host.strip().lower()
    if normalized == scheduler.strip().lower():
        return True
    local_names = {
        "127.0.0.1",
        "::1",
        "localhost",
        socket.gethostname().lower(),
        socket.getfqdn().lower(),
    }
    return normalized in local_names


def remote_worker_specs(plan: ValidationPlan) -> tuple[WorkerSpec, ...]:
    remote_specs: list[WorkerSpec] = []
    for spec in plan.worker_specs:
        if _is_local_host(spec.host, scheduler=plan.scheduler):
            continue
        remote_specs.append(
            WorkerSpec(host=spec.host, count=spec.count, user=spec.user or plan.remote_user)
        )
    return tuple(remote_specs)


def _run_command(argv: Sequence[str], *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        text=True,
        capture_output=True,
        check=True,
        timeout=timeout,
    )


def _ssh_target(spec: WorkerSpec, plan: ValidationPlan) -> str:
    user = spec.user or plan.remote_user
    return f"{user}@{spec.host}" if user else spec.host


def _ssh_argv(target: str, command: str) -> list[str]:
    return ["ssh", "-o", "BatchMode=yes", target, command]


def _remote_share_probe_script(plan: ValidationPlan, sentinel_rel: Path, token: str) -> str:
    return "\n".join(
        [
            "import json, os, sys",
            "from pathlib import Path",
            f"root_value = {json.dumps(plan.remote_cluster_share_setting)}",
            f"sentinel_rel = {json.dumps(sentinel_rel.as_posix())}",
            f"expected_token = {json.dumps(token)}",
            "root = Path(os.path.expanduser(root_value))",
            "if not root.is_absolute():",
            "    root = Path.home() / root",
            "path = root / sentinel_rel",
            "try:",
            "    payload = json.loads(path.read_text(encoding='utf-8'))",
            "except Exception as exc:",
            "    raise SystemExit(f'cluster share sentinel is not visible at {path}: {exc}')",
            "if payload.get('token') != expected_token:",
            "    raise SystemExit(f'cluster share sentinel token mismatch at {path}')",
            "print(str(path))",
        ]
    )


def validate_shared_cluster_share(plan: ValidationPlan, *, timeout: int) -> tuple[ShareProbeSummary, ...]:
    marker_path, token = write_cluster_share_sentinel(plan)
    sentinel_rel = marker_path.relative_to(local_cluster_share_root(plan))
    probes = [
        ShareProbeSummary(location="local", path=str(marker_path)),
    ]
    script = _remote_share_probe_script(plan, sentinel_rel, token)
    for spec in remote_worker_specs(plan):
        target = _ssh_target(spec, plan)
        command = "python3 - <<'PY'\n" + script + "\nPY"
        completed = _run_command(_ssh_argv(target, command), timeout=timeout)
        probes.append(
            ShareProbeSummary(
                location=target,
                path=(completed.stdout.strip().splitlines() or [""])[-1],
            )
        )
    return tuple(probes)


def _script_local_user(environ: Mapping[str, str] | None = None) -> str:
    environ = environ or os.environ
    return environ.get("USER") or environ.get("USERNAME") or "agi"


def _scheduler_ssh_target(plan: ValidationPlan, *, local_user: str | None = None) -> str:
    if "@" in plan.scheduler:
        return plan.scheduler
    return f"{local_user or _script_local_user()}@{plan.scheduler}"


def _remote_share_assignment(setting: str) -> str:
    cleaned = setting.strip() or "clustershare"
    if cleaned.startswith("~/"):
        return '"$HOME"/' + shlex.quote(cleaned[2:])
    if cleaned == "~":
        return '"$HOME"'
    if Path(cleaned).expanduser().is_absolute():
        return shlex.quote(str(Path(cleaned).expanduser()))
    return '"$HOME"/' + shlex.quote(cleaned)


def _workers_cli_value(plan: ValidationPlan) -> str:
    values: list[str] = []
    for spec in plan.worker_specs:
        user = spec.user or plan.remote_user
        host = f"{user}@{spec.host}" if user else spec.host
        values.append(f"{host}:{spec.count}" if spec.count != 1 else host)
    return ",".join(values)


def _share_check_command(plan: ValidationPlan) -> str:
    parts = [
        "agilab",
        "doctor",
        "--cluster",
        "--scheduler",
        plan.scheduler,
        "--workers",
        _workers_cli_value(plan),
        "--cluster-share",
        plan.local_cluster_share_setting,
        "--remote-cluster-share",
        plan.remote_cluster_share_setting,
        "--share-check-only",
    ]
    return " ".join(shlex.quote(part) for part in parts)


def _remote_env_update_script(plan: ValidationPlan) -> str:
    return "\n".join(
        [
            "from pathlib import Path",
            "key = 'AGI_CLUSTER_SHARE'",
            f"value = {json.dumps(plan.remote_cluster_share_setting)}",
            "env_path = Path.home() / '.agilab' / '.env'",
            "env_path.parent.mkdir(parents=True, exist_ok=True)",
            "lines = []",
            "if env_path.exists():",
            "    for raw_line in env_path.read_text(encoding='utf-8').splitlines():",
            "        if not raw_line.strip().startswith(key + '='):",
            "            lines.append(raw_line)",
            "lines.append(f'{key}={value!r}')",
            "env_path.write_text('\\n'.join(lines) + '\\n', encoding='utf-8')",
            "print(str(env_path))",
        ]
    )


def _remote_env_update_command(plan: ValidationPlan) -> str:
    return "python3 - <<'PY'\n" + _remote_env_update_script(plan) + "\nPY"


def _sshfs_options_args() -> str:
    return " ".join(f"-o {shlex.quote(option)}" for option in SSHFS_OPTIONS)


def _remote_share_unmount_snippet() -> str:
    return (
        "if command -v fusermount3 >/dev/null 2>&1; then "
        "fusermount3 -u \"$REMOTE_CLUSTER_SHARE\" || true; "
        "elif command -v fusermount >/dev/null 2>&1; then "
        "fusermount -u \"$REMOTE_CLUSTER_SHARE\" || true; "
        "else umount \"$REMOTE_CLUSTER_SHARE\" || true; fi"
    )


def _remote_share_setup_commands(
    plan: ValidationPlan,
    *,
    local_user: str | None = None,
) -> tuple[str, str, str]:
    local_root = local_cluster_share_root(plan)
    scheduler_target = _scheduler_ssh_target(plan, local_user=local_user)
    source = f"{scheduler_target}:{local_root.as_posix()}"
    remote_assignment = _remote_share_assignment(plan.remote_cluster_share_setting)
    sshfs_options = _sshfs_options_args()
    unmount_snippet = _remote_share_unmount_snippet()
    sshfs_check_command = (
        'mkdir -p "$HOME"/.agilab && '
        "if ! command -v sshfs >/dev/null 2>&1; then "
        f"printf '%s\\n' {shlex.quote(SSHFS_INSTALL_HINT)} >&2; exit 70; "
        "fi"
    )
    mkdir_command = (
        "REMOTE_CLUSTER_SHARE="
        + remote_assignment
        + '; mkdir -p "$REMOTE_CLUSTER_SHARE"'
    )
    mount_command = (
        f"SCHEDULER_CLUSTER_SHARE={shlex.quote(source)}; REMOTE_CLUSTER_SHARE="
        + remote_assignment
        + '; MOUNT_LINE=$(mount | grep -F -- "$REMOTE_CLUSTER_SHARE" || true); '
        + 'if [ -n "$MOUNT_LINE" ]; then '
        + 'if printf \'%s\\n\' "$MOUNT_LINE" | grep -F -- "$SCHEDULER_CLUSTER_SHARE" >/dev/null 2>&1 '
        + '&& test -d "$REMOTE_CLUSTER_SHARE" && test -w "$REMOTE_CLUSTER_SHARE"; then '
        + 'echo "already mounted: $REMOTE_CLUSTER_SHARE"; else '
        + 'echo "stale, unexpected, or unwritable SSHFS mount: $REMOTE_CLUSTER_SHARE; remounting" >&2; '
        + unmount_snippet
        + "; "
        + 'sshfs "$SCHEDULER_CLUSTER_SHARE" '
        + f'"$REMOTE_CLUSTER_SHARE" {sshfs_options}; fi; else '
        + 'sshfs "$SCHEDULER_CLUSTER_SHARE" '
        + f'"$REMOTE_CLUSTER_SHARE" {sshfs_options}; fi'
    )
    return sshfs_check_command, mkdir_command, mount_command


def share_setup_script_lines(
    plan: ValidationPlan,
    backend: str,
    *,
    local_user: str | None = None,
) -> tuple[str, ...]:
    if backend != "sshfs":
        raise ValueError(f"unsupported share setup backend: {backend}")

    local_root = local_cluster_share_root(plan)
    lines = [
        "# AGILAB cluster-share setup using SSHFS",
        "# Run these from the scheduler/manager host, then run the share check.",
        "# macOS workers need macFUSE + sshfs; Debian/Ubuntu workers need package sshfs.",
        "set -euo pipefail",
        f"mkdir -p {shlex.quote(str(local_root))}",
    ]
    for spec in remote_worker_specs(plan):
        target = _ssh_target(spec, plan)
        sshfs_check_command, mkdir_command, mount_command = _remote_share_setup_commands(
            plan,
            local_user=local_user,
        )
        lines.extend(
            [
                f"# Worker {target}",
                f"ssh {shlex.quote(target)} {shlex.quote(sshfs_check_command)}",
                f"ssh {shlex.quote(target)} {shlex.quote(_remote_env_update_command(plan))}",
                f"ssh {shlex.quote(target)} {shlex.quote(mkdir_command)}",
                f"ssh {shlex.quote(target)} {shlex.quote(mount_command)}",
            ]
        )
    lines.extend(
        [
            "# Validate without running Flight install/compute:",
            _share_check_command(plan),
        ]
    )
    return tuple(lines)


def apply_share_setup(
    plan: ValidationPlan,
    backend: str,
    *,
    timeout: int,
    local_user: str | None = None,
) -> tuple[ShareSetupSummary, ...]:
    if backend != "sshfs":
        raise ValueError(f"unsupported share setup backend: {backend}")

    _validate_distinct_cluster_share(plan)
    local_root = local_cluster_share_root(plan)
    local_root.mkdir(parents=True, exist_ok=True)
    summaries = [
        ShareSetupSummary(location="local", action="mkdir", path=str(local_root)),
    ]
    for spec in remote_worker_specs(plan):
        target = _ssh_target(spec, plan)
        sshfs_check_command, mkdir_command, mount_command = _remote_share_setup_commands(
            plan,
            local_user=local_user,
        )
        _run_command(_ssh_argv(target, sshfs_check_command), timeout=timeout)
        summaries.append(ShareSetupSummary(location=target, action="check-sshfs", path="sshfs"))
        completed = _run_command(_ssh_argv(target, _remote_env_update_command(plan)), timeout=timeout)
        env_path = (completed.stdout.strip().splitlines() or [""])[-1]
        summaries.append(ShareSetupSummary(location=target, action="write-env", path=env_path))
        _run_command(_ssh_argv(target, mkdir_command), timeout=timeout)
        summaries.append(
            ShareSetupSummary(
                location=target,
                action="mkdir",
                path=plan.remote_cluster_share_setting,
            )
        )
        completed = _run_command(_ssh_argv(target, mount_command), timeout=timeout)
        mount_output = (completed.stdout.strip().splitlines() or [plan.remote_cluster_share_setting])[-1]
        summaries.append(ShareSetupSummary(location=target, action="mount", path=mount_output))
    return tuple(summaries)


def sync_remote_inputs(
    plan: ValidationPlan,
    files: Sequence[Path],
    *,
    timeout: int,
) -> None:
    remote_dir = plan.dataset_rel_to_home.as_posix()
    for spec in remote_worker_specs(plan):
        target = _ssh_target(spec, plan)
        quoted_remote_dir = shlex.quote(remote_dir)
        mkdir_cmd = (
            f"mkdir -p \"$HOME\"/{quoted_remote_dir} && "
            f"rm -f \"$HOME\"/{quoted_remote_dir}/*.csv"
        )
        _run_command(_ssh_argv(target, mkdir_cmd), timeout=timeout)
        for file_path in files:
            destination = f"{target}:{remote_dir}/"
            _run_command(
                ["scp", "-q", "-o", "BatchMode=yes", str(file_path), destination],
                timeout=timeout,
            )
        cluster_share = plan.remote_cluster_share_setting
        if cluster_share:
            mkdir_share_cmd = f"mkdir -p {shlex.quote(cluster_share)}"
            _run_command(_ssh_argv(target, mkdir_share_cmd), timeout=timeout)


def _summarize_output_dir(path: Path, *, location: str) -> OutputSummary:
    parquet_files = tuple(sorted(item.name for item in path.glob("*.parquet"))) if path.is_dir() else ()
    reduce_artifacts = (
        tuple(sorted(item.name for item in path.glob("reduce_summary_worker_*.json")))
        if path.is_dir()
        else ()
    )
    row_count = 0
    aircraft: set[str] = set()
    if path.is_dir():
        for artifact in sorted(path.glob("reduce_summary_worker_*.json")):
            try:
                payload = json.loads(artifact.read_text(encoding="utf-8")).get("payload", {})
            except (OSError, json.JSONDecodeError):
                payload = {}
            try:
                row_count += int(payload.get("row_count", 0))
            except (TypeError, ValueError):
                pass
            aircraft.update(str(item) for item in payload.get("aircraft", []) if str(item))
    return OutputSummary(
        location=location,
        path=str(path),
        parquet_files=parquet_files,
        reduce_artifacts=reduce_artifacts,
        row_count=row_count,
        aircraft=tuple(sorted(aircraft)),
    )


def local_output_candidates(plan: ValidationPlan, *, home: Path | None = None) -> tuple[Path, ...]:
    home = (home or Path.home()).resolve(strict=False)
    roots = [
        _resolve_path_setting(plan.local_cluster_share_setting, home=home),
        home / "clustershare" / _default_share_user(os.environ),
        home / "clustershare",
    ]
    seen: set[Path] = set()
    candidates: list[Path] = []
    for root in roots:
        output = (root / plan.output_rel).resolve(strict=False)
        if output in seen:
            continue
        seen.add(output)
        candidates.append(output)
    return tuple(candidates)


def collect_local_outputs(plan: ValidationPlan, *, home: Path | None = None) -> tuple[OutputSummary, ...]:
    return tuple(
        _summarize_output_dir(candidate, location="local")
        for candidate in local_output_candidates(plan, home=home)
    )


def clean_local_outputs(plan: ValidationPlan, *, home: Path | None = None) -> None:
    for candidate in local_output_candidates(plan, home=home):
        shutil.rmtree(candidate, ignore_errors=True)


def _remote_probe_script(plan: ValidationPlan) -> str:
    roots = remote_output_root_settings(plan)
    return "\n".join(
        [
            "import json, os",
            "from pathlib import Path",
            f"roots = {json.dumps(roots)}",
            f"rel = {json.dumps(plan.output_rel.as_posix())}",
            "summaries = []",
            "for root in roots:",
            "    base = Path(os.path.expanduser(root))",
            "    if not base.is_absolute():",
            "        base = Path.home() / base",
            "    path = base / rel",
            "    parquet = sorted(item.name for item in path.glob('*.parquet')) if path.is_dir() else []",
            "    artifacts = sorted(item.name for item in path.glob('reduce_summary_worker_*.json')) if path.is_dir() else []",
            "    row_count = 0",
            "    aircraft = set()",
            "    if path.is_dir():",
            "        for item in sorted(path.glob('reduce_summary_worker_*.json')):",
            "            try:",
            "                payload = json.loads(item.read_text(encoding='utf-8')).get('payload', {})",
            "            except Exception:",
            "                payload = {}",
            "            try:",
            "                row_count += int(payload.get('row_count', 0))",
            "            except Exception:",
            "                pass",
            "            aircraft.update(str(value) for value in payload.get('aircraft', []) if str(value))",
            "    summaries.append({",
            "        'path': str(path),",
            "        'parquet_files': parquet,",
            "        'reduce_artifacts': artifacts,",
            "        'row_count': row_count,",
            "        'aircraft': sorted(aircraft),",
            "    })",
            "print(json.dumps(summaries, sort_keys=True))",
        ]
    )


def _remote_cleanup_script(plan: ValidationPlan) -> str:
    roots = remote_output_root_settings(plan)
    return "\n".join(
        [
            "import json, os, shutil",
            "from pathlib import Path",
            f"roots = {json.dumps(roots)}",
            f"rel = {json.dumps(plan.output_rel.as_posix())}",
            "for root in roots:",
            "    base = Path(os.path.expanduser(root))",
            "    if not base.is_absolute():",
            "        base = Path.home() / base",
            "    shutil.rmtree(base / rel, ignore_errors=True)",
        ]
    )


def remote_output_root_settings(plan: ValidationPlan) -> tuple[str, ...]:
    roots = [
        plan.remote_cluster_share_setting,
        "clustershare",
    ]
    if plan.remote_user:
        roots.append(f"clustershare/{plan.remote_user}")

    seen: set[str] = set()
    unique_roots: list[str] = []
    for root in roots:
        cleaned = str(root).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        unique_roots.append(cleaned)
    return tuple(unique_roots)


def clean_remote_outputs(plan: ValidationPlan, *, timeout: int) -> None:
    script = _remote_cleanup_script(plan)
    for spec in remote_worker_specs(plan):
        target = _ssh_target(spec, plan)
        command = "python3 - <<'PY'\n" + script + "\nPY"
        _run_command(_ssh_argv(target, command), timeout=timeout)


def clean_validation_outputs(plan: ValidationPlan, *, timeout: int) -> None:
    clean_local_outputs(plan)
    clean_remote_outputs(plan, timeout=timeout)


def collect_remote_outputs(plan: ValidationPlan, *, timeout: int) -> tuple[OutputSummary, ...]:
    summaries: list[OutputSummary] = []
    script = _remote_probe_script(plan)
    for spec in remote_worker_specs(plan):
        target = _ssh_target(spec, plan)
        command = "python3 - <<'PY'\n" + script + "\nPY"
        completed = _run_command(_ssh_argv(target, command), timeout=timeout)
        try:
            payload = json.loads(completed.stdout.strip() or "[]")
        except json.JSONDecodeError:
            payload = []
        for item in payload:
            summaries.append(
                OutputSummary(
                    location=target,
                    path=str(item.get("path", "")),
                    parquet_files=tuple(item.get("parquet_files", [])),
                    reduce_artifacts=tuple(item.get("reduce_artifacts", [])),
                    row_count=int(item.get("row_count", 0) or 0),
                    aircraft=tuple(item.get("aircraft", [])),
                )
            )
    return tuple(summaries)


def _request_params() -> dict[str, Any]:
    return {
        "data_source": "file",
        "files": "*.csv",
        "nfile": 0,
        "nskip": 0,
        "nread": 0,
        "sampling_rate": 1.0,
        "datemin": "2020-01-01",
        "datemax": "2021-01-01",
        "output_format": "parquet",
    }


def validation_success(
    output_summaries: Sequence[OutputSummary],
    remote_targets: Sequence[WorkerSpec],
) -> bool:
    local_output = any(
        summary.location == "local" and summary.has_result for summary in output_summaries
    )
    remote_output = any(
        summary.location != "local" and summary.has_result for summary in output_summaries
    )
    if remote_targets:
        return local_output and remote_output
    return local_output


def _configure_process_env(plan: ValidationPlan) -> None:
    os.environ["AGI_CLUSTER_ENABLED"] = "1"
    os.environ["AGI_LOCAL_SHARE"] = plan.local_share_setting
    os.environ["AGI_CLUSTER_SHARE"] = plan.local_cluster_share_setting


def _reset_agi_state(agi_cls: Any) -> None:
    for name, value in (
        ("_ssh_connections", {}),
        ("_dask_client", None),
        ("_dask_scheduler", None),
        ("_dask_workers", []),
        ("_service_workers", []),
        ("_jobs", None),
    ):
        try:
            setattr(agi_cls, name, value)
        except Exception:
            pass


async def run_cluster_validation(args: argparse.Namespace) -> dict[str, Any]:
    plan = build_validation_plan(args)
    _configure_process_env(plan)
    files = write_synthetic_flight_dataset(
        plan.local_dataset_dir,
        aircraft=plan.aircraft,
        rows_per_aircraft=plan.rows_per_aircraft,
    )
    clean_validation_outputs(plan, timeout=args.timeout)
    share_probes = validate_shared_cluster_share(plan, timeout=args.timeout)
    sync_remote_inputs(plan, files, timeout=args.timeout)

    from agi_cluster.agi_distributor import AGI, RunRequest
    from agi_env import AgiEnv

    try:
        AgiEnv.reset()
    except AttributeError:
        pass

    env = AgiEnv(apps_path=plan.apps_path, app=plan.app, verbose=args.verbose)
    env.user = plan.remote_user
    env.password = None
    if args.ssh_key:
        env.ssh_key_path = str(Path(args.ssh_key).expanduser())

    AGI._TIMEOUT = int(args.timeout)
    _reset_agi_state(AGI)
    await AGI.install(
        env=env,
        scheduler=plan.scheduler,
        workers=plan.workers,
        workers_data_path=plan.remote_cluster_share_setting,
        modes_enabled=plan.modes_enabled,
        verbose=args.verbose,
    )

    request = RunRequest(
        params=_request_params(),
        data_in=str(plan.local_dataset_dir),
        data_out=plan.output_rel.as_posix(),
        reset_target=True,
        scheduler=plan.scheduler,
        workers=plan.workers,
        workers_data_path=plan.remote_cluster_share_setting,
        verbose=args.verbose,
        mode=AGI.DASK_MODE,
    )
    run_result = await AGI.run(env, request=request)
    local_outputs = collect_local_outputs(plan)
    remote_outputs = collect_remote_outputs(plan, timeout=args.timeout)
    output_summaries = (*local_outputs, *remote_outputs)
    remote_targets = remote_worker_specs(plan)
    success = validation_success(output_summaries, remote_targets)
    return {
        "success": success,
        "plan": plan.to_dict(),
        "shared_cluster_share": [asdict(probe) for probe in share_probes],
        "written_inputs": [str(path) for path in files],
        "run_result": run_result,
        "outputs": [asdict(summary) for summary in output_summaries],
    }


def _print_plan(plan: ValidationPlan, files: Sequence[Path]) -> None:
    print("AGILAB Flight cluster validation plan")
    print(f"  scheduler: {plan.scheduler}")
    print(f"  workers: {plan.workers}")
    print(f"  ssh user: {plan.remote_user}")
    print(f"  local input: {plan.local_dataset_dir}")
    print(f"  remote input: $HOME/{plan.dataset_rel_to_home.as_posix()}")
    print(f"  local cluster share: {plan.local_cluster_share_setting}")
    print(f"  remote cluster share: {plan.remote_cluster_share_setting}")
    print(f"  output rel: {plan.output_rel.as_posix()}")
    print("  cluster share contract: remote workers must see the local sentinel and local must see outputs")
    if files:
        print("  synthetic inputs:")
        for file_path in files:
            print(f"    {file_path}")


def _print_share_probes(probes: Sequence[ShareProbeSummary]) -> None:
    print("AGILAB cluster-share preflight")
    for probe in probes:
        print(f"  ok: {probe.location} {probe.path}")


def _print_share_setup_summaries(summaries: Sequence[ShareSetupSummary]) -> None:
    print("AGILAB cluster-share setup")
    for summary in summaries:
        print(f"  ok: {summary.location} {summary.action} {summary.path}")


def _write_summary(path: str, payload: Mapping[str, Any]) -> None:
    if not path:
        return
    output = Path(path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, default=str, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _run_lan_discovery(args: argparse.Namespace) -> dict[str, Any]:
    options = DiscoveryOptions(
        cidrs=parse_cidr_values(args.cidr) if args.cidr else (),
        remote_user=args.remote_user,
        active=not args.passive_only,
        tcp_timeout=args.discovery_timeout,
        ssh_timeout=args.ssh_probe_timeout,
        max_hosts=args.discovery_limit,
        scheduler=args.scheduler,
        use_cache=not args.no_discovery_cache,
        cache_path=default_cache_path() if not args.no_discovery_cache else None,
    )
    report = discover_lan_nodes(options)
    payload = {"success": True, "lan_discovery": report.to_dict()}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_discovery_report(report)
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        if args.discover_lan:
            payload = _run_lan_discovery(args)
            _write_summary(args.summary_json, payload)
            return 0

        plan = build_validation_plan(args)
        _configure_process_env(plan)

        if args.print_share_setup:
            _print_plan(plan, ())
            print("\n".join(share_setup_script_lines(plan, args.print_share_setup)))
            _write_summary(
                args.summary_json,
                {
                    "success": True,
                    "setup_backend": args.print_share_setup,
                    "plan": plan.to_dict(),
                },
            )
            return 0

        if args.setup_share:
            _print_plan(plan, ())
            setup_summaries = apply_share_setup(
                plan,
                args.setup_share,
                timeout=args.timeout,
            )
            _print_share_setup_summaries(setup_summaries)
            probes = validate_shared_cluster_share(plan, timeout=args.timeout)
            _print_share_probes(probes)
            _write_summary(
                args.summary_json,
                {
                    "success": True,
                    "setup_backend": args.setup_share,
                    "setup_applied": True,
                    "plan": plan.to_dict(),
                    "share_setup": [asdict(summary) for summary in setup_summaries],
                    "shared_cluster_share": [asdict(probe) for probe in probes],
                },
            )
            return 0

        if args.share_check_only:
            _print_plan(plan, ())
            probes = validate_shared_cluster_share(plan, timeout=args.timeout)
            _print_share_probes(probes)
            _write_summary(
                args.summary_json,
                {
                    "success": True,
                    "share_check_only": True,
                    "plan": plan.to_dict(),
                    "shared_cluster_share": [asdict(probe) for probe in probes],
                },
            )
            return 0

        files = write_synthetic_flight_dataset(
            plan.local_dataset_dir,
            aircraft=plan.aircraft,
            rows_per_aircraft=plan.rows_per_aircraft,
        )
        _print_plan(plan, files)
        if args.dry_run:
            payload = {"success": True, "dry_run": True, "plan": plan.to_dict()}
            _write_summary(args.summary_json, payload)
            return 0

        payload = asyncio.run(run_cluster_validation(args))
        _write_summary(args.summary_json, payload)
        print("AGILAB Flight cluster validation outputs")
        for item in payload["outputs"]:
            marker = "ok" if item["parquet_files"] or item["reduce_artifacts"] else "missing"
            print(
                f"  {marker}: {item['location']} {item['path']} "
                f"parquet={len(item['parquet_files'])} reduce={len(item['reduce_artifacts'])} "
                f"rows={item['row_count']}"
            )
        return 0 if payload["success"] else 1
    except Exception as exc:
        print(f"agilab cluster doctor failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
