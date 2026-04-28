"""LAN node discovery helpers for AGILAB cluster preflight."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


Runner = Callable[..., subprocess.CompletedProcess[str]]
TcpProbe = Callable[[str, int, float], bool]

DEFAULT_DISCOVERY_PORT = 22
DEFAULT_TCP_TIMEOUT = 0.35
DEFAULT_SSH_TIMEOUT = 5
DEFAULT_MAX_HOSTS = 256
CACHE_VERSION = 1


@dataclass(frozen=True)
class DiscoveryOptions:
    cidrs: tuple[str, ...] = ()
    remote_user: str = ""
    active: bool = True
    port: int = DEFAULT_DISCOVERY_PORT
    tcp_timeout: float = DEFAULT_TCP_TIMEOUT
    ssh_timeout: int = DEFAULT_SSH_TIMEOUT
    max_hosts: int = DEFAULT_MAX_HOSTS
    scheduler: str = ""
    manager_user: str = ""
    use_cache: bool = True
    cache_path: Path | None = None


@dataclass(frozen=True)
class DiscoveryNode:
    host: str
    ssh_target: str
    sources: tuple[str, ...]
    tcp_ssh_open: bool | None
    ssh_auth: bool
    status: str
    score: int
    hostname: str = ""
    os_name: str = ""
    os_version: str = ""
    arch: str = ""
    python3: str = ""
    uv: str = ""
    brew: str = ""
    homebrew: str = ""
    sshfs: str = ""
    cpu: str = ""
    ram: str = ""
    gpu: str = ""
    npu: str = ""
    reverse_ssh: bool | None = None
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DiscoveryReport:
    generated_at: float
    cidrs: tuple[str, ...]
    local_hosts: tuple[str, ...]
    nodes: tuple[DiscoveryNode, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "cidrs": self.cidrs,
            "local_hosts": self.local_hosts,
            "nodes": [node.to_dict() for node in self.nodes],
        }


def parse_cidr_values(value: str) -> tuple[str, ...]:
    cidrs: list[str] = []
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue
        ipaddress.ip_network(item, strict=False)
        cidrs.append(item)
    return tuple(dict.fromkeys(cidrs))


def default_cache_path(home: Path | None = None) -> Path:
    root = home or Path.home()
    return root / ".agilab" / "lan_nodes.json"


def discover_lan_nodes(
    options: DiscoveryOptions,
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
    runner: Runner | None = None,
    tcp_probe: TcpProbe | None = None,
) -> DiscoveryReport:
    home = home or Path.home()
    environ = environ or os.environ
    runner = runner or _run_text
    tcp_probe = tcp_probe or _tcp_connect

    local_hosts = _local_ipv4_hosts(runner=runner)
    local_aliases = _local_host_aliases(local_hosts)
    cidrs = options.cidrs or _default_cidrs(local_hosts)
    candidates: dict[str, set[str]] = {}

    def add(host: str, source: str) -> None:
        normalized = _normalize_host(host)
        if not normalized or _is_unusable_host(normalized):
            return
        if normalized in local_hosts or normalized.lower() in local_aliases:
            return
        candidates.setdefault(normalized, set()).add(source)

    for host, source in _ssh_config_candidates(home):
        add(host, source)
    for host, source in _known_hosts_candidates(home):
        add(host, source)
    for host, source in _arp_candidates(runner):
        add(host, source)
    if options.use_cache:
        for host, source in _cache_candidates(options.cache_path or default_cache_path(home)):
            add(host, source)

    if options.active:
        for host in _active_ssh_hosts(
            cidrs,
            port=options.port,
            timeout=options.tcp_timeout,
            max_hosts=options.max_hosts,
            tcp_probe=tcp_probe,
        ):
            add(host, "tcp-scan")

    nodes: list[DiscoveryNode] = []
    for host in sorted(candidates, key=_host_sort_key):
        sources = tuple(sorted(candidates[host]))
        tcp_open: bool | None = None
        if options.active or sources != ("cache",):
            tcp_open = tcp_probe(host, options.port, options.tcp_timeout)
        nodes.append(
            _probe_node(
                host,
                sources,
                options=options,
                local_hosts=local_hosts,
                environ=environ,
                runner=runner,
                tcp_open=tcp_open,
            )
        )

    report = DiscoveryReport(
        generated_at=time.time(),
        cidrs=tuple(cidrs),
        local_hosts=tuple(sorted(local_hosts, key=_host_sort_key)),
        nodes=tuple(sorted(nodes, key=lambda node: (-node.score, _host_sort_key(node.host)))),
    )
    if options.use_cache:
        _write_cache(options.cache_path or default_cache_path(home), report)
    return report


def print_discovery_report(report: DiscoveryReport) -> None:
    print("AGILAB LAN discovery")
    print(f"  cidrs: {', '.join(report.cidrs) if report.cidrs else 'none'}")
    print(f"  local hosts: {', '.join(report.local_hosts) if report.local_hosts else 'unknown'}")
    if not report.nodes:
        print("  nodes: none")
        return

    print("  nodes:")
    for node in report.nodes:
        detail = _node_detail(node)
        print(f"    {node.status}: {node.ssh_target} ({detail})")

    ready = [node for node in report.nodes if node.status == "ready"]
    if ready:
        workers = ",".join(node.ssh_target for node in ready)
        print("  next:")
        print(f"    --workers {workers}")
        print("    run --share-check-only after cluster-share setup")


def _node_detail(node: DiscoveryNode) -> str:
    parts = [f"score={node.score}", f"sources={','.join(node.sources)}"]
    if node.hostname:
        parts.append(f"host={node.hostname}")
    if node.os_name:
        os_label = f"{node.os_name} {node.os_version}".strip()
        parts.append(f"os={os_label}")
    if node.arch:
        parts.append(f"arch={node.arch}")
    if node.gpu:
        parts.append(f"gpu={node.gpu}")
    if node.sshfs:
        parts.append(f"sshfs={node.sshfs}")
    if node.uv:
        parts.append(f"uv={node.uv}")
    if node.errors:
        parts.append(f"error={node.errors[0]}")
    return "; ".join(parts)


def _probe_node(
    host: str,
    sources: tuple[str, ...],
    *,
    options: DiscoveryOptions,
    local_hosts: set[str],
    environ: Mapping[str, str],
    runner: Runner,
    tcp_open: bool | None,
) -> DiscoveryNode:
    ssh_target = f"{options.remote_user}@{host}" if options.remote_user else host
    if tcp_open is False:
        return _node(
            host,
            ssh_target,
            sources,
            tcp_open,
            ssh_auth=False,
            status="no-ssh-port",
            errors=("ssh port closed or timed out",),
        )

    manager_target = _manager_ssh_target(
        options.scheduler,
        manager_user=options.manager_user or _local_user(environ),
    )
    command = _remote_probe_command(manager_target)
    completed = runner(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={max(1, int(options.ssh_timeout))}",
            ssh_target,
            command,
        ],
        capture_output=True,
        text=True,
        timeout=options.ssh_timeout,
    )
    if completed.returncode != 0:
        error = (completed.stderr or completed.stdout or "ssh authentication failed").strip()
        return _node(
            host,
            ssh_target,
            sources,
            tcp_open,
            ssh_auth=False,
            status="ssh-auth-needed",
            errors=(_first_line(error),),
        )

    values = _parse_key_value_lines(completed.stdout)
    reverse = _parse_optional_bool(values.get("reverse_ssh", ""))
    status, score, errors = _classify(values, tcp_open=tcp_open, reverse_ssh=reverse)
    return DiscoveryNode(
        host=host,
        ssh_target=ssh_target,
        sources=sources,
        tcp_ssh_open=tcp_open,
        ssh_auth=True,
        status=status,
        score=score,
        hostname=values.get("hostname", ""),
        os_name=values.get("os", ""),
        os_version=values.get("os_version", ""),
        arch=values.get("arch", ""),
        python3=values.get("python3", ""),
        uv=values.get("uv", ""),
        brew=values.get("brew", ""),
        homebrew=values.get("homebrew", ""),
        sshfs=values.get("sshfs", ""),
        cpu=values.get("cpu", ""),
        ram=values.get("ram", ""),
        gpu=values.get("gpu", ""),
        npu=values.get("npu", ""),
        reverse_ssh=reverse,
        errors=errors,
    )


def _node(
    host: str,
    ssh_target: str,
    sources: tuple[str, ...],
    tcp_open: bool | None,
    *,
    ssh_auth: bool,
    status: str,
    errors: tuple[str, ...] = (),
) -> DiscoveryNode:
    score = {
        "ready": 100,
        "reverse-ssh-needed": 80,
        "sshfs-missing": 70,
        "uv-missing": 60,
        "python-missing": 50,
        "ssh-auth-needed": 30,
        "no-ssh-port": 0,
    }.get(status, 10)
    return DiscoveryNode(
        host=host,
        ssh_target=ssh_target,
        sources=sources,
        tcp_ssh_open=tcp_open,
        ssh_auth=ssh_auth,
        status=status,
        score=score,
        errors=errors,
    )


def _classify(
    values: Mapping[str, str],
    *,
    tcp_open: bool | None,
    reverse_ssh: bool | None,
) -> tuple[str, int, tuple[str, ...]]:
    if not values.get("python3"):
        return "python-missing", 50, ("python3 not found",)
    if not values.get("uv"):
        return "uv-missing", 60, ("uv not found",)
    if not values.get("sshfs"):
        return "sshfs-missing", 70, ("sshfs not found",)
    if reverse_ssh is False:
        return "reverse-ssh-needed", 80, ("worker cannot ssh back to scheduler",)
    score = 100 if tcp_open is not False else 90
    return "ready", score, ()


def _remote_probe_command(manager_target: str) -> str:
    lines = [
        'printf "hostname=%s\\n" "$(hostname 2>/dev/null || true)"',
        'printf "os=%s\\n" "$(uname -s 2>/dev/null || true)"',
        'printf "arch=%s\\n" "$(uname -m 2>/dev/null || true)"',
        'printf "os_version=%s\\n" "$(sw_vers -productVersion 2>/dev/null || uname -r 2>/dev/null || true)"',
        "cpu=''; "
        "if command -v lscpu >/dev/null 2>&1; then cpu=\"$(lscpu 2>/dev/null | awk -F: '/Model name/ {sub(/^[ \\t]+/, \"\", $2); print $2; exit}')\"; fi; "
        "if [ -z \"$cpu\" ] && [ -r /proc/cpuinfo ]; then cpu=\"$(awk -F: '/model name/ {sub(/^[ \\t]+/, \"\", $2); print $2; exit}' /proc/cpuinfo)\"; fi; "
        "if [ -z \"$cpu\" ] && command -v sysctl >/dev/null 2>&1; then cpu=\"$(sysctl -n machdep.cpu.brand_string 2>/dev/null || true)\"; fi; "
        "if [ -z \"$cpu\" ]; then cpu=\"$(uname -m 2>/dev/null || true)\"; fi; "
        "cores=\"$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || true)\"; "
        "if [ -n \"$cores\" ]; then cpu=\"$cpu; cores: $cores\"; fi; "
        'printf "cpu=%s\\n" "$cpu"',
        "ram=''; "
        "if [ -r /proc/meminfo ]; then ram=\"$(awk '/MemTotal/ {printf \"%.0f GB\", ($2 * 1024) / (1024 * 1024 * 1024)}' /proc/meminfo)\"; fi; "
        "if [ -z \"$ram\" ] && command -v sysctl >/dev/null 2>&1; then ram_bytes=\"$(sysctl -n hw.memsize 2>/dev/null || true)\"; "
        "if [ -n \"$ram_bytes\" ]; then ram=\"$(awk -v b=\"$ram_bytes\" 'BEGIN {printf \"%.0f GB\", b / (1024 * 1024 * 1024)}')\"; fi; fi; "
        'printf "ram=%s\\n" "$ram"',
        "gpu=''; "
        "if command -v nvidia-smi >/dev/null 2>&1; then gpu=\"$(nvidia-smi --query-gpu=name,multiprocessor_count --format=csv,noheader,nounits 2>/dev/null | awk -F, '{gsub(/^[ \\t]+|[ \\t]+$/, \"\", $1); gsub(/^[ \\t]+|[ \\t]+$/, \"\", $2); if ($2 != \"\") print $1 \" (\" $2 \" SMs)\"; else print $1}' | paste -sd ';' -)\"; fi; "
        "if [ -z \"$gpu\" ] && command -v system_profiler >/dev/null 2>&1; then gpu=\"$(system_profiler SPDisplaysDataType 2>/dev/null | awk -F: '/Chipset Model/ {gsub(/^[ \\t]+/, \"\", $2); print $2; exit}')\"; fi; "
        'printf "gpu=%s\\n" "$gpu"',
        "npu=''; chip=''; "
        "if command -v system_profiler >/dev/null 2>&1; then chip=\"$(system_profiler SPHardwareDataType 2>/dev/null | awk -F: '/Chip/ {gsub(/^[ \\t]+/, \"\", $2); print $2; exit}')\"; fi; "
        "case \"$chip\" in Apple\\ M*) npu='Apple Neural Engine (16 cores)' ;; esac; "
        'printf "npu=%s\\n" "$npu"',
        'printf "python3=%s\\n" "$(command -v python3 2>/dev/null || true)"',
        'printf "uv=%s\\n" "$(command -v uv 2>/dev/null || true)"',
        'printf "sshfs=%s\\n" "$(command -v sshfs 2>/dev/null || true)"',
        'printf "brew=%s\\n" "$(command -v brew 2>/dev/null || true)"',
        'printf "homebrew=%s\\n" "$(/usr/local/Homebrew/bin/brew --prefix 2>/dev/null || true)"',
    ]
    if manager_target:
        quoted = _shell_quote(manager_target)
        lines.append(
            'printf "reverse_ssh="; '
            f"ssh -o BatchMode=yes -o ConnectTimeout=3 {quoted} hostname >/dev/null 2>&1 "
            '&& echo yes || echo no'
        )
    return "; ".join(lines)


def _manager_ssh_target(scheduler: str, *, manager_user: str) -> str:
    cleaned = scheduler.strip()
    if not cleaned:
        return ""
    if "@" in cleaned:
        return cleaned
    return f"{manager_user}@{cleaned}" if manager_user else cleaned


def _parse_key_value_lines(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in output.splitlines():
        key, sep, value = line.partition("=")
        if sep and key:
            values[key.strip()] = value.strip()
    return values


def _parse_optional_bool(value: str) -> bool | None:
    if value == "yes":
        return True
    if value == "no":
        return False
    return None


def _active_ssh_hosts(
    cidrs: Sequence[str],
    *,
    port: int,
    timeout: float,
    max_hosts: int,
    tcp_probe: TcpProbe,
) -> tuple[str, ...]:
    hosts: list[str] = []
    for cidr in cidrs:
        network = ipaddress.ip_network(cidr, strict=False)
        for ip in network.hosts():
            if len(hosts) >= max_hosts:
                break
            hosts.append(str(ip))
        if len(hosts) >= max_hosts:
            break
    if not hosts:
        return ()

    found: list[str] = []
    workers = min(64, max(1, len(hosts)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(tcp_probe, host, port, timeout): host for host in hosts}
        for future in as_completed(futures):
            host = futures[future]
            try:
                if future.result():
                    found.append(host)
            except Exception:
                continue
    return tuple(sorted(found, key=_host_sort_key))


def _tcp_connect(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _run_text(argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(argv), **kwargs)


def _local_ipv4_hosts(*, runner: Runner) -> set[str]:
    hosts: set[str] = set()
    try:
        hostname = socket.gethostname()
        for item in socket.getaddrinfo(hostname, None, family=socket.AF_INET):
            hosts.add(item[4][0])
    except OSError:
        pass

    try:
        completed = runner(["ifconfig"], capture_output=True, text=True, timeout=2)
    except Exception:
        completed = subprocess.CompletedProcess(["ifconfig"], 1, stdout="", stderr="")
    if completed.returncode == 0:
        for match in re.finditer(r"\binet\s+(\d+\.\d+\.\d+\.\d+)\s+netmask\s+(0x[0-9a-fA-F]+)", completed.stdout):
            hosts.add(match.group(1))
    return {host for host in hosts if not host.startswith("127.")}


def _default_cidrs(local_hosts: set[str]) -> tuple[str, ...]:
    cidrs: list[str] = []
    for host in sorted(local_hosts, key=_host_sort_key):
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            continue
        if address.is_private and not address.is_link_local:
            network = ipaddress.ip_network(f"{host}/24", strict=False)
            cidrs.append(str(network))
    return tuple(dict.fromkeys(cidrs))


def _ssh_config_candidates(home: Path) -> tuple[tuple[str, str], ...]:
    path = home / ".ssh" / "config"
    if not path.exists():
        return ()
    candidates: list[tuple[str, str]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split(None, 1)
        if len(parts) != 2:
            continue
        key, value = parts
        if key.lower() != "host":
            continue
        for token in value.split():
            if any(char in token for char in "*?!"):
                continue
            candidates.append((token, "ssh-config"))
    return tuple(candidates)


def _known_hosts_candidates(home: Path) -> tuple[tuple[str, str], ...]:
    path = home / ".ssh" / "known_hosts"
    if not path.exists():
        return ()
    candidates: list[tuple[str, str]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("|") or stripped.startswith("#"):
            continue
        fields = stripped.split()
        if not fields:
            continue
        if fields[0].startswith("@"):
            continue
        host_field = fields[0]
        for host in host_field.split(","):
            normalized = _normalize_known_host(host)
            if normalized and not any(char in normalized for char in "*?!"):
                candidates.append((normalized, "known-hosts"))
    return tuple(candidates)


def _arp_candidates(runner: Runner) -> tuple[tuple[str, str], ...]:
    try:
        completed = runner(["arp", "-an"], capture_output=True, text=True, timeout=2)
    except Exception:
        return ()
    if completed.returncode != 0:
        return ()
    return tuple((match.group(1), "arp") for match in re.finditer(r"\((\d+\.\d+\.\d+\.\d+)\)", completed.stdout))


def _cache_candidates(path: Path) -> tuple[tuple[str, str], ...]:
    if not path.exists():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    nodes = payload.get("nodes", [])
    candidates: list[tuple[str, str]] = []
    if isinstance(nodes, list):
        for item in nodes:
            if isinstance(item, dict) and isinstance(item.get("host"), str):
                candidates.append((item["host"], "cache"))
    return tuple(candidates)


def _write_cache(path: Path, report: DiscoveryReport) -> None:
    payload = report.to_dict()
    payload["cache_version"] = CACHE_VERSION
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        print(f"warning: could not write LAN discovery cache: {path}", file=sys.stderr)


def _normalize_known_host(value: str) -> str:
    if value.startswith("[") and "]:" in value:
        return value[1:].split("]:", 1)[0]
    if ":" in value and not _looks_ipv6(value):
        return value.split(":", 1)[0]
    return value


def _normalize_host(value: str) -> str:
    cleaned = value.strip().strip("[]")
    if cleaned.endswith(".local."):
        cleaned = cleaned[:-1]
    return cleaned


def _is_unusable_host(host: str) -> bool:
    if host.startswith("#") or any(char.isspace() for char in host):
        return True
    if host in {"localhost", "0.0.0.0"}:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return _looks_ipv6(host)
    if address.is_loopback or address.is_multicast or address.is_unspecified:
        return True
    return _looks_ipv6(host)


def _local_host_aliases(local_hosts: set[str]) -> set[str]:
    aliases = {host.lower() for host in local_hosts}
    for value in (socket.gethostname(), socket.getfqdn()):
        cleaned = value.strip().lower()
        if not cleaned:
            continue
        aliases.add(cleaned)
        short = cleaned.split(".", 1)[0]
        aliases.add(short)
        aliases.add(f"{short}.local")
    return aliases


def _looks_ipv6(value: str) -> bool:
    return value.count(":") >= 2


def _host_sort_key(host: str) -> tuple[int, Any]:
    try:
        return (0, ipaddress.ip_address(host))
    except ValueError:
        return (1, host)


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _first_line(value: str) -> str:
    return (value.splitlines() or [""])[0][:240]


def _local_user(environ: Mapping[str, str]) -> str:
    return environ.get("USER") or environ.get("USERNAME") or ""
