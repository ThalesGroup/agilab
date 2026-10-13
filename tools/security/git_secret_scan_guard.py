#!/usr/bin/env python3
"""Scan complete staged Git blobs locally with a checksum-pinned Gitleaks binary."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = "8.30.1"
PINS = {
    "darwin_arm64": {
        "archive": "gitleaks_8.30.1_darwin_arm64.tar.gz",
        "archive_sha256": "b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5",
        "binary_sha256": "ba52fb1bfabbcde42f032afad3d6e0b19dff8ed105229a16e7caa338bbc0e84f",
        "binary_bytes": 21324882,
    },
    "darwin_x64": {
        "archive": "gitleaks_8.30.1_darwin_x64.tar.gz",
        "archive_sha256": "dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709",
        "binary_sha256": "cee01fea7173f1b779dff188e1c26ecbcb4027d394acc573b23aaf0be260e291",
        "binary_bytes": 22398576,
    },
    "linux_arm64": {
        "archive": "gitleaks_8.30.1_linux_arm64.tar.gz",
        "archive_sha256": "e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080",
        "binary_sha256": "00e91bbe655bd7c47753e8cfe61cb76ea1a5d7e7702fe161ee40102b46b3823b",
        "binary_bytes": 20775096,
    },
    "linux_x64": {
        "archive": "gitleaks_8.30.1_linux_x64.tar.gz",
        "archive_sha256": "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb",
        "binary_sha256": "88f91962aa2f93ac6ab281d553b9e125f5197bbbce38f9f2437f7299c32e5509",
        "binary_bytes": 21958840,
    },
    "windows_arm64": {
        "archive": "gitleaks_8.30.1_windows_arm64.zip",
        "archive_sha256": "b95f5e4f5c425cedca7ee203d9afd29597e692c4924a12ed42f970537c72cc0f",
        "binary_sha256": "200df852fdecbedb19a33960657333cba5e231740bc8968972b507b50f93b194",
        "binary_bytes": 21111296,
    },
    "windows_x64": {
        "archive": "gitleaks_8.30.1_windows_x64.zip",
        "archive_sha256": "d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e",
        "binary_sha256": "17157e2ee8b76fc8b1d8bee607a250e34b8a8023c8bc81822d4b5ee4d78fcb7c",
        "binary_bytes": 22575104,
    },
}
RELEASE_URL = "https://github.com/gitleaks/gitleaks/releases/download/v" + VERSION + "/"


class GuardError(RuntimeError):
    """A scan cannot establish that the staged content is safe."""


def platform_key():
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = {"aarch64": "arm64", "arm64": "arm64", "amd64": "x64", "x86_64": "x64"}.get(
        machine
    )
    key = system + "_" + str(arch)
    if key not in PINS:
        raise GuardError(
            "Unsupported scanner platform; supported: macOS, Linux and Windows arm64/x64."
        )
    return key


def binary_path():
    base = Path(
        os.environ.get(
            "AGILAB_GITLEAKS_CACHE", str(Path.home() / ".cache" / "agilab" / "gitleaks")
        )
    )
    key = platform_key()
    return (
        base
        / VERSION
        / key
        / ("gitleaks.exe" if key.startswith("windows_") else "gitleaks")
    )


def verified_binary():
    path = binary_path()
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or path.is_symlink():
            raise GuardError("Scanner must be a regular file.")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise GuardError(
            "Scanner is not installed. Run: python3 tools/security/git_secret_scan_guard.py install"
        ) from exc
    if digest != PINS[platform_key()]["binary_sha256"]:
        raise GuardError("Scanner checksum mismatch; no scan was performed.")
    return path


def install():
    path = binary_path()
    if path.exists():
        return verified_binary()
    pin = PINS[platform_key()]
    # Installation is explicit; scans never download code or send repository content.
    with urllib.request.urlopen(RELEASE_URL + pin["archive"], timeout=60) as response:
        archive = response.read(64 * 1024 * 1024 + 1)
    if hashlib.sha256(archive).hexdigest() != pin["archive_sha256"]:
        raise GuardError("Scanner archive checksum mismatch.")
    name = path.name
    if pin["archive"].endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(archive)) as container:
            binary = container.read(name)
    else:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as container:
            binary = container.extractfile(name).read()
    if hashlib.sha256(binary).hexdigest() != pin["binary_sha256"]:
        raise GuardError("Extracted scanner checksum mismatch.")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(
        prefix=".scanner-install-", dir=path.parent
    ) as directory:
        staged = Path(directory) / name
        staged.write_bytes(binary)
        staged.chmod(0o700)
        # Another installer may have completed while this one downloaded.
        if path.exists():
            return verified_binary()
        os.replace(staged, path)
    return verified_binary()


def scanner_content(content):
    # Preserve text and line positions while making BOM-encoded Windows files
    # readable by the UTF-8 detector. The Git index itself is never rewritten.
    encodings = (
        (b"\xff\xfe\x00\x00", "utf-32"),
        (b"\x00\x00\xfe\xff", "utf-32"),
        (b"\xff\xfe", "utf-16"),
        (b"\xfe\xff", "utf-16"),
    )
    for marker, encoding in encodings:
        if content.startswith(marker):
            try:
                return content.decode(encoding).encode("utf-8")
            except UnicodeError as exc:
                raise GuardError(
                    "Invalid BOM-encoded staged text; commit is blocked."
                ) from exc
    return content


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    if result.returncode:
        raise GuardError("Git could not provide an unambiguous staged snapshot.")
    return result.stdout


def index_entries(root):
    raw = git(root, "ls-files", "--stage", "-z")
    entries = {}
    for item in raw.split(b"\0"):
        if not item:
            continue
        metadata, path = item.split(b"\t", 1)
        mode, oid, stage = metadata.split()
        if stage != b"0":
            raise GuardError("Resolve merge conflicts before scanning.")
        entries[path] = (mode, oid)
    return raw, entries


def changed_paths(root):
    return [
        p
        for p in git(
            root, "diff", "--cached", "--name-only", "--diff-filter=ACMRT", "-z"
        ).split(b"\0")
        if p
    ]


def scan_staged(root):
    root = Path(root).resolve()
    top_level = git(root, "rev-parse", "--show-toplevel")
    if not top_level.endswith(b"\n") or b"\0" in top_level:
        raise GuardError("Git returned an invalid repository root.")
    # Remove Git's line terminator, preserving whitespace belonging to the path.
    # CR is not a valid Windows path character, but remains meaningful on Unix.
    terminator_bytes = 2 if os.name == "nt" and top_level.endswith(b"\r\n") else 1
    root = Path(os.fsdecode(top_level[:-terminator_bytes]))
    if not root.is_absolute():
        raise GuardError("Git returned an invalid repository root.")
    root = root.resolve()
    before, entries = index_entries(root)
    changed = changed_paths(root)
    if not changed:
        return {"status": "pass", "files_scanned": 0, "findings": []}
    executable = verified_binary()
    scanned = 0
    with tempfile.TemporaryDirectory(prefix="agilab-staged-secret-scan-") as directory:
        base = Path(directory)
        payload = base / "files"
        payload.mkdir(mode=0o700)
        for raw_path in changed:
            if raw_path not in entries:
                raise GuardError("Git index changed during snapshot preparation.")
            mode, oid = entries[raw_path]
            if (
                mode == b"160000"
            ):  # A gitlink contains no parent-repository file content.
                continue
            rel = Path(os.fsdecode(raw_path))
            if rel.is_absolute() or ".." in rel.parts:
                raise GuardError("Unsafe staged filename.")
            target = payload / rel
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Read the staged blob, never the working copy or a symlink's target.
            content = scanner_content(
                git(root, "cat-file", "blob", oid.decode("ascii"))
            )
            with target.open("xb") as stream:
                stream.write(content)
            target.chmod(0o600)
            scanned += 1
        config = base / "scanner-config.toml"
        config.write_text("[extend]\nuseDefault = true\n", encoding="utf-8")
        ignore = base / "empty-ignores"
        ignore.write_text("", encoding="utf-8")
        report = base / "redacted-findings.json"
        env = {k: v for k, v in os.environ.items() if not k.startswith("GITLEAKS_")}
        result = subprocess.run(
            [
                str(executable),
                "dir",
                str(payload),
                "--config",
                str(config),
                "--gitleaks-ignore-path",
                str(ignore),
                "--ignore-gitleaks-allow",
                "--no-banner",
                "--no-color",
                "--redact=100",
                "--log-level=error",
                "--report-format=json",
                "--report-path",
                str(report),
            ],
            cwd=base,
            env=env,
            capture_output=True,
            # A native Gitleaks timeout may return a clean but partial report.
            # Only the process deadline establishes a completed scan or fails closed.
            timeout=130,
        )
        # Do not relay scanner stdout/stderr: only validated non-secret metadata.
        if result.returncode not in (0, 1) or not report.is_file():
            raise GuardError(
                "Scanner failed; commit is blocked. Re-run after repairing the scanner."
            )
        try:
            findings = json.loads(report.read_text(encoding="utf-8"))
            if not isinstance(findings, list) or any(
                not isinstance(x, dict) for x in findings
            ):
                raise ValueError("invalid report")
            if (result.returncode == 1) != bool(findings):
                raise ValueError("inconsistent scanner outcome")
            safe = []
            for finding in findings:
                rule = finding["RuleID"]
                line = finding["StartLine"]
                path = Path(finding["File"])
                if path.is_absolute():
                    path = path.relative_to(payload)
                if (
                    ".." in path.parts
                    or not re.fullmatch(r"[A-Za-z0-9_-]+", rule)
                    or type(line) is not int
                ):
                    raise ValueError("invalid finding metadata")
                safe.append({"file": path.as_posix(), "line": line, "rule": rule})
        except (KeyError, ValueError, TypeError, OSError) as exc:
            raise GuardError("Scanner report is invalid; commit is blocked.") from exc
        after, _ = index_entries(root)
        if after != before or changed_paths(root) != changed:
            raise GuardError("Git index changed during scanning; retry the commit.")
    return {
        "status": "fail" if safe else "pass",
        "files_scanned": scanned,
        "findings": safe,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "staged"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        if args.action == "install":
            installed = install()
            print(
                json.dumps(
                    {
                        "status": "installed",
                        "version": VERSION,
                        "binary": str(installed),
                    }
                )
            )
            return 0
        result = scan_staged(args.root)
        print(json.dumps(result, ensure_ascii=True))
        return 1 if result["status"] == "fail" else 0
    except (GuardError, OSError, subprocess.TimeoutExpired) as exc:
        # Exceptions containing provider output or file contents are never printed.
        message = (
            str(exc)
            if isinstance(exc, GuardError)
            else "Secret scan could not complete; commit is blocked."
        )
        print(json.dumps({"status": "error", "message": message}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
