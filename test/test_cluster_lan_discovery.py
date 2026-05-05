from __future__ import annotations

import contextlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
while str(SRC_ROOT) in sys.path:
    sys.path.remove(str(SRC_ROOT))
sys.path.insert(0, str(SRC_ROOT))
loaded_agilab = sys.modules.get("agilab")
loaded_path = str(getattr(loaded_agilab, "__file__", ""))
if loaded_agilab is not None and not loaded_path.startswith(str(SRC_ROOT)):
    sys.modules.pop("agilab", None)

from agilab import cluster_flight_validation as cfv
from agilab import cluster_lan_discovery as discovery


def test_parse_cidr_values_rejects_invalid_network():
    assert discovery.parse_cidr_values(" ,192.168.3.0/24, 192.168.3.0/24") == ("192.168.3.0/24",)

    with pytest.raises(ValueError):
        discovery.parse_cidr_values("not-a-cidr")


def test_discover_lan_nodes_combines_sources_and_scores_nodes(tmp_path: Path):
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    (ssh_dir / "known_hosts").write_text(
        "# comment should be ignored\n"
        "192.168.3.35 ssh-ed25519 AAAA\n"
        "[192.168.3.36]:22 ssh-ed25519 BBBB\n"
        "macbook.local,*.example.com ssh-ed25519 CCCC\n"
        "@cert-authority *.example.com ssh-ed25519 DDDD\n"
        "|1|hashed|entry ssh-ed25519 EEEE\n",
        encoding="utf-8",
    )
    (ssh_dir / "config").write_text("Host\trtx2\n  HostName 192.168.3.35\nHost *\n", encoding="utf-8")

    def fake_runner(argv, **kwargs):
        command = list(argv)
        if command[:2] == ["arp", "-an"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="? (192.168.3.37) at aa:bb\n? (224.0.0.251) at multicast\n",
                stderr="",
            )
        if command[:1] == ["ifconfig"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="en0: flags\n\tinet 192.168.3.103 netmask 0xffffff00 broadcast 192.168.3.255\n",
                stderr="",
            )
        if command[:1] == ["ssh"]:
            target = command[-2]
            if target == "jpm@192.168.3.35":
                stdout = "\n".join(
                    [
                        "hostname=rtx2",
                        "os=Darwin",
                        "arch=x86_64",
                        "os_version=10.15.8",
                        "cpu=Intel Core i9; cores: 16",
                        "ram=64 GB",
                        "gpu=AMD Radeon Pro",
                        "npu=",
                        "python3=/usr/bin/python3",
                        "uv=/usr/local/bin/uv",
                        "sshfs=/usr/local/bin/sshfs",
                        "brew=",
                        "homebrew=/usr/local",
                        "reverse_ssh=yes",
                    ]
                )
                return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")
            if target == "jpm@192.168.3.36":
                stdout = "\n".join(
                    [
                        "hostname=mini",
                        "os=Darwin",
                        "arch=arm64",
                        "os_version=14.0",
                        "cpu=Apple M4 Max; cores: 16",
                        "ram=48 GB",
                        "gpu=Apple M4 Max",
                        "npu=Apple Neural Engine (16 cores)",
                        "python3=/usr/bin/python3",
                        "uv=/usr/local/bin/uv",
                        "sshfs=",
                        "brew=/opt/homebrew/bin/brew",
                    ]
                )
                return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")
            return subprocess.CompletedProcess(command, 255, stdout="", stderr="Permission denied")
        raise AssertionError(f"unexpected command: {command}")

    def fake_tcp(host: str, port: int, timeout: float) -> bool:
        assert port == 22
        assert timeout == 0.1
        return host in {"192.168.3.35", "192.168.3.36", "192.168.3.37"}

    report = discovery.discover_lan_nodes(
        discovery.DiscoveryOptions(
            cidrs=("192.168.3.32/30",),
            remote_user="jpm",
            tcp_timeout=0.1,
            scheduler="192.168.3.103",
            use_cache=True,
        ),
        home=tmp_path,
        environ={"USER": "agi"},
        runner=fake_runner,
        tcp_probe=fake_tcp,
    )

    statuses = {node.host: node.status for node in report.nodes}
    assert statuses["192.168.3.35"] == "ready"
    assert statuses["192.168.3.36"] == "sshfs-missing"
    assert statuses["192.168.3.37"] == "ssh-auth-needed"
    assert "224.0.0.251" not in statuses
    assert "*.example.com" not in statuses
    assert report.nodes[0].host == "192.168.3.35"
    assert "known-hosts" in report.nodes[0].sources
    cache = json.loads((tmp_path / ".agilab" / "lan_nodes.json").read_text(encoding="utf-8"))
    assert cache["cache_version"] == 1
    assert cache["nodes"][0]["status"] == "ready"
    assert cache["nodes"][0]["cpu"] == "Intel Core i9; cores: 16"
    assert cache["nodes"][0]["gpu"] == "AMD Radeon Pro"


def test_passive_cache_only_discovery_does_not_tcp_probe(tmp_path: Path):
    cache_path = tmp_path / ".agilab" / "lan_nodes.json"
    cache_path.parent.mkdir()
    cache_path.write_text(json.dumps({"nodes": [{"host": "192.168.3.55"}]}), encoding="utf-8")

    def fake_runner(argv, **kwargs):
        command = list(argv)
        if command[:1] == ["ifconfig"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="en0: flags\n\tinet 192.168.3.103 netmask 0xffffff00\n",
                stderr="",
            )
        if command[:2] == ["arp", "-an"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:1] == ["ssh"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="\n".join(
                    [
                        "hostname=cache-node",
                        "cpu=AMD EPYC; cores: 64",
                        "ram=256 GB",
                        "gpu=NVIDIA L40S (142 SMs)",
                        "npu=",
                        "python3=/usr/bin/python3",
                        "uv=/usr/local/bin/uv",
                        "sshfs=/usr/local/bin/sshfs",
                    ]
                ),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {command}")

    def fail_tcp(host: str, port: int, timeout: float) -> bool:
        raise AssertionError("passive cache-only discovery should not TCP probe")

    report = discovery.discover_lan_nodes(
        discovery.DiscoveryOptions(active=False, use_cache=True, cache_path=cache_path),
        home=tmp_path,
        runner=fake_runner,
        tcp_probe=fail_tcp,
    )

    assert report.nodes[0].host == "192.168.3.55"
    assert report.nodes[0].tcp_ssh_open is None
    assert report.nodes[0].status == "ready"
    assert report.nodes[0].gpu == "NVIDIA L40S (142 SMs)"


def test_local_ipv4_hosts_supports_ubuntu_without_ifconfig(monkeypatch):
    monkeypatch.setattr(discovery.socket, "gethostname", lambda: "ubuntu-worker")
    monkeypatch.setattr(discovery.socket, "getaddrinfo", lambda *_args, **_kwargs: [])

    def fake_runner(argv, **kwargs):
        command = list(argv)
        if command[:1] == ["ifconfig"]:
            return subprocess.CompletedProcess(command, 127, stdout="", stderr="ifconfig: not found")
        if command[:4] == ["ip", "route", "get", "1.1.1.1"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="1.1.1.1 via 192.168.20.1 dev eno1 src 192.168.20.15 uid 1000\n",
                stderr="",
            )
        if command[:6] == ["ip", "-4", "-o", "addr", "show", "scope"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    "2: eno1    inet 192.168.20.15/24 brd 192.168.20.255 scope global dynamic eno1\n"
                    "3: docker0 inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0\n"
                ),
                stderr="",
            )
        if command[:2] == ["hostname", "-I"]:
            return subprocess.CompletedProcess(command, 0, stdout="192.168.20.15 10.42.0.5\n", stderr="")
        raise AssertionError(f"unexpected command: {command}")

    hosts = discovery._local_ipv4_hosts(runner=fake_runner)

    assert hosts == {"192.168.20.15"}


def test_local_ipv4_hosts_supports_windows_ipconfig(monkeypatch):
    monkeypatch.setattr(discovery.socket, "gethostname", lambda: "windows-manager")
    monkeypatch.setattr(
        discovery.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, None, ("127.0.0.1", 0))],
    )
    commands: list[tuple[str, ...]] = []

    def fake_runner(argv, **kwargs):
        command = tuple(argv)
        commands.append(command)
        if command[:1] in {("ifconfig",), ("ip",)}:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="not found")
        if command[:1] == ("ipconfig",):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    "Windows IP Configuration\r\n\r\n"
                    "Ethernet adapter Ethernet:\r\n"
                    "   IPv4 Address. . . . . . . . . . . : 192.168.20.111(Preferred)\r\n"
                    "   Subnet Mask . . . . . . . . . . . : 255.255.255.0\r\n"
                    "   Default Gateway . . . . . . . . . : 192.168.20.1\r\n"
                ),
                stderr="",
            )
        if command[:1] in {("powershell",), ("pwsh",), ("hostname",)}:
            raise AssertionError(f"unexpected fallback after ipconfig success: {command}")
        raise AssertionError(f"unexpected command: {command}")

    hosts = discovery._local_ipv4_hosts(runner=fake_runner)

    assert hosts == {"192.168.20.111"}
    assert ("ipconfig",) in commands


def test_arp_candidates_supports_windows_arp_a():
    def fake_runner(argv, **kwargs):
        command = list(argv)
        if command[:2] == ["arp", "-an"]:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="invalid option")
        if command[:2] == ["arp", "-a"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    "Interface: 192.168.20.111 --- 0x7\r\n"
                    "  Internet Address      Physical Address      Type\r\n"
                    "  192.168.20.15         aa-bb-cc-dd-ee-ff     dynamic\r\n"
                    "  192.168.20.130        11-22-33-44-55-66     dynamic\r\n"
                ),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {command}")

    assert discovery._arp_candidates(fake_runner) == (
        ("192.168.20.15", "arp"),
        ("192.168.20.130", "arp"),
    )


def test_print_discovery_report_recommends_ready_workers(capsys):
    report = discovery.DiscoveryReport(
        generated_at=1.0,
        cidrs=("192.168.3.0/24",),
        local_hosts=("192.168.3.103",),
        nodes=(
            discovery.DiscoveryNode(
                host="192.168.3.35",
                ssh_target="jpm@192.168.3.35",
                sources=("known-hosts",),
                tcp_ssh_open=True,
                ssh_auth=True,
                status="ready",
                score=100,
                hostname="rtx2",
                os_name="Darwin",
                os_version="10.15.8",
                arch="x86_64",
                sshfs="/usr/local/bin/sshfs",
                uv="/usr/local/bin/uv",
            ),
        ),
    )

    discovery.print_discovery_report(report)

    output = capsys.readouterr().out
    assert "AGILAB LAN discovery" in output
    assert "ready: jpm@192.168.3.35" in output
    assert "--workers jpm@192.168.3.35" in output


def test_print_discovery_report_handles_empty_nodes(capsys):
    report = discovery.DiscoveryReport(generated_at=1.0, cidrs=(), local_hosts=(), nodes=())

    discovery.print_discovery_report(report)

    output = capsys.readouterr().out
    assert "cidrs: none" in output
    assert "local hosts: unknown" in output
    assert "nodes: none" in output


def test_probe_helpers_classify_missing_prerequisites_and_reverse_ssh():
    assert discovery._classify({}, tcp_open=True, reverse_ssh=None) == (
        "python-missing",
        50,
        ("python3 not found",),
    )
    assert discovery._classify({"python3": "/usr/bin/python3"}, tcp_open=True, reverse_ssh=None) == (
        "uv-missing",
        60,
        ("uv not found",),
    )
    assert discovery._classify(
        {"python3": "/usr/bin/python3", "uv": "/usr/local/bin/uv"},
        tcp_open=True,
        reverse_ssh=None,
    ) == ("sshfs-missing", 70, ("sshfs not found",))
    assert discovery._classify(
        {"python3": "python3", "uv": "uv", "sshfs": "sshfs"},
        tcp_open=True,
        reverse_ssh=False,
    ) == ("reverse-ssh-needed", 80, ("worker cannot ssh back to scheduler",))
    assert discovery._classify(
        {"python3": "python3", "uv": "uv", "sshfs": "sshfs"},
        tcp_open=False,
        reverse_ssh=True,
    ) == ("ready", 90, ())
    assert discovery._manager_ssh_target("", manager_user="agi") == ""
    assert discovery._manager_ssh_target("jpm@192.168.3.35", manager_user="agi") == "jpm@192.168.3.35"
    assert discovery._manager_ssh_target("192.168.3.35", manager_user="agi") == "agi@192.168.3.35"
    assert discovery._parse_key_value_lines("host = rtx\nignored\n=empty\nuv=/usr/local/bin/uv") == {
        "host": "rtx",
        "uv": "/usr/local/bin/uv",
    }
    assert discovery._parse_optional_bool("yes") is True
    assert discovery._parse_optional_bool("no") is False
    assert discovery._parse_optional_bool("") is None
    assert "reverse_ssh=" in discovery._remote_probe_command("agi@192.168.3.103")
    assert "gpu=%s" in discovery._remote_probe_command("agi@192.168.3.103")
    assert 'export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"' in discovery._remote_probe_command(
        "agi@192.168.3.103"
    )


def test_candidate_and_host_helpers_handle_edge_cases(tmp_path: Path, monkeypatch):
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    (ssh_dir / "config").write_text(
        "Host *.example.com\nHost old-mac\nHost ?wild\n",
        encoding="utf-8",
    )
    (ssh_dir / "known_hosts").write_text(
        "host1,host2:2222 ssh-ed25519 AAAA\n"
        "@cert-authority host3 ssh-ed25519 BBBB\n"
        "[192.168.3.44]:22 ssh-ed25519 CCCC\n"
        "# ignored\n"
        "|1|hashed|entry ssh-ed25519 DDDD\n",
        encoding="utf-8",
    )
    invalid_cache = tmp_path / "invalid.json"
    invalid_cache.write_text("{", encoding="utf-8")

    assert discovery._ssh_config_candidates(tmp_path) == (("old-mac", "ssh-config"),)
    assert discovery._known_hosts_candidates(tmp_path) == (
        ("host1", "known-hosts"),
        ("host2", "known-hosts"),
        ("192.168.3.44", "known-hosts"),
    )
    assert discovery._cache_candidates(tmp_path / "missing.json") == ()
    assert discovery._cache_candidates(invalid_cache) == ()
    assert discovery._normalize_host("[old-mac.local.]") == "old-mac.local"
    assert discovery._normalize_known_host("[192.168.3.44]:22") == "192.168.3.44"
    assert discovery._normalize_known_host("host.example.com:2222") == "host.example.com"
    assert discovery._is_unusable_host("localhost") is True
    assert discovery._is_unusable_host("224.0.0.251") is True
    assert discovery._is_unusable_host("fe80::1") is True
    assert discovery._is_unusable_host("192.168.3.35") is False

    monkeypatch.setattr(discovery.socket, "gethostname", lambda: "manager.local")
    monkeypatch.setattr(discovery.socket, "getfqdn", lambda: "manager.example.com")
    aliases = discovery._local_host_aliases({"192.168.3.103"})
    assert {"manager", "manager.local", "manager.example.com"} <= aliases


def test_active_ssh_hosts_limits_hosts_and_ignores_probe_exceptions():
    seen = []

    def fake_tcp(host: str, port: int, timeout: float) -> bool:
        seen.append(host)
        if host.endswith(".1"):
            raise OSError("probe failed")
        return host.endswith(".2")

    hosts = discovery._active_ssh_hosts(
        ("192.168.3.0/29",),
        port=22,
        timeout=0.01,
        max_hosts=2,
        tcp_probe=fake_tcp,
    )

    assert sorted(seen) == ["192.168.3.1", "192.168.3.2"]
    assert hosts == ("192.168.3.2",)


def test_tcp_connect_reports_success_and_oserror(monkeypatch):
    @contextlib.contextmanager
    def fake_connection(address, timeout):
        assert address == ("192.168.3.35", 22)
        assert timeout == 0.1
        yield object()

    monkeypatch.setattr(discovery.socket, "create_connection", fake_connection)
    assert discovery._tcp_connect("192.168.3.35", 22, 0.1) is True

    def fail_connection(address, timeout):
        raise OSError("closed")

    monkeypatch.setattr(discovery.socket, "create_connection", fail_connection)
    assert discovery._tcp_connect("192.168.3.35", 22, 0.1) is False


def test_default_cidrs_and_local_ipv4_hosts_handle_runner_failures(monkeypatch):
    monkeypatch.setattr(
        discovery.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (None, None, None, None, ("127.0.0.1", 0)),
            (None, None, None, None, ("192.168.3.103", 0)),
        ],
    )

    def failing_runner(argv, **kwargs):
        raise OSError("ifconfig unavailable")

    hosts = discovery._local_ipv4_hosts(runner=failing_runner)

    assert hosts == {"192.168.3.103"}
    assert discovery._default_cidrs({"169.254.35.190", "192.168.3.103", "not-an-ip"}) == (
        "192.168.3.0/24",
    )


def test_main_discover_lan_writes_json_summary(tmp_path: Path, monkeypatch, capsys):
    report = discovery.DiscoveryReport(
        generated_at=1.0,
        cidrs=("192.168.3.0/24",),
        local_hosts=("192.168.3.103",),
        nodes=(),
    )
    summary = tmp_path / "lan.json"

    def fake_discover(options):
        assert options.remote_user == "jpm"
        assert options.active is False
        assert options.use_cache is False
        return report

    def fail_plan(*args, **kwargs):
        raise AssertionError("discovery should not require a cluster validation plan")

    monkeypatch.setattr(cfv, "discover_lan_nodes", fake_discover)
    monkeypatch.setattr(cfv, "build_validation_plan", fail_plan)

    rc = cfv.main(
        [
            "--discover-lan",
            "--remote-user",
            "jpm",
            "--passive-only",
            "--no-discovery-cache",
            "--json",
            "--summary-json",
            str(summary),
        ]
    )

    output = json.loads(capsys.readouterr().out)
    payload = json.loads(summary.read_text(encoding="utf-8"))
    assert rc == 0
    assert output["success"] is True
    assert payload["lan_discovery"]["cidrs"] == ["192.168.3.0/24"]
