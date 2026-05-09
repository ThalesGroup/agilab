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
SECRET_KEY_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)
HEX_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
LOCAL_HOSTS = {"", "127.0.0.1", "localhost", "::1"}
EXPOSED_HOSTS = {"0.0.0.0", "::"}
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


def _check_apps_repository(config: Mapping[str, str], *, cwd: Path) -> Check:
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
            "warn",
            "APPS_REPOSITORY points to a missing path.",
            "Point APPS_REPOSITORY to an allowlisted reviewed checkout, pinned commit, or immutable tag.",
            {"path": str(path)},
        )
    if not path.is_dir():
        return Check(
            "apps_repository_pin",
            "External apps repository pinning",
            "warn",
            "APPS_REPOSITORY is not a directory.",
            "Use a reviewed Git checkout directory for external apps.",
            {"path": str(path)},
        )
    git_state = _git_head_state(path)
    if not git_state.get("is_git_checkout"):
        return Check(
            "apps_repository_pin",
            "External apps repository pinning",
            "warn",
            "APPS_REPOSITORY is not a Git checkout.",
            "Use an allowlisted Git checkout pinned to a commit SHA or immutable tag before shared use.",
            {"path": str(path), **git_state},
        )
    if git_state.get("head_state") == "branch":
        return Check(
            "apps_repository_pin",
            "External apps repository pinning",
            "warn",
            "APPS_REPOSITORY is on a floating branch.",
            "Checkout a reviewed commit SHA or immutable tag before installing external apps in shared environments.",
            {"path": str(path), **git_state},
        )
    return Check(
        "apps_repository_pin",
        "External apps repository pinning",
        "pass",
        "APPS_REPOSITORY is a Git checkout and is not on a floating branch.",
        "Keep the referenced commit reviewed and scanned.",
        {"path": str(path), **git_state},
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


def _check_persisted_secrets(env_file: Path, env_file_values: Mapping[str, str]) -> Check:
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
        "warn",
        "Likely sensitive keys are persisted in the AGILAB env file.",
        "Move these values to a keyring, vault, or short-lived environment variables; avoid command-line secrets.",
        {"env_file": str(env_file), "secret_keys": keys},
    )


def _check_cluster_share(config: Mapping[str, str], *, cwd: Path) -> Check:
    cluster_share = _resolve_path(config.get("AGI_CLUSTER_SHARE"), cwd=cwd)
    local_share = _resolve_path(config.get("AGI_LOCAL_SHARE"), cwd=cwd)
    scheduler = str(config.get("AGI_SCHEDULER_IP") or "").strip()
    workers = str(config.get("AGI_WORKERS") or config.get("AGI_CLUSTER_WORKERS") or "").strip()
    cluster_requested = bool(cluster_share) and (scheduler not in LOCAL_HOSTS or bool(workers))
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
    writable = cluster_share.exists() and os.access(cluster_share, os.W_OK) if cluster_share else False
    same_as_local = bool(cluster_share and local_share and cluster_share.resolve() == local_share.resolve())
    if writable or same_as_local:
        return Check(
            "cluster_share_isolation",
            "Cluster share isolation",
            "warn",
            "Cluster mode appears enabled with a local writable or local-share-equivalent path.",
            "Use a per-user shared mount with explicit worker-side path mapping; do not share one writable directory across users.",
            {
                "cluster_share": str(cluster_share),
                "local_share": str(local_share) if local_share else None,
                "scheduler": scheduler or None,
                "workers_configured": bool(workers),
                "cluster_share_exists": cluster_share.exists(),
                "cluster_share_writable": writable,
                "same_as_local_share": same_as_local,
            },
        )
    return Check(
        "cluster_share_isolation",
        "Cluster share isolation",
        "pass",
        "Cluster mode appears configured without an obviously writable local share.",
        "Validate the worker-side mount contract before running shared workloads.",
        {
            "cluster_share": str(cluster_share),
            "local_share": str(local_share) if local_share else None,
            "scheduler": scheduler or None,
            "workers_configured": bool(workers),
        },
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


def _check_ui_exposure(config: Mapping[str, str], *, home: Path) -> Check:
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
    auth_or_tls = any(
        _truthy(config.get(name))
        for name in (
            "AGILAB_AUTH_REQUIRED",
            "AGILAB_PUBLIC_AUTH",
            "AGILAB_TLS_TERMINATED",
            "STREAMLIT_AUTH_REQUIRED",
        )
    )
    if auth_or_tls:
        return Check(
            "ui_network_exposure",
            "UI network exposure",
            "pass",
            "UI binds publicly but an auth/TLS indicator is configured.",
            "Verify the front-end control is actually enforced before exposing sensitive data.",
            {"host": host, "auth_or_tls_indicator": True},
        )
    return Check(
        "ui_network_exposure",
        "UI network exposure",
        "warn",
        "UI appears configured to bind publicly without an auth/TLS indicator.",
        "Bind to 127.0.0.1, or put AGILAB behind authentication and TLS before shared/public use.",
        {"host": host, "auth_or_tls_indicator": False},
    )


def _check_optional_profiles(config: Mapping[str, str]) -> Check:
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
        {"enabled_keys": sorted(enabled)},
    )


def _check_generated_code_execution(config: Mapping[str, str]) -> Check:
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
    if sandbox in {"process", "container", "vm"}:
        return Check(
            "generated_code_execution_boundary",
            "Generated-code execution boundary",
            "pass",
            "Generated-code auto-run is enabled with an explicit sandbox indicator.",
            "Verify the configured sandbox really limits filesystem, network, CPU, RAM, time, and secrets.",
            {"enabled_keys": sorted(enabled), "sandbox": sandbox},
        )
    return Check(
        "generated_code_execution_boundary",
        "Generated-code execution boundary",
        "warn",
        "Generated-code auto-run is enabled without an explicit sandbox indicator.",
        "Run generated code in a constrained process/container/VM and set AGILAB_GENERATED_CODE_SANDBOX=process|container|vm when that boundary is in place.",
        {"enabled_keys": sorted(enabled), "sandbox": sandbox or None},
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
        "warn",
        "Recent pip-audit and CycloneDX SBOM artifacts were not both found.",
        "Generate profile-specific artifacts with tools/profile_supply_chain_scan.py --profile all --run, or archive equivalent pip-audit JSON and CycloneDX SBOM files for each deployed profile.",
        {"pip_audit": pip_state, "sbom": sbom_state, "max_age_days": max_age_days},
    )


def build_report(
    *,
    env_file: Path | None = None,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    home: Path | None = None,
    now: datetime | None = None,
    pip_audit_json: Path | None = None,
    sbom_json: Path | None = None,
    artifact_max_age_days: int = DEFAULT_ARTIFACT_MAX_AGE_DAYS,
) -> dict[str, Any]:
    cwd = (cwd or Path.cwd()).resolve()
    home = (home or Path.home()).resolve()
    env_file = (env_file or home / ".agilab" / ".env").expanduser()
    env_file_values = _parse_env_file(env_file)
    config = _merged_config(environ or os.environ, env_file_values)
    now = now or _utc_now()
    checks = [
        _check_apps_repository(config, cwd=cwd),
        _check_persisted_secrets(env_file, env_file_values),
        _check_cluster_share(config, cwd=cwd),
        _check_ui_exposure(config, home=home),
        _check_generated_code_execution(config),
        _check_optional_profiles(config),
        _check_supply_chain_artifacts(
            cwd=cwd,
            now=now,
            pip_audit_json=pip_audit_json,
            sbom_json=sbom_json,
            max_age_days=artifact_max_age_days,
        ),
    ]
    warning_count = sum(1 for check in checks if check.status == "warn")
    status = "warn" if warning_count else "pass"
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "agilab.security_check",
        "schema": SCHEMA,
        "status": status,
        "generated_at": now.isoformat(),
        "summary": {
            "check_count": len(checks),
            "warnings": warning_count,
            "env_file": str(env_file),
            "advisory": True,
        },
        "checks": [check.as_dict() for check in checks],
    }


def _print_text(report: Mapping[str, Any]) -> None:
    status = str(report.get("status", "unknown")).upper()
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    warnings = summary.get("warnings", 0)
    print(f"AGILAB security-check: {status} ({warnings} warning(s))")
    for check in report.get("checks", []):
        if not isinstance(check, dict):
            continue
        marker = str(check.get("status", "unknown")).upper()
        print(f"- [{marker}] {check.get('label')}: {check.get('summary')}")
        if check.get("status") == "warn":
            print(f"  remediation: {check.get('remediation')}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an advisory AGILAB local security preflight."
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
