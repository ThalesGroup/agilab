import ast
import json
import os
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

import tomli_w


def sanitize_for_toml(obj):
    """Recursively convert values into TOML-safe structures."""
    if isinstance(obj, dict):
        sanitized = {}
        for key, value in obj.items():
            if value is None:
                continue
            sanitized_value = sanitize_for_toml(value)
            if sanitized_value is None:
                continue
            sanitized[key] = sanitized_value
        return sanitized
    if isinstance(obj, list):
        sanitized_items = []
        for item in obj:
            if item is None:
                continue
            sanitized_item = sanitize_for_toml(item)
            if sanitized_item is None:
                continue
            sanitized_items.append(sanitized_item)
        return sanitized_items
    if isinstance(obj, tuple):
        return sanitize_for_toml(list(obj))
    if isinstance(obj, Path):
        return str(obj)
    return obj


def write_app_settings_toml(settings_path: Path, payload: dict) -> dict:
    """Persist ``payload`` after converting it to a TOML-serializable object."""
    sanitized = sanitize_for_toml(payload)
    with open(settings_path, "wb") as file:
        tomli_w.dump(sanitized, file)
    return sanitized


SHARED_FILESYSTEM_TYPES: set[str] = {
    "nfs",
    "nfs4",
    "cifs",
    "smbfs",
    "sshfs",
    "afpfs",
    "webdav",
    "lustre",
    "gpfs",
    "panfs",
    "beegfs",
    "ceph",
    "glusterfs",
    "gfs2",
    "autofs",
}


@lru_cache(maxsize=1)
def mount_table() -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    try:
        if sys.platform.startswith("linux"):
            mounts = Path("/proc/mounts")
            if mounts.exists():
                for line in mounts.read_text(encoding="utf-8", errors="replace").splitlines():
                    parts = line.split()
                    if len(parts) >= 3:
                        mountpoint = parts[1].replace("\\040", " ")
                        fstype = parts[2]
                        entries.append((mountpoint, fstype))
        elif sys.platform == "darwin":
            proc = subprocess.run(["mount"], capture_output=True, text=True, check=False)
            for line in (proc.stdout or "").splitlines():
                match = re.match(r".+ on (?P<mountpoint>.+?) \((?P<fstype>[^,\)]+)", line)
                if match:
                    entries.append((match.group("mountpoint").strip(), match.group("fstype").strip()))
    except Exception:
        entries = []

    entries.sort(key=lambda item: len(item[0]), reverse=True)
    return entries


def fstype_for_path(path: Path) -> Optional[str]:
    path_str = str(path)
    for mountpoint, fstype in mount_table():
        normalized_mountpoint = mountpoint.rstrip("/") or "/"
        if normalized_mountpoint == "/":
            return fstype.lower()
        if path_str == normalized_mountpoint or path_str.startswith(normalized_mountpoint + "/"):
            return fstype.lower()
    return None


def looks_like_shared_path(path: Path, *, project_root: Path) -> bool:
    """Best-effort heuristic for whether a path looks like shared storage."""
    raw = path.expanduser()
    try:
        resolved = raw.resolve()
    except Exception:
        resolved = raw

    for candidate in (raw, resolved):
        fstype = fstype_for_path(candidate)
        if fstype and fstype in SHARED_FILESYSTEM_TYPES:
            return True

    home_raw = Path.home().expanduser()
    home = Path.home().resolve()
    try:
        resolved.relative_to(home)
        for current, stop in ((raw, home_raw), (resolved, home)):
            node = current
            while True:
                try:
                    if os.path.ismount(node):
                        return True
                except Exception:
                    break
                if node == stop:
                    break
                parent = node.parent
                if parent == node:
                    break
                node = parent
        return False
    except ValueError:
        pass

    try:
        resolved.relative_to(project_root)
        return False
    except ValueError:
        pass

    return resolved.is_absolute()


def macos_autofs_hint(share_candidate: Path) -> Optional[str]:
    """Return a short hint when a macOS autofs map seems misconfigured."""
    if sys.platform != "darwin":
        return None

    share_candidate = share_candidate.expanduser()
    candidate_str = str(share_candidate)
    if not (candidate_str.startswith("/mnt/") or candidate_str.startswith("/Volumes/")):
        return None

    auto_master = Path("/etc/auto_master")
    auto_nfs = Path("/etc/auto_nfs")
    if not auto_master.exists():
        return (
            "macOS detected a path under `/mnt`, but `/etc/auto_master` was not found. "
            "If this share is served through autofs, ensure `/mnt` is declared there and run `sudo automount -vc`."
        )

    try:
        master_text = auto_master.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    has_mnt_map = re.search(r"^\s*/mnt\s+auto_nfs(\s|$)", master_text, flags=re.MULTILINE) is not None
    has_direct_ref = re.search(r"^\s*/-\s+auto_nfs(\s|$)", master_text, flags=re.MULTILINE) is not None
    if not has_mnt_map and not has_direct_ref:
        has_static = re.search(r"^\s*/-\s+-static(\s|$)", master_text, flags=re.MULTILINE) is not None
        if has_static:
            return (
                "macOS only honors the first `/-` entry (duplicates are ignored), so replace `/- -static` with `/- auto_nfs` "
                "in `/etc/auto_master`, then run `sudo automount -vc`."
            )
        return (
            "macOS autofs does not advertise `/mnt` or `/- auto_nfs`. Add one of these entries to `/etc/auto_master` "
            "and reload it with `sudo automount -vc` before using worker shares."
        )

    if auto_nfs.exists():
        try:
            nfs_text = auto_nfs.read_text(encoding="utf-8", errors="replace")
        except Exception:
            nfs_text = ""
        if candidate_str.startswith("/mnt/"):
            mount_root = "/mnt"
        elif candidate_str.startswith("/Volumes/"):
            mount_root = "/Volumes"
        else:
            mount_root = None
        if mount_root and mount_root not in nfs_text:
            return (
                f"`{auto_nfs}` exists but does not mention `{mount_root}`. Verify the map entry for `{share_candidate}` "
                "and run `sudo automount -vc`."
            )
    return None


def parse_benchmark(benchmark_str):
    """Parse a benchmark string into a dictionary."""
    if not isinstance(benchmark_str, str):
        raise ValueError("Input must be a string.")
    if len(benchmark_str) < 3:
        return None

    try:
        json_str = re.sub(r'([{,]\s*)(\d+):', r'\1"\2":', benchmark_str)
        json_str = json_str.replace("'", '"')
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid benchmark string. Failed to decode JSON.") from exc

    def try_int(key):
        return int(key) if key.isdigit() else key

    return {try_int(k): v for k, v in data.items()}


def extract_result_dict_from_output(raw_output: str) -> Optional[dict]:
    """Best-effort parse of the printed AGI result dictionary."""
    if not raw_output:
        return None
    for line in reversed(raw_output.splitlines()):
        candidate = line.strip()
        if not candidate or not candidate.startswith("{") or not candidate.endswith("}"):
            continue
        try:
            parsed = ast.literal_eval(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def coerce_bool_setting(raw_value, default: bool) -> bool:
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, (int, float)):
        return bool(raw_value)
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def coerce_int_setting(raw_value, default: int, *, minimum: int = 0) -> int:
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default
    return max(value, minimum)


def coerce_float_setting(
    raw_value,
    default: float,
    *,
    minimum: float = 0.0,
    maximum: float = 1.0,
) -> float:
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return default
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def evaluate_service_health_gate(
    payload: dict,
    *,
    allow_idle: bool,
    max_unhealthy: int,
    max_restart_rate: float,
) -> tuple[int, str, dict]:
    status = str(payload.get("status", "unknown") or "unknown").lower()
    unhealthy = coerce_int_setting(payload.get("workers_unhealthy_count"), 0, minimum=0)
    running = coerce_int_setting(payload.get("workers_running_count"), 0, minimum=0)
    restarted = coerce_int_setting(payload.get("workers_restarted_count"), 0, minimum=0)
    restart_rate = (float(restarted) / float(running)) if running > 0 else 0.0
    details = {
        "status": status,
        "workers_unhealthy_count": unhealthy,
        "workers_running_count": running,
        "workers_restarted_count": restarted,
        "restart_rate": restart_rate,
    }
    if unhealthy > max_unhealthy:
        return 2, f"unhealthy workers {unhealthy} exceeds limit {max_unhealthy}", details
    if status in {"error", "degraded"}:
        return 3, f"service status is {status}", details
    if status == "idle" and not allow_idle:
        return 4, "service status is idle (set 'Allow idle status' to accept)", details
    if restart_rate > max_restart_rate:
        return 5, f"restart rate {restart_rate:.3f} exceeds limit {max_restart_rate:.3f}", details
    return 0, "ok", details


def safe_eval(
    expression,
    expected_type,
    error_message,
    *,
    on_error: Callable[[str], None],
):
    try:
        result = ast.literal_eval(expression)
        if not isinstance(result, expected_type):
            on_error(error_message)
            return None
        return result
    except (SyntaxError, ValueError):
        on_error(error_message)
        return None


def parse_and_validate_scheduler(
    scheduler,
    *,
    is_valid_ip: Callable[[str], bool],
    on_error: Callable[[str], None],
):
    """Accept IP or IP:PORT. Validate IP via is_valid_ip(host) and optional numeric port."""
    host, sep, port = scheduler.partition(":")
    if not is_valid_ip(host):
        on_error(f"The scheduler host '{scheduler}' is invalid. Expect IP or IP:PORT.")
        return None
    if sep and (not port.isdigit() or not (0 < int(port) < 65536)):
        on_error(f"The scheduler port in '{scheduler}' is invalid.")
        return None
    return scheduler


def parse_and_validate_workers(
    workers_input,
    *,
    is_valid_ip: Callable[[str], bool],
    on_error: Callable[[str], None],
    default_workers: Optional[dict] = None,
):
    fallback_workers = default_workers or {"127.0.0.1": 1}
    workers = safe_eval(
        expression=workers_input,
        expected_type=dict,
        error_message="Workers must be provided as a dictionary of IP addresses and capacities (e.g., {'192.168.0.1': 2}).",
        on_error=on_error,
    )
    if workers is not None:
        invalid_ips = [ip for ip in workers.keys() if not is_valid_ip(ip)]
        if invalid_ips:
            on_error(f"The following worker IPs are invalid: {', '.join(invalid_ips)}")
            return fallback_workers
        invalid_values = {ip: num for ip, num in workers.items() if not isinstance(num, int) or num <= 0}
        if invalid_values:
            error_details = ", ".join([f"{ip}: {num}" for ip, num in invalid_values.items()])
            on_error(f"All worker capacities must be positive integers. Invalid entries: {error_details}")
            return fallback_workers
    return workers or fallback_workers
