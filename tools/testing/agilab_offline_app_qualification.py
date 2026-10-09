#!/usr/bin/env python3
"""Qualify explicit app checks offline using preinstalled runtimes and pinned sources.

Manifests and outputs may describe private apps: keep them outside public source
trees. A passed check proves its declared scope, not every function of an app.
This tool installs nothing and runs argv directly without a shell.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

SCHEMA = "agilab.offline_app_qualification_manifest.v1"
DENY_ALL = "(version 1)(allow default)(deny network*)"
LOOPBACK = (
    DENY_ALL + '(allow network-outbound (remote ip "localhost:*"))'
    '(allow network-inbound (local ip "localhost:*"))'
    '(allow network-bind (local ip "localhost:*"))'
    "(allow network* (local unix-socket))(allow network* (remote unix-socket))"
)
LAYERS = {"science", "web", "notebook"}
CONTROL = r"""
import json,socket,subprocess,sys,tempfile,threading
def denied():
 s=socket.socket();s.settimeout(1)
 try:s.connect(('198.51.100.1',9))
 except OSError as e:return e.errno
 finally:s.close()
 raise AssertionError('external connection was allowed')
assert denied()==1
child=subprocess.run([sys.executable,'-c',"import socket; s=socket.socket();\ntry:s.connect(('198.51.100.1',9))\nexcept OSError as e:assert e.errno==1\nelse:raise AssertionError('child network allowed')"],capture_output=True,text=True,timeout=5)
assert child.returncode==0,child.stderr
mode=sys.argv[1]
if mode=='loopback':
 listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1)
 client=socket.socket();client.settimeout(2);client.connect(listener.getsockname())
 peer,_=listener.accept();peer.close();client.close();listener.close()
 with tempfile.TemporaryDirectory(prefix='agilab-offline-ipc-control-') as directory:
  listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);listener.bind(directory+'/socket');listener.listen(1)
  client=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);client.connect(directory+'/socket')
  peer,_=listener.accept();peer.close();client.close();listener.close()
 local='allowed'
else:
 client=socket.socket()
 try:client.connect(('127.0.0.1',9))
 except OSError as e:assert e.errno==1
 else:raise AssertionError('loopback unexpectedly allowed')
 finally:client.close()
 local='denied'
print(json.dumps({'external_errno':1,'child_external_errno':1,'loopback':local}))
"""


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def regular_file(path: Path) -> Path:
    require(
        path.is_file() and not path.is_symlink(),
        "Expected a regular file: " + str(path),
    )
    return path


def read_manifest(path: Path, *, content: bytes | None = None) -> dict:
    value = json.loads(regular_file(path).read_bytes() if content is None else content)
    require(value.get("schema") == SCHEMA, "Unsupported manifest schema")
    require(
        isinstance(value.get("sources"), list) and value["sources"],
        "Missing source pins",
    )
    require(
        isinstance(value.get("checks"), list) and value["checks"],
        "Missing explicit checks",
    )
    for source in value["sources"]:
        require(
            bool(re.fullmatch(r"[0-9a-f]{40}", source.get("revision", ""))),
            "Invalid source revision",
        )
        require(
            Path(source.get("root", "")).is_absolute(), "Source root must be absolute"
        )
        require(
            isinstance(source.get("paths"), list) and source["paths"],
            "Missing source scope",
        )
        for name in source["paths"]:
            require(
                isinstance(name, str)
                and name
                and not Path(name).is_absolute()
                and ".." not in Path(name).parts,
                "Unsafe source path",
            )
    seen = set()
    for check in value["checks"]:
        name = check.get("id", "")
        require(
            bool(re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,95}", name)) and name not in seen,
            "Invalid or duplicate check id",
        )
        seen.add(name)
        require(
            check.get("layer") in LAYERS
            and bool(check.get("app"))
            and bool(check.get("scope")),
            "Missing app/layer/scope",
        )
        require(
            isinstance(check.get("argv"), list)
            and check["argv"]
            and all(isinstance(x, str) and x for x in check["argv"]),
            "Invalid argv",
        )
        require(Path(check.get("cwd", "")).is_absolute(), "Check cwd must be absolute")
        require(
            isinstance(check.get("timeout", 180), int)
            and 1 <= check.get("timeout", 180) <= 1800,
            "Invalid timeout",
        )
        require(
            check.get("network", "deny_all") in {"deny_all", "loopback"},
            "Unsupported network profile",
        )
        require(
            isinstance(check.get("env", {}), dict)
            and all(
                isinstance(k, str) and isinstance(v, str)
                for k, v in check.get("env", {}).items()
            ),
            "Invalid environment",
        )
    return value


def bytecode_source(root: Path, path: Path) -> str:
    try:
        return (
            Path(importlib.util.source_from_cache(str(path)))
            .relative_to(root)
            .as_posix()
        )
    except ValueError:
        pytest_cache = re.fullmatch(
            r"(.+)\.(?:cpython|pypy)-\d+-pytest-\d+(?:\.\d+){1,2}\.pyc", path.name
        )
        return (
            (path.parent.parent / (pytest_cache[1] + ".py"))
            .relative_to(root)
            .as_posix()
            if pytest_cache
            else ""
        )


def source_snapshot(sources: list[dict]) -> list[dict]:
    results = []
    for source in sources:
        root = Path(source["root"]).resolve()
        command = ["git", "-C", str(root)]
        head = subprocess.check_output(
            [*command, "rev-parse", "HEAD"], text=True
        ).strip()
        require(head == source["revision"], "Source HEAD drift: " + str(root))
        changed = subprocess.run(
            [*command, "diff", "--quiet", "HEAD", "--", *source["paths"]], check=False
        )
        require(changed.returncode == 0, "Source scope is dirty: " + str(root))
        paths = subprocess.check_output(
            [*command, "ls-files", "-z", "--", *source["paths"]]
        ).split(b"\0")
        tracked = {os.fsdecode(entry) for entry in paths if entry}
        cache_files = {}
        # File pathspecs omit sibling caches from Git's untracked enumeration.
        # Discover caches for every selected Python source independently.
        cache_directories = {
            (root / name).parent / "__pycache__"
            for name in tracked
            if Path(name).suffix == ".py"
        }
        for directory in sorted(cache_directories):
            if not directory.exists():
                continue
            require(
                not directory.is_symlink() and directory.resolve().is_relative_to(root),
                "Source cache escapes root",
            )
            for path in sorted(directory.glob("*.pyc")):
                if bytecode_source(root, path) in tracked:
                    regular_file(path)
                    cache_files[path.relative_to(root).as_posix()] = {
                        "sha256": digest(path),
                        "size": path.stat().st_size,
                    }
        untracked = subprocess.check_output(
            [*command, "ls-files", "--others", "-z", "--", *source["paths"]]
        ).split(b"\0")
        for encoded in (entry for entry in untracked if entry):
            name = os.fsdecode(encoded)
            parts = Path(name).parts
            path = root / name
            if path.suffix == ".pyc" and path.parent.name == "__pycache__":
                origin = bytecode_source(root, path)
                require(
                    origin in tracked,
                    "Untracked input has no pinned bytecode source: " + name,
                )
                regular_file(path)
                cache_files[name] = {
                    "sha256": digest(path),
                    "size": path.stat().st_size,
                }
                continue
            executable_suffixes = {
                ".py",
                ".pyi",
                ".pyc",
                ".pyo",
                ".js",
                ".mjs",
                ".cjs",
                ".ts",
                ".tsx",
                ".jsx",
                ".sh",
                ".bash",
                ".zsh",
                ".r",
                ".rb",
                ".pl",
                ".so",
                ".dylib",
                ".dll",
                ".wasm",
                ".jar",
                ".class",
                ".ipynb",
            }
            metadata_cache = any(
                part in {".pytest_cache", ".mypy_cache", ".ruff_cache"}
                for part in parts
            )
            metadata_cache = (
                metadata_cache
                and path.suffix.lower() not in executable_suffixes
                and not path.stat().st_mode & 0o111
            )
            egg_metadata = any(
                part.endswith(".egg-info") for part in parts
            ) and path.name in {
                "PKG-INFO",
                "SOURCES.txt",
                "requires.txt",
                "top_level.txt",
                "dependency_links.txt",
                "entry_points.txt",
                "not-zip-safe",
            }
            require(
                metadata_cache or egg_metadata or path.name == "uv.lock",
                "Untracked input inside revision-pinned source scope: " + name,
            )
        files = {}
        for encoded in sorted(x for x in paths if x):
            name = os.fsdecode(encoded)
            path = regular_file(root / name)
            require(path.resolve().is_relative_to(root), "Source file escapes root")
            files[name] = {"sha256": digest(path), "size": path.stat().st_size}
        require(bool(files), "Source pin contains no tracked files")
        results.append(
            {
                "root": str(root),
                "revision": head,
                "paths": source["paths"],
                "files": files,
                "generated_bytecode_inputs": cache_files,
            }
        )
    return results


def output_path(output: Path, name: str) -> Path:
    candidate = output / name
    require(
        not Path(name).is_absolute()
        and ".." not in Path(name).parts
        and candidate.resolve().is_relative_to(output.resolve()),
        "Artifact path escapes output",
    )
    return candidate


class ProcessInfo(ctypes.Structure):
    """Metadata-only macOS proc_bsdinfo; no process arguments are collected."""

    _fields_ = [
        (name, ctypes.c_uint32)
        for name in (
            "flags",
            "status",
            "xstatus",
            "pid",
            "ppid",
            "uid",
            "gid",
            "ruid",
            "rgid",
            "svuid",
            "svgid",
            "reserved",
        )
    ]
    _fields_ += [("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32)]
    _fields_ += [
        (name, ctypes.c_uint32)
        for name in ("nfiles", "pgid", "jobc", "tdev", "tpgid", "nice")
    ]
    _fields_ += [
        ("start_seconds", ctypes.c_uint64),
        ("start_microseconds", ctypes.c_uint64),
    ]


class OwnedProcesses:
    """Observe child parentage and bind every cleanup target to its start time."""

    def __init__(self, pid: int):
        self.library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        self.library.proc_pidinfo.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        self.library.proc_pidinfo.restype = ctypes.c_int
        self.library.proc_listchildpids.argtypes = [
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        self.library.proc_listchildpids.restype = ctypes.c_int
        self.owned = {}
        info = self.info(pid)
        require(info is not None, "Could not identify the launched process")
        self.owned[pid] = self.identity(info)

    @staticmethod
    def identity(info):
        return (info.start_seconds, info.start_microseconds)

    def info(self, pid):
        value = ProcessInfo()
        for attempt in range(20):
            size = self.library.proc_pidinfo(
                pid, 3, 0, ctypes.byref(value), ctypes.sizeof(value)
            )
            if size == ctypes.sizeof(value):
                return value
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return None
            probe = subprocess.run(
                ["/bin/ps", "-o", "stat=", "-p", str(pid)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if probe.stdout.strip().startswith("Z") or (
                probe.returncode == 1 and not probe.stdout.strip()
            ):
                return None
            # BSD metadata can briefly be unavailable while an owned child execs.
            time.sleep(0.001)
        raise OSError(
            f"Could not verify owned process PID {pid}; errno={ctypes.get_errno()}; state={probe.stdout.strip()}"
        )

    def observe(self):
        pending = list(self.owned)
        visited = set()
        while pending:
            pid = pending.pop()
            if pid in visited:
                continue
            visited.add(pid)
            info = self.info(pid)
            if (
                info is None
                or self.identity(info) != self.owned[pid]
                or info.status == 5
            ):
                continue
            children = (ctypes.c_int * 4096)()
            count = self.library.proc_listchildpids(
                pid, children, ctypes.sizeof(children)
            )
            require(
                0 <= count < len(children), "Could not enumerate owned process children"
            )
            for child_pid in children[:count]:
                child = self.info(child_pid)
                if child is not None and child.ppid == pid:
                    identity = self.identity(child)
                    if child_pid not in self.owned:
                        self.owned[child_pid] = identity
                    require(
                        self.owned[child_pid] == identity,
                        "Owned process PID changed identity",
                    )
                    pending.append(child_pid)

    def live(self):
        rows = []
        for pid, identity in self.owned.items():
            info = self.info(pid)
            if (
                info is not None
                and self.identity(info) == identity
                and info.status != 5
            ):
                rows.append(pid)
        return rows

    def stop(self):
        self.observe()
        for sig, grace in ((signal.SIGTERM, 0.2), (signal.SIGKILL, 2.0)):
            for pid in self.live():
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    pass
            deadline = time.monotonic() + grace
            while self.live() and time.monotonic() < deadline:
                self.observe()
                time.sleep(0.001)
        require(not self.live(), "Live owned descendants remain after cleanup")
        return {
            "status": "passed",
            "observed_process_count": len(self.owned),
            "method": "macOS parentage polling with PID and microsecond start-time binding",
            "unobserved_descendant_containment": False,
        }


def execute(
    argv: list[str], *, cwd: str, env: dict, timeout: int, stdout: Path, stderr: Path
) -> dict:
    started = time.monotonic()
    with stdout.open("xb") as out, stderr.open("xb") as err:
        process = subprocess.Popen(
            argv, cwd=cwd, env=env, stdout=out, stderr=err, start_new_session=True
        )
        owned = None
        try:
            owned = OwnedProcesses(process.pid)
            deadline = started + timeout
            while True:
                owned.observe()
                code = process.poll()
                timed_out = code is None and time.monotonic() >= deadline
                if code is not None or timed_out:
                    break
                time.sleep(0.001)
        finally:
            try:
                if owned is None:
                    cleanup = {
                        "status": "failed",
                        "reason": "process_identity_unavailable",
                    }
                else:
                    cleanup = owned.stop()
            finally:
                if process.poll() is None:
                    process.kill()
                code = process.wait(timeout=5)
    return {
        "exit_code": code,
        "timed_out": timed_out,
        "duration_seconds": round(time.monotonic() - started, 3),
        "process_cleanup": cleanup,
        "stdout": {
            "path": stdout.name,
            "sha256": digest(stdout),
            "size": stdout.stat().st_size,
        },
        "stderr": {
            "path": stderr.name,
            "sha256": digest(stderr),
            "size": stderr.stat().st_size,
        },
    }


def junit_summary(path: Path) -> dict:
    root = ET.parse(regular_file(path)).getroot()
    cases = list(root.iter("testcase"))
    counts = {"tests": len(cases), "failed": 0, "errors": 0, "skipped": 0, "passed": 0}
    for case in cases:
        kind = next(
            (
                name
                for name in ("failure", "error", "skipped")
                if case.find(name) is not None
            ),
            None,
        )
        counts[
            {"failure": "failed", "error": "errors", "skipped": "skipped"}.get(
                kind, "passed"
            )
        ] += 1
    return counts


def run(manifest_path: Path, output: Path) -> dict:
    harness_sha256 = digest(Path(__file__))
    manifest_bytes = regular_file(manifest_path).read_bytes()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    manifest = read_manifest(manifest_path, content=manifest_bytes)
    require(
        platform.system() == "Darwin" and Path("/usr/bin/sandbox-exec").is_file(),
        "This network-enforced backend requires macOS sandbox-exec",
    )
    require(not output.exists(), "Refusing to reuse an existing evidence directory")
    before = source_snapshot(manifest["sources"])
    output.mkdir(parents=True)
    controls = {}
    results = []
    for check in manifest["checks"]:
        name, mode = check["id"], check.get("network", "deny_all")
        env = dict(os.environ)
        env.update(check.get("env", {}))
        env.update(
            {
                "AGI_INTERNET_ON": "0",
                "UV_OFFLINE": "1",
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "OPENBLAS_NUM_THREADS": "1",
                "OMP_NUM_THREADS": "1",
                "POLARS_MAX_THREADS": "2",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        profile = LOOPBACK if mode == "loopback" else DENY_ALL
        prefix = ["/usr/bin/sandbox-exec", "-p", profile]
        python = check.get("control_python", sys.executable)
        require(
            Path(python).is_absolute() and Path(python).is_file(),
            "Missing control Python",
        )
        if (python, mode) not in controls:
            probe = subprocess.run(
                [*prefix, python, "-c", CONTROL, mode],
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
            controls[(python, mode)] = {
                "python": python,
                "mode": mode,
                "profile": profile,
                "profile_sha256": hashlib.sha256(profile.encode()).hexdigest(),
                "observed": json.loads(probe.stdout),
            }
        print(
            json.dumps(
                {
                    "check": name,
                    "app": check["app"],
                    "layer": check["layer"],
                    "status": "started",
                }
            ),
            flush=True,
        )
        argv = [arg.replace("{output}", str(output)) for arg in check["argv"]]
        outcome = execute(
            [*prefix, *argv],
            cwd=check["cwd"],
            env=env,
            timeout=check.get("timeout", 180),
            stdout=output / name_with_role(name, "stdout.log"),
            stderr=output / name_with_role(name, "stderr.log"),
        )
        item = {
            "id": name,
            "app": check["app"],
            "layer": check["layer"],
            "scope": check["scope"],
            "argv": argv,
            "cwd": check["cwd"],
            "network": mode,
            **outcome,
            "status": "failed"
            if outcome["exit_code"] != 0 or outcome["timed_out"]
            else "passed",
        }
        error_text = "\n".join(
            (output / outcome[key]["path"]).read_text(errors="replace")
            for key in ("stdout", "stderr")
        )
        if item["status"] == "failed" and re.search(
            r"ModuleNotFoundError: No module named", error_text
        ):
            item["status"], item["reason"] = "blocked", "missing_preinstalled_module"
        if item["status"] == "passed":
            try:
                if check.get("junit"):
                    counts = junit_summary(output_path(output, check["junit"]))
                    item["junit"] = counts
                    if counts["failed"] or counts["errors"]:
                        item["status"], item["reason"] = (
                            "failed",
                            "reported_test_failures",
                        )
                    elif not counts["passed"]:
                        item["status"], item["reason"] = (
                            "blocked",
                            "no_passing_executed_tests",
                        )
                if check.get("json_evidence"):
                    evidence_path = output_path(output, check["json_evidence"])
                    evidence = json.loads(regular_file(evidence_path).read_text())
                    require(
                        evidence.get("status") == "passed",
                        "Check JSON evidence did not pass",
                    )
                    item["json_evidence"] = {
                        "path": check["json_evidence"],
                        "sha256": digest(evidence_path),
                    }
                item["artifacts"] = []
                for artifact in check.get("artifacts", []):
                    path = regular_file(output_path(output, artifact))
                    item["artifacts"].append(
                        {
                            "path": artifact,
                            "sha256": digest(path),
                            "size": path.stat().st_size,
                        }
                    )
            except (OSError, ValueError, ET.ParseError) as exc:
                item["status"], item["reason"] = "failed", "missing_or_invalid_evidence"
                item["evidence_error"] = str(exc)
        results.append(item)
        with (output / "agilab_offline_app_qualification_progress.jsonl").open(
            "a", encoding="utf-8"
        ) as stream:
            stream.write(json.dumps(item, sort_keys=True) + "\n")
        print(
            json.dumps(
                {
                    "check": name,
                    "status": item["status"],
                    "exit_code": item["exit_code"],
                }
            ),
            flush=True,
        )
    source_integrity = {"status": "passed"}
    try:
        after = source_snapshot(manifest["sources"])
        require(before == after, "Source bytes changed during qualification")
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        source_integrity = {"status": "failed", "reason": str(exc)}
    manifest_integrity = {"status": "passed"}
    try:
        require(
            regular_file(manifest_path).read_bytes() == manifest_bytes,
            "Manifest bytes changed during qualification",
        )
    except (ValueError, OSError) as exc:
        manifest_integrity = {"status": "failed", "reason": str(exc)}
    harness_integrity = {"status": "passed"}
    try:
        require(
            digest(regular_file(Path(__file__))) == harness_sha256,
            "Harness bytes changed during qualification",
        )
    except (ValueError, OSError) as exc:
        harness_integrity = {"status": "failed", "reason": str(exc)}
    apps = {}
    for app in sorted({item["app"] for item in results}):
        layers = {}
        for layer in sorted(LAYERS):
            rows = [
                item
                for item in results
                if item["app"] == app and item["layer"] == layer
            ]
            layers[layer] = (
                "not_qualified"
                if not rows
                else (
                    "passed"
                    if all(item["status"] == "passed" for item in rows)
                    else "failed"
                    if any(item["status"] == "failed" for item in rows)
                    else "blocked"
                )
            )
        apps[app] = {
            "layers": layers,
            "qualified_requested_checks": source_integrity["status"] == "passed"
            and manifest_integrity["status"] == "passed"
            and harness_integrity["status"] == "passed"
            and all(
                item["status"] == "passed" for item in results if item["app"] == app
            ),
        }
    receipt = {
        "schema": "agilab.offline_app_qualification_receipt.v1",
        "status": "passed"
        if source_integrity["status"] == "passed"
        and manifest_integrity["status"] == "passed"
        and harness_integrity["status"] == "passed"
        and all(item["status"] == "passed" for item in results)
        else "incomplete",
        "source_integrity": source_integrity,
        "manifest_integrity": manifest_integrity,
        "harness_integrity": harness_integrity,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_sha256": manifest_sha256,
        "harness_sha256": harness_sha256,
        "source_snapshots": before,
        "network_controls": list(controls.values()),
        "checks": results,
        "apps": apps,
        "scope": manifest.get("scope", "Explicit checks only; preinstalled inputs."),
        "limits": [
            "No installation or physical air-gap claim.",
            "Canonical bytecode caches are hash-bound generated inputs; lock and non-executable build/cache metadata are excluded.",
            "Cleanup covers identity-verified observed descendants; rapidly daemonized unobserved descendants are not contained.",
            "Passing a declared scope does not qualify unexecuted app functions or layers.",
        ],
    }
    path = output / "agilab_offline_app_qualification_receipt.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(
        json.dumps(
            {"receipt": str(path), "sha256": digest(path), "status": receipt["status"]}
        ),
        flush=True,
    )
    return receipt


def name_with_role(check: str, role: str) -> str:
    return check + "_" + role


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    receipt = run(args.manifest.resolve(), args.output_dir.resolve())
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
