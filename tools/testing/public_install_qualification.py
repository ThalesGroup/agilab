"""Install the manifest-pinned public package, then run its installed first proof."""

from __future__ import annotations

import argparse
import json
import hashlib
import tomllib
import os
from pathlib import Path
import subprocess
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[2]


def public_install_environment(
    home: Path, base_env: dict[str, str] | None = None
) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    for key in (
        "PYTHONPATH",
        "PYTHONUSERBASE",
        "VIRTUAL_ENV",
        "APPS_REPOSITORY",
        "UV_PROJECT_ENVIRONMENT",
        "UV_NO_SYNC",
        "PYTHONHOME",
        "AGILAB_DOCS_SOURCE",
        "DOCS_REPOSITORY",
        "PIP_EXTRA_INDEX_URL",
        "PIP_FIND_LINKS",
        "PIP_NO_INDEX",
    ):
        env.pop(key, None)
    for key in tuple(env):
        if key.upper().startswith("PIP_") and key.upper() not in {
            "PIP_CERT",
            "PIP_CLIENT_CERT",
        }:
            env.pop(key)
    env.update(
        PIP_CONFIG_FILE=os.devnull,
        PIP_INDEX_URL="https://pypi.org/simple",
        PYTHONNOUSERSITE="1",
    )
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        XDG_DATA_HOME=str(home / ".local/share"),
        XDG_CONFIG_HOME=str(home / ".config"),
        XDG_CACHE_HOME=str(home / ".cache"),
        APPDATA=str(home / "AppData/Roaming"),
        LOCALAPPDATA=str(home / "AppData/Local"),
        AGILAB_DISABLE_BACKGROUND_SERVICES="1",
        OPENAI_API_KEY="sk-test-first-proof-000000000000",
    )
    return env


def qualify(output: Path) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = ROOT / "docs/source/data/release_proof.toml"
    release = tomllib.loads(manifest.read_text())["release"]
    payload = {
        "package": release["package_name"],
        "version": release["package_version"],
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "schema": "agilab.public_install_qualification.v1",
        "status": "failed",
        "scope": "Exact public package on this host; source first-proof and other platforms remain separate.",
    }
    with tempfile.TemporaryDirectory(prefix="agilab-public-install-") as directory:
        stage = Path(directory)
        environment = stage / "environment"
        python = environment / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        home = stage / "home"
        home.mkdir()
        env = public_install_environment(home)
        # The existing installer owns public package pins, retries and dependency checks.
        installer = ROOT / "tools/install_release_proof_package.py"
        command = [
            str(python),
            str(installer),
            "--manifest",
            str(ROOT / "docs/source/data/release_proof.toml"),
            "--retries",
            "20",
            "--delay-seconds",
            "15",
        ]
        try:
            subprocess.run(
                [sys.executable, "-m", "venv", str(environment)],
                cwd=stage,
                env=env,
                check=True,
                timeout=120,
            )
            subprocess.run(command, cwd=stage, env=env, check=True, timeout=900)
            identity = subprocess.check_output(
                [
                    str(python),
                    "-c",
                    "import agilab,importlib.metadata,json; print(json.dumps({'module':agilab.__file__,'version':importlib.metadata.version('agilab')}))",
                ],
                cwd=stage,
                env=env,
                text=True,
            )
            payload["installed"] = json.loads(identity)
            if payload["installed"]["version"] != release["package_version"]:
                raise ValueError(
                    "Installed public package differs from the manifest pin."
                )
            if (
                not Path(payload["installed"]["module"])
                .resolve()
                .is_relative_to(environment.resolve())
            ):
                raise ValueError(
                    "Public package imports outside the isolated environment."
                )
            console = environment / (
                "Scripts/agilab.exe" if os.name == "nt" else "bin/agilab"
            )
            proof = subprocess.run(
                [
                    str(console),
                    "first-proof",
                    "--json",
                    "--no-manifest",
                    "--max-seconds",
                    "60",
                ],
                cwd=stage,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )
            (output.parent / "public-install-first-proof.stdout.txt").write_text(
                proof.stdout
            )
            (output.parent / "public-install-first-proof.stderr.txt").write_text(
                proof.stderr
            )
            result = json.loads(proof.stdout)
            payload["first_proof"] = result
            if (
                proof.returncode != 0
                or result.get("success") is not True
                or result.get("within_target") is not True
            ):
                raise ValueError(
                    "Installed public first-proof failed or exceeded its target."
                )
            payload["status"] = "passed"
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            payload["error"] = str(exc)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "test-results/public-install-qualification.json",
    )
    args = parser.parse_args(argv)
    result = qualify(args.output)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
