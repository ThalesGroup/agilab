"""Advisory local security preflight for AGILAB adoption."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tomllib
from typing import Any, Mapping, Sequence


SCHEMA = "agilab.security_check.v1"
SCHEMA_VERSION = 1
DEFAULT_ARTIFACT_MAX_AGE_DAYS = 30
PROFILES = ("local", "shared", "cluster", "public-ui")
SECRET_KEY_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)
HEX_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
LOCAL_HOSTS = {"", "127.0.0.1", "localhost", "::1"}
EXPOSED_HOSTS = {"0.0.0.0", "::"}
PUBLIC_BIND_OK_ENV = "AGILAB_PUBLIC_BIND_OK"
APPS_ALLOWLIST_ENV = "AGILAB_APPS_REPOSITORY_ALLOWLIST"
APPS_ALLOWLIST_FILE_ENV = "AGILAB_APPS_REPOSITORY_ALLOWLIST_FILE"
PLACEHOLDER_SECRET_VALUES = {
    "empty",
    "none",
    "null",
    "placeholder",
    "your-api-key",
    "your-key",
    "change-me",
    "changeme",
}


@dataclass(frozen=True)
class Check:
    id: str
    label: str
    status: str
    summary: str
    remediation: str
    details: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "summary": self.summary,
            "remediation": self.remediation,
            "details": dict(self.details),
        }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _is_hardening_profile(profile: str) -> bool:
    return profile in {"shared", "cluster", "public-ui"}


def _status_for_profile(*, profile: str, local_status: str = "warn") -> str:
    return "fail" if _is_hardening_profile(profile) else local_status


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip("'\"")
        if key:
            result[key] = value
    return result


def _merged_config(environ: Mapping[str, str], env_file_values: Mapping[str, str]) -> dict[str, str]:
    merged = dict(env_file_values)
    merged.update({key: value for key, value in environ.items() if value is not None})
    return merged


def _resolve_path(raw_path: str | None, *, cwd: Path) -> Path | None:
    value = str(raw_path or "").strip().strip("'\"")
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = cwd / path
    return path


def _resolve_git_dir(repo: Path) -> Path | None:
    dot_git = repo / ".git"
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():
        text = dot_git.read_text(encoding="utf-8", errors="ignore").strip()
        if text.startswith("gitdir:"):
            git_dir = Path(text.split(":", 1)[1].strip()).expanduser()
            if not git_dir.is_absolute():
                git_dir = dot_git.parent / git_dir
            return git_dir
    return None


def _git_config_value(repo: Path, section: str, key: str) -> str | None:
    git_dir = _resolve_git_dir(repo)
    if git_dir is None:
        return None
    config_path = git_dir / "config"
    if not config_path.is_file():
        return None
    current_section: str | None = None
    for raw_line in config_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip()
            continue
        if current_section != section or "=" not in line:
            continue
        raw_key, raw_value = line.split("=", 1)
        if raw_key.strip() == key:
            return raw_value.strip()
    return None


def _git_origin_url(repo: Path) -> str | None:
    return _git_config_value(repo, 'remote "origin"', "url")


def _redact_url(value: str | None) -> str | None:
    if not value:
        return value
    return re.sub(r"(https?://)[^/@:\s]+(:[^/@\s]+)?@", r"\1<redacted>@", value)


def _split_allowlist(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[\n,;]", value) if item.strip()]


def _apps_repository_allowlist(config: Mapping[str, str], *, cwd: Path) -> list[str]:
    allowlist = _split_allowlist(str(config.get(APPS_ALLOWLIST_ENV) or ""))
    file_path = _resolve_path(config.get(APPS_ALLOWLIST_FILE_ENV), cwd=cwd)
    if file_path and file_path.is_file():
        for raw_line in file_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#"):
                allowlist.extend(_split_allowlist(line))
    return sorted(set(allowlist))


def _git_head_state(repo: Path) -> dict[str, Any]:
    git_dir = _resolve_git_dir(repo)
    if git_dir is None:
        return {"is_git_checkout": False}
    head_path = git_dir / "HEAD"
    if not head_path.is_file():
        return {"is_git_checkout": True, "head_state": "unknown"}
    head = head_path.read_text(encoding="utf-8", errors="ignore").strip()
    if head.startswith("ref:"):
        ref = head.split(":", 1)[1].strip()
        short = ref.removeprefix("refs/heads/").removeprefix("refs/tags/")
        return {
            "is_git_checkout": True,
            "head_state": "branch" if ref.startswith("refs/heads/") else "ref",
            "ref": ref,
            "name": short,
        }
    if HEX_SHA_RE.match(head):
        return {"is_git_checkout": True, "head_state": "detached", "commit": head}
    return {"is_git_checkout": True, "head_state": "unknown", "head": head[:64]}


def _check_apps_repository(config: Mapping[str, str], *, cwd: Path, profile: str = "local") -> Check:
    path = _resolve_path(config.get("APPS_REPOSITORY"), cwd=cwd)
    if path is None:
        return Check(
            "apps_repository_pin",
            "External apps repository pinning",
            "pass",
            "APPS_REPOSITORY is not configured.",
            "No action required unless you install external apps.",
            {},
        )
    if not path.exists():
        return Check(
            "apps_repository_pin",
            "External apps repository pinning",
            _status_for_profile(profile=profile),
            "APPS_REPOSITORY points to a missing path.",
            "Point APPS_REPOSITORY to an allowlisted reviewed checkout, pinned commit, or immutable tag.",
            {"path": str(path)},
        )
    if not path.is_dir():
        return Check(
            "apps_repository_pin",
            "External apps repository pinning",
            _status_for_profile(profile=profile),
            "APPS_REPOSITORY is not a directory.",
            "Use a reviewed Git checkout directory for external apps.",
            {"path": str(path)},
        )
    git_state = _git_head_state(path)
    if not git_state.get("is_git_checkout"):
        return Check(
            "apps_repository_pin",
            "External apps repository pinning",
            _status_for_profile(profile=profile),
            "APPS_REPOSITORY is not a Git checkout.",
            "Use an allowlisted Git checkout pinned to a commit SHA or immutable tag before shared use.",
            {"path": str(path), **git_state},
        )
    if git_state.get("head_state") == "branch":
        return Check(
            "apps_repository_pin",
            "External apps repository pinning",
            _status_for_profile(profile=profile),
            "APPS_REPOSITORY is on a floating branch.",
            "Checkout a reviewed commit SHA or immutable tag before installing external apps in shared environments.",
            {"path": str(path), **git_state},
        )
    origin_url = _git_origin_url(path)
    allowlist = _apps_repository_allowlist(config, cwd=cwd)
    details = {
        "path": str(path),
        **git_state,
        "origin_url": _redact_url(origin_url),
        "allowlist_configured": bool(allowlist),
    }
    if _is_hardening_profile(profile):
        if not origin_url:
            return Check(
                "apps_repository_pin",
                "External apps repository pinning",
                "fail",
                "APPS_REPOSITORY is pinned but has no origin URL to match against an allowlist.",
                (
                    "Set a reviewed origin URL and configure "
                    f"{APPS_ALLOWLIST_ENV} or {APPS_ALLOWLIST_FILE_ENV} before shared use."
                ),
                details,
            )
        if origin_url not in allowlist:
            return Check(
                "apps_repository_pin",
                "External apps repository pinning",
                "fail",
                "APPS_REPOSITORY origin is not in the configured allowlist.",
                (
                    "Add the exact reviewed origin URL to "
                    f"{APPS_ALLOWLIST_ENV} or {APPS_ALLOWLIST_FILE_ENV}, then rerun the gate."
                ),
                details | {"allowlist_size": len(allowlist)},
            )
    return Check(
        "apps_repository_pin",
        "External apps repository pinning",
        "pass",
        (
            "APPS_REPOSITORY is pinned and allowlisted."
            if _is_hardening_profile(profile)
            else "APPS_REPOSITORY is a Git checkout and is not on a floating branch."
        ),
        "Keep the referenced commit reviewed and scanned.",
        details,
    )


def _looks_like_secret_value(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    lower = stripped.lower()
    if lower in PLACEHOLDER_SECRET_VALUES:
        return False
    if lower.startswith("sk-test"):
        return False
    return True


def _check_persisted_secrets(
    env_file: Path,
    env_file_values: Mapping[str, str],
    *,
    profile: str = "local",
) -> Check:
    keys = sorted(
        key
        for key, value in env_file_values.items()
        if SECRET_KEY_RE.search(key) and _looks_like_secret_value(value)
    )
    if not keys:
        return Check(
            "persisted_plaintext_secrets",
            "Plaintext local secrets",
            "pass",
            "No likely sensitive secret values were found in the AGILAB env file.",
            "Keep shared/sensitive secrets in a keyring, vault, or short-lived session environment.",
            {"env_file": str(env_file), "secret_keys": []},
        )
    return Check(
        "persisted_plaintext_secrets",
        "Plaintext local secrets",
        _status_for_profile(profile=profile),
        "Likely sensitive keys are persisted in the AGILAB env file.",
        "Move these values to a keyring, vault, or short-lived environment variables; avoid command-line secrets.",
        {"env_file": str(env_file), "secret_keys": keys},
    )


def _check_cluster_share(config: Mapping[str, str], *, cwd: Path, profile: str = "local") -> Check:
    cluster_share = _resolve_path(config.get("AGI_CLUSTER_SHARE"), cwd=cwd)
    local_share = _resolve_path(config.get("AGI_LOCAL_SHARE"), cwd=cwd)
    scheduler = str(config.get("AGI_SCHEDULER_IP") or "").strip()
    workers = str(config.get("AGI_WORKERS") or config.get("AGI_CLUSTER_WORKERS") or "").strip()
    cluster_requested = bool(cluster_share or workers or scheduler not in LOCAL_HOSTS)
    if profile == "cluster":
        cluster_requested = True
    if not cluster_requested:
        return Check(
            "cluster_share_isolation",
            "Cluster share isolation",
            "pass",
            "Cluster mode does not appear to be requested.",
            "No action required for local-only use.",
            {
                "cluster_share": str(cluster_share) if cluster_share else None,
                "scheduler": scheduler or None,
                "workers_configured": bool(workers),
            },
        )
    details = {
        "cluster_share": str(cluster_share) if cluster_share else None,
        "local_share": str(local_share) if local_share else None,
        "scheduler": scheduler or None,
        "workers_configured": bool(workers),
    }
    if cluster_share is None:
        return Check(
            "cluster_share_isolation",
            "Cluster share isolation",
            _status_for_profile(profile=profile),
            "Cluster mode appears requested but AGI_CLUSTER_SHARE is not configured.",
            "Configure an explicit per-user shared cluster mount and rerun the cluster gate.",
            details,
        )
    exists = cluster_share.exists()
    is_dir = cluster_share.is_dir()
    writable = exists and is_dir and os.access(cluster_share, os.W_OK)
    same_as_local = bool(
        cluster_share
        and local_share
        and exists
        and local_share.exists()
        and cluster_share.resolve() == local_share.resolve()
    )
    world_writable = bool(exists and is_dir and (cluster_share.stat().st_mode & 0o002))
    details |= {
        "cluster_share_exists": exists,
        "cluster_share_is_dir": is_dir,
        "cluster_share_writable": writable,
        "same_as_local_share": same_as_local,
        "world_writable": world_writable,
    }
    if not exists or not is_dir or not writable:
        return Check(
            "cluster_share_isolation",
            "Cluster share isolation",
            _status_for_profile(profile=profile),
            "Cluster share is not an existing writable directory.",
            "Mount or create a per-user cluster share before running distributed workloads.",
            details,
        )
    if same_as_local:
        return Check(
            "cluster_share_isolation",
            "Cluster share isolation",
            _status_for_profile(profile=profile),
            "Cluster share is the same path as the local share.",
            "Use a distinct shared mount for cluster data; do not silently degrade to localshare.",
            details,
        )
    if world_writable:
        return Check(
            "cluster_share_isolation",
            "Cluster share isolation",
            _status_for_profile(profile=profile),
            "Cluster share is world-writable.",
            "Restrict the cluster share to the trusted operator or per-user group before shared use.",
            details,
        )
    return Check(
        "cluster_share_isolation",
        "Cluster share isolation",
        "pass",
        "Cluster mode has an explicit writable share distinct from localshare.",
        "Validate the worker-side mount contract and sentinel round-trip before running shared workloads.",
        details,
    )


def _streamlit_config_address(home: Path) -> str | None:
    config_path = home / ".streamlit" / "config.toml"
    if not config_path.is_file():
        return None
    try:
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    server = payload.get("server")
    if not isinstance(server, dict):
        return None
    value = server.get("address")
    return str(value).strip() if value is not None else None


def _check_ui_exposure(config: Mapping[str, str], *, home: Path, profile: str = "local") -> Check:
    host = (
        config.get("STREAMLIT_SERVER_ADDRESS")
        or config.get("AGILAB_UI_HOST")
        or config.get("UVICORN_HOST")
        or _streamlit_config_address(home)
        or ""
    ).strip()
    if host not in EXPOSED_HOSTS:
        return Check(
            "ui_network_exposure",
            "UI network exposure",
            "pass",
            "No public bind address was detected from environment or Streamlit config.",
            "Keep local UI binds on 127.0.0.1 unless an authenticated TLS front end is configured.",
            {"host": host or None},
        )
    public_bind_ok = _truthy(config.get(PUBLIC_BIND_OK_ENV))
    auth_or_tls = any(
        _truthy(config.get(name))
        for name in (
            "AGILAB_AUTH_REQUIRED",
            "AGILAB_PUBLIC_AUTH",
            "AGILAB_TLS_TERMINATED",
            "STREAMLIT_AUTH_REQUIRED",
        )
    )
    if public_bind_ok and auth_or_tls:
        return Check(
            "ui_network_exposure",
            "UI network exposure",
            "pass",
            "UI binds publicly with explicit public-bind acknowledgement and auth/TLS indicator.",
            "Verify the front-end control is actually enforced before exposing sensitive data.",
            {"host": host, "public_bind_ok": True, "auth_or_tls_indicator": True},
        )
    return Check(
        "ui_network_exposure",
        "UI network exposure",
        _status_for_profile(profile=profile),
        "UI appears configured to bind publicly without the full public-bind control pair.",
        (
            "Bind to 127.0.0.1, or set AGILAB_PUBLIC_BIND_OK=1 together with an auth/TLS "
            "indicator after a reverse proxy or equivalent control is actually configured."
        ),
        {"host": host, "public_bind_ok": public_bind_ok, "auth_or_tls_indicator": auth_or_tls},
    )


def _check_optional_profiles(config: Mapping[str, str], *, profile: str = "local") -> Check:
    enabled: dict[str, str] = {}
    for key in (
        "INSTALL_LOCAL_MODELS",
        "AGILAB_INSTALL_LOCAL_MODELS",
        "AGILAB_INSTALL_PROFILE",
        "LAB_LLM_PROVIDER",
        "UOAIC_MODEL",
        "UOAIC_OLLAMA_ENDPOINT",
    ):
        value = str(config.get(key) or "").strip()
        if value:
            enabled[key] = value
    local_provider = enabled.get("LAB_LLM_PROVIDER", "").lower()
    if local_provider and not (
        local_provider.startswith("ollama") or "local" in local_provider or "vllm" in local_provider
    ):
        enabled.pop("LAB_LLM_PROVIDER", None)
    if not enabled:
        return Check(
            "optional_runtime_profiles",
            "Optional runtime profiles",
            "pass",
            "No optional local-model or installer profile indicators were detected.",
            "Keep optional profiles disabled unless the deployment needs them.",
            {"enabled_keys": []},
        )
    return Check(
        "optional_runtime_profiles",
        "Optional runtime profiles",
        "warn",
        "Optional local-model or installer profile indicators are configured.",
        "Review dry-run output and supply-chain evidence before enabling local-model, Ollama, or cluster automation profiles.",
        {"enabled_keys": sorted(enabled), "profile": profile},
    )


def _check_generated_code_execution(config: Mapping[str, str], *, profile: str = "local") -> Check:
    enabled = {
        key: str(config.get(key) or "").strip()
        for key in (
            "UOAIC_AUTOFIX",
            "AGILAB_GENERATED_CODE_AUTORUN",
        )
        if _truthy(str(config.get(key) or ""))
    }
    if not enabled:
        return Check(
            "generated_code_execution_boundary",
            "Generated-code execution boundary",
            "pass",
            "Generated-code auto-run indicators are not enabled.",
            "Keep model-generated code reviewed, or run it in a constrained process/container before shared use.",
            {"enabled_keys": []},
        )
    sandbox = str(config.get("AGILAB_GENERATED_CODE_SANDBOX") or "").strip().lower()
    process_limits = _truthy(config.get("AGILAB_GENERATED_CODE_PROCESS_LIMITS"))
    if sandbox in {"container", "vm"} or (sandbox == "process" and process_limits):
        return Check(
            "generated_code_execution_boundary",
            "Generated-code execution boundary",
            "pass",
            "Generated-code auto-run is enabled with an explicit sandbox boundary.",
            "Verify the configured sandbox really limits filesystem, network, CPU, RAM, time, and secrets.",
            {
                "enabled_keys": sorted(enabled),
                "sandbox": sandbox,
                "process_limits": process_limits,
            },
        )
    if sandbox == "process":
        return Check(
            "generated_code_execution_boundary",
            "Generated-code execution boundary",
            _status_for_profile(profile=profile),
            "Generated-code auto-run uses process mode without an explicit resource-limit indicator.",
            (
                "Prefer AGILAB_GENERATED_CODE_SANDBOX=container|vm for shared use. If using process "
                "mode, enforce filesystem, network, CPU, RAM, time, and secret boundaries and set "
                "AGILAB_GENERATED_CODE_PROCESS_LIMITS=1."
            ),
            {
                "enabled_keys": sorted(enabled),
                "sandbox": sandbox,
                "process_limits": process_limits,
            },
        )
    return Check(
        "generated_code_execution_boundary",
        "Generated-code execution boundary",
        _status_for_profile(profile=profile),
        "Generated-code auto-run is enabled without an explicit sandbox indicator.",
        "Run generated code in a constrained process/container/VM and set AGILAB_GENERATED_CODE_SANDBOX=process|container|vm when that boundary is in place.",
        {"enabled_keys": sorted(enabled), "sandbox": sandbox or None, "process_limits": process_limits},
    )


def _artifact_state(path: Path, *, now: datetime, max_age_days: int) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False}
    mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    age_days = (now - mtime).total_seconds() / 86400
    return {
        "path": str(path),
        "exists": True,
        "age_days": round(age_days, 3),
        "fresh": age_days <= max_age_days,
    }


def _check_supply_chain_artifacts(
    *,
    cwd: Path,
    now: datetime,
    pip_audit_json: Path | None,
    sbom_json: Path | None,
    max_age_days: int,
    profile: str,
) -> Check:
    pip_path = pip_audit_json or cwd / "pip-audit.json"
    sbom_path = sbom_json or cwd / "sbom-cyclonedx.json"
    pip_state = _artifact_state(pip_path, now=now, max_age_days=max_age_days)
    sbom_state = _artifact_state(sbom_path, now=now, max_age_days=max_age_days)
    fresh = bool(pip_state.get("fresh")) and bool(sbom_state.get("fresh"))
    if fresh:
        return Check(
            "supply_chain_artifacts",
            "Supply-chain scan artifacts",
            "pass",
            "Recent pip-audit and CycloneDX SBOM artifacts were found.",
            "Regenerate these artifacts for each deployed install profile.",
            {"pip_audit": pip_state, "sbom": sbom_state, "max_age_days": max_age_days},
        )
    return Check(
        "supply_chain_artifacts",
        "Supply-chain scan artifacts",
        _status_for_profile(profile=profile),
        "Recent pip-audit and CycloneDX SBOM artifacts were not both found.",
        "Generate profile-specific artifacts with tools/profile_supply_chain_scan.py --profile all --run, or archive equivalent pip-audit JSON and CycloneDX SBOM files for each deployed profile.",
        {
            "pip_audit": pip_state,
            "sbom": sbom_state,
            "max_age_days": max_age_days,
            "profile": profile,
        },
    )


def build_report(
    *,
    profile: str = "local",
    env_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    home: Path | None = None,
    now: datetime | None = None,
    pip_audit_json: Path | None = None,
    sbom_json: Path | None = None,
    artifact_max_age_days: int = DEFAULT_ARTIFACT_MAX_AGE_DAYS,
) -> dict[str, Any]:
    if profile not in PROFILES:
        raise ValueError(f"unknown security-check profile: {profile}")
    cwd = (cwd or Path.cwd()).resolve()
    home = (home or Path.home()).resolve()
    env_file = (env_file or home / ".agilab" / ".env").expanduser()
    env_file_values = _parse_env_file(env_file)
    config = _merged_config(environ or os.environ, env_file_values)
    now = now or _utc_now()
    checks = [
        _check_apps_repository(config, cwd=cwd, profile=profile),
        _check_persisted_secrets(env_file, env_file_values, profile=profile),
        _check_cluster_share(config, cwd=cwd, profile=profile),
        _check_ui_exposure(config, home=home, profile=profile),
        _check_generated_code_execution(config, profile=profile),
        _check_optional_profiles(config, profile=profile),
        _check_supply_chain_artifacts(
            cwd=cwd,
            now=now,
            pip_audit_json=pip_audit_json,
            sbom_json=sbom_json,
            max_age_days=artifact_max_age_days,
            profile=profile,
        ),
    ]
    warning_count = sum(1 for check in checks if check.status == "warn")
    failure_count = sum(1 for check in checks if check.status == "fail")
    status = "fail" if failure_count else "warn" if warning_count else "pass"
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "agilab.security_check",
        "schema": SCHEMA,
        "status": status,
        "generated_at": now.isoformat(),
        "summary": {
            "check_count": len(checks),
            "warnings": warning_count,
            "failures": failure_count,
            "env_file": str(env_file),
            "advisory": True,
            "profile": profile,
        },
        "checks": [check.as_dict() for check in checks],
    }


def _print_text(report: Mapping[str, Any]) -> None:
    status = str(report.get("status", "unknown")).upper()
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    warnings = summary.get("warnings", 0)
    failures = summary.get("failures", 0)
    profile = summary.get("profile", "local")
    print(
        f"AGILAB security-check: {status} "
        f"({warnings} warning(s), {failures} failure(s), profile={profile})"
    )
    for check in report.get("checks", []):
        if not isinstance(check, dict):
            continue
        marker = str(check.get("status", "unknown")).upper()
        print(f"- [{marker}] {check.get('label')}: {check.get('summary')}")
        if check.get("status") in {"warn", "fail"}:
            print(f"  remediation: {check.get('remediation')}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an advisory AGILAB local security preflight."
    )
    parser.add_argument(
        "--profile",
        choices=PROFILES,
        default="local",
        help=(
            "Adoption profile to evaluate. local is advisory; shared, cluster, "
            "and public-ui promote deployment-boundary risks to failures."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return a non-zero exit code when advisory warnings are found.",
    )
    parser.add_argument("--env-file", type=Path, default=None, help="AGILAB .env file to inspect.")
    parser.add_argument("--pip-audit-json", type=Path, default=None)
    parser.add_argument("--sbom-json", type=Path, default=None)
    parser.add_argument(
        "--artifact-max-age-days",
        type=int,
        default=DEFAULT_ARTIFACT_MAX_AGE_DAYS,
        help="Maximum accepted age for pip-audit/SBOM artifacts.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report(
        profile=args.profile,
        env_file=args.env_file,
        pip_audit_json=args.pip_audit_json,
        sbom_json=args.sbom_json,
        artifact_max_age_days=args.artifact_max_age_days,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_text(report)
    return 1 if args.strict and report["status"] != "pass" else 0


if __name__ == "__main__":
    raise SystemExit(main())
