#!/usr/bin/env python3
"""Deploy and validate the public AGILAB Hugging Face Space during release."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPACE_ID = "jpmorard/agilab"
DEFAULT_PROFILE = "first-proof"
DEFAULT_TIMEOUT_SECONDS = 900.0
DEFAULT_POLL_SECONDS = 10.0

FIRST_PROOF_APPS = ("flight_project", "meteo_forecast_project")
FIRST_PROOF_PAGES = ("view_maps", "view_forecast_analysis", "view_release_decision")
ADVANCED_APPS = (
    "data_io_2026_project",
    "execution_pandas_project",
    "execution_polars_project",
    "flight_project",
    "global_dag_project",
    "mission_decision_project",
    "mycode_project",
    "tescia_diagnostic_project",
    "uav_queue_project",
    "uav_relay_queue_project",
    "meteo_forecast_project",
)
ADVANCED_PAGES = (
    "view_data_io_decision",
    "view_forecast_analysis",
    "view_maps",
    "view_maps_network",
    "view_queue_resilience",
    "view_relay_resilience",
    "view_release_decision",
)
ALLOWED_APP_ENTRIES = {
    ".DS_Store",
    ".gitignore",
    "README.md",
    "__init__.py",
    "__pycache__",
    "builtin",
    "install.py",
    "src",
    "templates",
}

DOCKERIGNORE = """\
**/.venv/
**/__pycache__/
**/*.pyc
**/*.pyo
**/*.egg-info/
**/.pytest_cache/
**/dist/
**/build/
**/.mypy_cache/
**/.ruff_cache/
**/*.so
**/*.c
**/*.7z
!src/agilab/apps/builtin/flight_project/src/flight_worker/dataset.7z
**/node_modules/
"""

README_TEMPLATE = """\
---
title: AGILAB
emoji: lab_coat
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
app_file: Dockerfile
pinned: false
license: bsd-3-clause
short_description: Anti-lock-in AI workbench with runnable notebook export
---

# AGILAB

This Space is deployed automatically by the AGILAB public release workflow.
It publishes the bounded `{profile}` profile from the public release source
tree and is validated by `tools/hf_space_smoke.py` before release proof is
updated.

Public documentation: https://thalesgroup.github.io/agilab
Source repository: https://github.com/ThalesGroup/agilab
PyPI package: https://pypi.org/project/agilab

## Installed profile

- Apps: `{apps}`
- Pages: `{pages}`

Use a local source checkout for private apps, mounted data, remote clusters, or
the heavier advanced proof pack.
"""

DOCKERFILE_TEMPLATE = """\
FROM ubuntu:24.04
LABEL maintainer="Jean-Pierre Morard"
LABEL description="AGILAB Hugging Face Docker Space"

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \\
    build-essential \\
    curl \\
    wget \\
    unzip \\
    git \\
    ca-certificates \\
    libssl-dev \\
    zlib1g-dev \\
    libbz2-dev \\
    libreadline-dev \\
    libsqlite3-dev \\
    libxml2-dev \\
    liblzma-dev \\
    llvm \\
    llvm-dev \\
    tk-dev \\
    p7zip-full \\
    libffi-dev \\
    clang \\
    locales \\
    && rm -rf /var/lib/apt/lists/*

RUN locale-gen en_US.UTF-8
ENV LC_ALL=en_US.UTF-8
ENV LANG=en_US.UTF-8

RUN curl -LsSf https://astral.sh/uv/install.sh -o /tmp/uv-install.sh && \\
    sh /tmp/uv-install.sh && \\
    cp /root/.local/bin/uv /usr/local/bin/uv && \\
    rm -f /tmp/uv-install.sh && \\
    uv --version

RUN if ! getent group 1000 > /dev/null 2>&1; then groupadd -g 1000 user; fi && \\
    if ! getent passwd 1000 > /dev/null 2>&1; then useradd -m -u 1000 -g 1000 user; fi && \\
    usermod -l user -d /home/user -m "$(getent passwd 1000 | cut -d: -f1)" 2>/dev/null || true && \\
    mkdir -p /home/user && chown 1000:1000 /home/user

RUN mkdir -p /app && chown 1000:1000 /app

USER user
WORKDIR /app

COPY --chown=1000:1000 src/ ./src/
COPY --chown=1000:1000 pyproject.toml ./pyproject.toml
COPY --chown=1000:1000 uv_config.toml ./uv_config.toml
COPY --chown=1000:1000 docker/install.sh ./install.sh
COPY --chown=1000:1000 seed_hf_app_settings.py ./seed_hf_app_settings.py

ENV AGI_PYTHON_VERSION="3.13.9"
ENV AGI_PYTHON_FREE_THREADED="0"
ENV UV_CACHE_DIR="/tmp/uv-cache"
ENV CLUSTER_CREDENTIALS="user:password"
ENV OPENAI_API_KEY=""
ENV APPS_REPOSITORY=""
ENV AGI_LOCAL_SHARE="/home/user/localshare"
ENV AGI_CLUSTER_SHARE="/home/user/clustershare"
ENV AGILAB_DISABLE_BACKGROUND_SERVICES="1"
ENV AGILAB_HF_PROFILE="{profile}"
ENV AGILAB_HF_BUILTIN_APPS="{apps}"
ENV AGILAB_HF_BUILTIN_PAGES="{pages}"

RUN mkdir -p /home/user/.agilab \\
    && mkdir -p /home/user/.local/share/agilab \\
    && mkdir -p /home/user/clustershare \\
    && mkdir -p /home/user/localshare \\
    && mkdir -p /home/user/log/install_logs

RUN chmod +x ./install.sh && \\
    CLUSTER_CREDENTIALS="$CLUSTER_CREDENTIALS" \\
    OPENAI_API_KEY="$OPENAI_API_KEY" \\
    ./install.sh --install-path /app --source local

RUN echo "/app/src/agilab" > /home/user/.local/share/agilab/.agilab-path

RUN cd /app/src/agilab && \\
    chmod +x install_apps.sh && \\
    echo "Installing AGILAB HF profile: ${{AGILAB_HF_PROFILE}}" && \\
    BUILTIN_APPS="${{AGILAB_HF_BUILTIN_APPS}}" \\
    BUILTIN_PAGES="${{AGILAB_HF_BUILTIN_PAGES}}" \\
    APPS_DEST_BASE="/app/src/agilab/apps" \\
    PAGES_DEST_BASE="/app/src/agilab/apps-pages" \\
    ./install_apps.sh && \\
    rm -rf /tmp/uv-cache /home/user/.cache/uv

RUN uv run --project /app --no-sync python /app/seed_hf_app_settings.py

RUN if [ -d /home/user/localshare ]; then \\
      cp -a /home/user/localshare/. /home/user/clustershare/; \\
    fi

RUN uv sync --project /app --extra ui && \\
    rm -rf /tmp/uv-cache /home/user/.cache/uv

EXPOSE 7860

CMD ["bash", "-c", \\
    "AGILAB_PUBLIC_BIND_OK=1 AGILAB_TLS_TERMINATED=1 \\
     uv run --project /app --extra ui --no-sync streamlit run /app/src/agilab/main_page.py \\
     --server.port 7860 \\
     --server.address 0.0.0.0 \\
     --server.headless true \\
     -- --apps-path /app/src/agilab/apps/builtin"]
"""

SEED_HF_APP_SETTINGS = '''\
"""Seed Hugging Face Space app settings for the staged AGILAB profile."""

from __future__ import annotations

import os
import re
from pathlib import Path


CLUSTER_SECTION = (
    "[cluster]\\n"
    "verbose = 1\\n"
    "cython = false\\n"
    "pool = false\\n"
    "rapids = false\\n"
    "cluster_enabled = false\\n"
    'scheduler = "127.0.0.1:8786"\\n'
    'workers_data_path = "/home/user/clustershare"\\n'
    "\\n"
    "[cluster.workers]\\n"
    '"127.0.0.1" = 2\\n'
    "\\n"
    "[cluster.service_health]\\n"
    "allow_idle = false\\n"
    "max_unhealthy = 0\\n"
    "max_restart_rate = 0.25\\n"
    "\\n"
)


def main() -> None:
    apps = os.environ["AGILAB_HF_BUILTIN_APPS"].split()
    for app in apps:
        source = Path(f"/app/src/agilab/apps/builtin/{app}/src/app_settings.toml")
        if not source.exists():
            continue

        target = Path(f"/home/user/.agilab/apps/{app}/app_settings.toml")
        target.parent.mkdir(parents=True, exist_ok=True)

        text = source.read_text(encoding="utf-8")
        text, count = re.subn(
            r"(?ms)^\\[cluster\\]\\n.*?(?=^\\[(?!cluster(?:\\.|\\]))|\\Z)",
            CLUSTER_SECTION,
            text,
            count=1,
        )
        if count != 1:
            raise SystemExit(f"missing [cluster] section in {source}")

        target.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
'''


def profile_entries(profile: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if profile == "first-proof":
        return FIRST_PROOF_APPS, FIRST_PROOF_PAGES
    if profile == "advanced":
        return ADVANCED_APPS, ADVANCED_PAGES
    raise ValueError(f"unknown HF Space profile: {profile}")


def format_space_url(space_id: str) -> str:
    return f"https://huggingface.co/spaces/{space_id}"


def runtime_url_for_space(space_id: str) -> str:
    owner, name = space_id.split("/", 1)
    return f"https://{owner}-{name}.hf.space"


def api_url_for_space(space_id: str) -> str:
    quoted = "/".join(urllib.parse.quote(part, safe="") for part in space_id.split("/"))
    return f"https://huggingface.co/api/spaces/{quoted}"


def info(message: str) -> None:
    print(f"[hf-release-sync] {message}", flush=True)


def run_command(command: Sequence[str], *, env: dict[str, str] | None = None) -> str:
    info("running: " + " ".join(command))
    completed = subprocess.run(
        list(command),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    if completed.returncode != 0:
        raise RuntimeError(f"command failed with exit {completed.returncode}: {' '.join(command)}")
    return completed.stdout or ""


def require_clean_public_apps(apps_dir: Path) -> None:
    offenders: list[str] = []
    for entry in sorted(apps_dir.iterdir(), key=lambda path: path.name):
        if entry.name in ALLOWED_APP_ENTRIES:
            continue
        suffix = f" -> {os.readlink(entry)}" if entry.is_symlink() else ""
        offenders.append(f"{entry}{suffix}")
    if offenders:
        formatted = "\n  - ".join(offenders)
        raise RuntimeError(
            "refusing HF deploy: non-public app entries found under "
            f"{apps_dir}\n  - {formatted}"
        )


def require_profile_dirs(repo_root: Path, profile: str, apps: Sequence[str], pages: Sequence[str]) -> None:
    missing = [
        f"src/agilab/apps/builtin/{name}"
        for name in apps
        if not (repo_root / "src/agilab/apps/builtin" / name).is_dir()
    ]
    missing.extend(
        f"src/agilab/apps-pages/{name}"
        for name in pages
        if not (repo_root / "src/agilab/apps-pages" / name).is_dir()
    )
    if missing:
        raise RuntimeError(f"profile {profile!r} references missing entries: {', '.join(missing)}")


def require_no_symlinked_sources(source_root: Path) -> None:
    symlinks = [str(path) for path in source_root.rglob("*") if path.is_symlink()]
    if symlinks:
        formatted = "\n  - ".join(sorted(symlinks))
        raise RuntimeError(f"refusing HF deploy: source tree contains symlinks\n  - {formatted}")


def copy_ignore(_directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name in {".DS_Store", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}:
            ignored.add(name)
        elif name in {".venv", "dist", "build", "node_modules"}:
            ignored.add(name)
        elif name.endswith((".pyc", ".pyo", ".egg-info")):
            ignored.add(name)
    return ignored


def prune_dir_except(root: Path, keep: Sequence[str]) -> None:
    keep_set = set(keep)
    for entry in sorted(root.iterdir(), key=lambda path: path.name):
        if not entry.is_dir() or entry.name in keep_set:
            continue
        shutil.rmtree(entry)


def write_profile_assets(stage_dir: Path, profile: str, apps: Sequence[str], pages: Sequence[str]) -> None:
    app_text = " ".join(apps)
    page_text = " ".join(pages)
    (stage_dir / "README.md").write_text(
        README_TEMPLATE.format(profile=profile, apps=app_text, pages=page_text),
        encoding="utf-8",
    )
    (stage_dir / "Dockerfile").write_text(
        DOCKERFILE_TEMPLATE.format(profile=profile, apps=app_text, pages=page_text),
        encoding="utf-8",
    )
    (stage_dir / ".dockerignore").write_text(DOCKERIGNORE, encoding="utf-8")
    (stage_dir / "seed_hf_app_settings.py").write_text(SEED_HF_APP_SETTINGS, encoding="utf-8")


def stage_space_tree(repo_root: Path, stage_dir: Path, *, profile: str) -> dict[str, Any]:
    apps, pages = profile_entries(profile)
    if not (repo_root / "src/agilab/main_page.py").is_file():
        raise RuntimeError(f"not an AGILAB checkout: {repo_root}")
    require_clean_public_apps(repo_root / "src/agilab/apps")
    require_profile_dirs(repo_root, profile, apps, pages)
    require_no_symlinked_sources(repo_root / "src")

    write_profile_assets(stage_dir, profile, apps, pages)
    shutil.copytree(repo_root / "src", stage_dir / "src", ignore=copy_ignore)
    shutil.copy2(repo_root / "pyproject.toml", stage_dir / "pyproject.toml")
    shutil.copy2(repo_root / "uv_config.toml", stage_dir / "uv_config.toml")
    (stage_dir / "docker").mkdir()
    shutil.copy2(repo_root / "docker/install.sh", stage_dir / "docker/install.sh")

    prune_dir_except(stage_dir / "src/agilab/apps/builtin", apps)
    prune_dir_except(stage_dir / "src/agilab/apps-pages", pages)

    files = [path for path in stage_dir.rglob("*") if path.is_file()]
    total_bytes = sum(path.stat().st_size for path in files)
    return {
        "profile": profile,
        "apps": list(apps),
        "pages": list(pages),
        "file_count": len(files),
        "bytes": total_bytes,
    }


def hf_headers(token: str | None) -> dict[str, str]:
    headers = {"User-Agent": "agilab-hf-release-sync/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_space_info(space_id: str, *, token: str | None, timeout: float = 30.0) -> dict[str, Any]:
    request = urllib.request.Request(api_url_for_space(space_id), headers=hf_headers(token))
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def current_space_sha(space_id: str, *, token: str | None) -> str:
    payload = fetch_space_info(space_id, token=token)
    return str(payload.get("sha") or "")


def parse_commit_sha(output: str) -> str | None:
    match = re.search(r"/commit/([0-9a-f]{40})", output)
    return match.group(1) if match else None


def upload_space(stage_dir: Path, *, space_id: str, token: str, private: bool) -> str:
    env = os.environ.copy()
    env["HF_TOKEN"] = token
    output = run_command(
        [
            "hf",
            "upload",
            space_id,
            str(stage_dir),
            "--type",
            "space",
            "--commit-message",
            f"chore: deploy AGILAB release Space ({time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})",
            "--delete",
            "src/agilab/apps/builtin/**",
            "--delete",
            "src/agilab/apps-pages/**",
            "--delete",
            "src/agilab/pages/**",
            "--delete",
            "src/.DS_Store",
            "--delete",
            "src/.coverage*",
            "--delete",
            "src/**/.DS_Store",
            "--delete",
            "src/**/.coverage*",
            "--exclude",
            "**/.venv/**",
            "--exclude",
            "**/__pycache__/**",
            "--exclude",
            "**/*.pyc",
        ],
        env=env,
    )
    visibility = "--private" if private else "--public"
    run_command(["hf", "repos", "settings", space_id, "--repo-type", "space", visibility, "--format", "quiet"], env=env)
    return parse_commit_sha(output) or current_space_sha(space_id, token=token)


def wait_for_runtime(
    space_id: str,
    *,
    expected_sha: str,
    token: str,
    timeout_seconds: float,
    poll_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = fetch_space_info(space_id, token=token)
        runtime = last.get("runtime") if isinstance(last.get("runtime"), dict) else {}
        repo_sha = str(last.get("sha") or "")
        runtime_sha = str(runtime.get("sha") or "")
        stage = str(runtime.get("stage") or "")
        info(f"space status: sha={repo_sha} runtime_sha={runtime_sha} stage={stage}")
        if repo_sha == expected_sha and runtime_sha == expected_sha and stage == "RUNNING":
            return last
        if "ERROR" in stage or "FAILED" in stage:
            raise RuntimeError(f"HF Space runtime failed while deploying {expected_sha}: {stage}")
        time.sleep(poll_seconds)
    raise TimeoutError(f"HF Space did not reach RUNNING at {expected_sha} within {timeout_seconds:.0f}s")


def run_hosted_smoke(repo_root: Path, *, space_id: str, timeout: float, target_seconds: float) -> dict[str, Any]:
    command = [
        sys.executable,
        str(repo_root / "tools/hf_space_smoke.py"),
        "--space",
        space_id,
        "--url",
        runtime_url_for_space(space_id),
        "--json",
        "--timeout",
        str(timeout),
        "--target-seconds",
        str(target_seconds),
    ]
    output = run_command(command)
    return json.loads(output[output.find("{") :])


def write_github_output(path: Path, values: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--space", default=os.environ.get("AGILAB_HF_SPACE_ID", DEFAULT_SPACE_ID))
    parser.add_argument("--profile", default=os.environ.get("AGILAB_HF_SPACE_PROFILE", DEFAULT_PROFILE))
    parser.add_argument("--private", action="store_true", help="Keep the Space private instead of public.")
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--smoke-timeout", type=float, default=30.0)
    parser.add_argument("--smoke-target-seconds", type=float, default=30.0)
    parser.add_argument("--github-output", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Stage and validate files without uploading.")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    token = os.environ.get("HF_TOKEN", "")
    if not token and not args.dry_run:
        raise SystemExit("HF_TOKEN is required for release HF Space sync")
    if "/" not in args.space:
        raise SystemExit("--space must be NAMESPACE/SPACE_NAME")
    if shutil.which("hf") is None and not args.dry_run:
        raise SystemExit("hf CLI is required; install huggingface_hub[cli]")

    with tempfile.TemporaryDirectory(prefix="agilab-hf-release-") as tmp:
        stage_dir = Path(tmp)
        staged = stage_space_tree(repo_root, stage_dir, profile=args.profile)
        info(f"staged {staged['file_count']} files for {args.profile} ({staged['bytes']} bytes)")
        if args.dry_run:
            summary = {
                "success": True,
                "dry_run": True,
                "space": args.space,
                "space_url": format_space_url(args.space),
                "staged": staged,
            }
        else:
            hf_commit = upload_space(stage_dir, space_id=args.space, token=token, private=args.private)
            runtime = wait_for_runtime(
                args.space,
                expected_sha=hf_commit,
                token=token,
                timeout_seconds=args.timeout_seconds,
                poll_seconds=args.poll_seconds,
            )
            smoke = run_hosted_smoke(
                repo_root,
                space_id=args.space,
                timeout=args.smoke_timeout,
                target_seconds=args.smoke_target_seconds,
            )
            runtime_payload = runtime.get("runtime") if isinstance(runtime.get("runtime"), dict) else {}
            summary = {
                "success": bool(smoke.get("success")),
                "dry_run": False,
                "space": args.space,
                "space_url": format_space_url(args.space),
                "runtime_url": runtime_url_for_space(args.space),
                "hf_space_commit": hf_commit,
                "runtime_stage": str(runtime_payload.get("stage") or ""),
                "runtime_sha": str(runtime_payload.get("sha") or ""),
                "staged": staged,
                "smoke": smoke,
            }
            if args.github_output:
                write_github_output(
                    args.github_output,
                    {
                        "hf_space_commit": hf_commit,
                        "hf_space_url": format_space_url(args.space),
                        "hf_runtime_stage": str(runtime_payload.get("stage") or ""),
                    },
                )

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
