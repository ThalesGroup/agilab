"""Kubernetes Job manifest support for AGILAB.

This module keeps the first Kubernetes integration deliberately small: build a
portable ``batch/v1`` Job manifest that runs an AGILAB command in a container.
It does not install Helm charts, manage clusters, or mutate Kubernetes state.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


SCHEMA = "agilab.kubernetes_job.v1"
DEFAULT_COMMAND = (
    "python",
    "-m",
    "agilab.lab_run",
    "first-proof",
    "--json",
    "--max-seconds",
    "60",
)
DEFAULT_MOUNT_PATH = "/agilab/export"
DEFAULT_BACKOFF_LIMIT = 0
DEFAULT_TTL_SECONDS_AFTER_FINISHED = 3600

_DNS_LABEL_MAX_LENGTH = 63
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SAFE_LABEL_VALUE_RE = re.compile(r"[^a-z0-9_.-]+")


@dataclass(frozen=True, slots=True)
class KubernetesJobConfig:
    app: str
    image: str
    namespace: str = "default"
    job_name: str | None = None
    command: tuple[str, ...] = DEFAULT_COMMAND
    env: tuple[tuple[str, str], ...] = ()
    pvc_name: str | None = None
    mount_path: str = DEFAULT_MOUNT_PATH
    service_account: str | None = None
    image_pull_policy: str = "IfNotPresent"
    backoff_limit: int = DEFAULT_BACKOFF_LIMIT
    ttl_seconds_after_finished: int | None = DEFAULT_TTL_SECONDS_AFTER_FINISHED


def kubernetes_name(value: str, *, prefix: str = "agilab") -> str:
    """Return a Kubernetes DNS-label-safe name with a stable truncation hash."""

    raw = str(value or "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9-]+", "-", raw).strip("-")
    if not cleaned:
        cleaned = "job"
    name = f"{prefix}-{cleaned}" if prefix else cleaned
    name = re.sub(r"-+", "-", name).strip("-")
    if len(name) <= _DNS_LABEL_MAX_LENGTH:
        return name

    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    trim_at = _DNS_LABEL_MAX_LENGTH - len(digest) - 1
    return f"{name[:trim_at].rstrip('-')}-{digest}"


def kubernetes_label_value(value: str) -> str:
    """Return a Kubernetes-label-safe value for AGILAB metadata labels."""

    cleaned = _SAFE_LABEL_VALUE_RE.sub("-", str(value or "").strip().lower())
    cleaned = re.sub(r"^[^a-z0-9]+|[^a-z0-9]+$", "", cleaned)
    if not cleaned:
        return "unknown"
    if len(cleaned) <= _DNS_LABEL_MAX_LENGTH:
        return cleaned
    digest = hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:8]
    trim_at = _DNS_LABEL_MAX_LENGTH - len(digest) - 1
    return f"{cleaned[:trim_at].rstrip('-_.')}-{digest}"


def parse_env_assignments(assignments: Sequence[str]) -> tuple[tuple[str, str], ...]:
    env: list[tuple[str, str]] = []
    for assignment in assignments:
        if "=" not in assignment:
            raise ValueError(f"environment assignment must use NAME=VALUE: {assignment!r}")
        name, value = assignment.split("=", 1)
        name = name.strip()
        if not _ENV_NAME_RE.fullmatch(name):
            raise ValueError(f"invalid Kubernetes environment variable name: {name!r}")
        env.append((name, value))
    return tuple(env)


def build_kubernetes_job_manifest(config: KubernetesJobConfig) -> dict[str, Any]:
    if not config.app.strip():
        raise ValueError("app is required")
    if not config.image.strip():
        raise ValueError("image is required")

    command = tuple(str(part) for part in (config.command or DEFAULT_COMMAND) if str(part))
    if not command:
        command = DEFAULT_COMMAND

    job_name = kubernetes_name(config.job_name or config.app)
    app_label = kubernetes_label_value(config.app)
    labels = {
        "app.kubernetes.io/name": "agilab",
        "app.kubernetes.io/component": "kubernetes-job",
        "agilab.thalesgroup.com/app": app_label,
        "agilab.thalesgroup.com/backend": "kubernetes-job",
    }
    annotations = {
        "agilab.thalesgroup.com/schema": SCHEMA,
        "agilab.thalesgroup.com/command": json.dumps(command, separators=(",", ":")),
    }

    env = {
        "AGILAB_ACTIVE_APP": config.app,
        "AGILAB_EXECUTION_BACKEND": "kubernetes-job",
        "AGILAB_EXPORT_DIR": config.mount_path,
    }
    env.update(dict(config.env))

    container: dict[str, Any] = {
        "name": "runner",
        "image": config.image,
        "imagePullPolicy": config.image_pull_policy,
        "command": [command[0]],
        "args": list(command[1:]),
        "env": [{"name": name, "value": value} for name, value in sorted(env.items())],
    }

    pod_spec: dict[str, Any] = {
        "restartPolicy": "Never",
        "containers": [container],
    }
    if config.service_account:
        pod_spec["serviceAccountName"] = config.service_account
    if config.pvc_name:
        container["volumeMounts"] = [
            {"name": "agilab-artifacts", "mountPath": config.mount_path}
        ]
        pod_spec["volumes"] = [
            {
                "name": "agilab-artifacts",
                "persistentVolumeClaim": {"claimName": config.pvc_name},
            }
        ]

    spec: dict[str, Any] = {
        "backoffLimit": int(config.backoff_limit),
        "template": {
            "metadata": {"labels": labels, "annotations": annotations},
            "spec": pod_spec,
        },
    }
    if config.ttl_seconds_after_finished is not None:
        spec["ttlSecondsAfterFinished"] = int(config.ttl_seconds_after_finished)

    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": job_name,
            "namespace": config.namespace,
            "labels": labels,
            "annotations": annotations,
        },
        "spec": spec,
    }


def render_manifest(manifest: Mapping[str, Any], *, output_format: str = "yaml") -> str:
    normalized_format = output_format.lower().strip()
    if normalized_format == "json":
        return json.dumps(manifest, indent=2, sort_keys=False)
    if normalized_format == "yaml":
        return "\n".join(_yaml_lines(manifest))
    raise ValueError(f"unsupported manifest format: {output_format!r}")


def kubectl_apply_command(path: str | Path) -> str:
    return f"kubectl apply -f {Path(path)}"


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


def _yaml_lines(value: Any, *, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, Mapping):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (Mapping, list)):
                lines.append(f"{prefix}{key}:")
                lines.extend(_yaml_lines(item, indent=indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_yaml_scalar(item)}")
        return lines
    if isinstance(value, list):
        if not value:
            return [f"{prefix}[]"]
        lines = []
        for item in value:
            if isinstance(item, Mapping):
                entries = list(item.items())
                if not entries:
                    lines.append(f"{prefix}- {{}}")
                    continue
                first_key, first_value = entries[0]
                if isinstance(first_value, (Mapping, list)):
                    lines.append(f"{prefix}- {first_key}:")
                    lines.extend(_yaml_lines(first_value, indent=indent + 4))
                else:
                    lines.append(f"{prefix}- {first_key}: {_yaml_scalar(first_value)}")
                for key, child in entries[1:]:
                    if isinstance(child, (Mapping, list)):
                        lines.append(f"{prefix}  {key}:")
                        lines.extend(_yaml_lines(child, indent=indent + 4))
                    else:
                        lines.append(f"{prefix}  {key}: {_yaml_scalar(child)}")
            elif isinstance(item, list):
                lines.append(f"{prefix}-")
                lines.extend(_yaml_lines(item, indent=indent + 2))
            else:
                lines.append(f"{prefix}- {_yaml_scalar(item)}")
        return lines
    return [f"{prefix}{_yaml_scalar(value)}"]


def _normalize_command(raw_command: Sequence[str]) -> tuple[str, ...]:
    command = tuple(raw_command)
    if command[:1] == ("--",):
        command = command[1:]
    return command or DEFAULT_COMMAND


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a Kubernetes Job manifest for an AGILAB command."
    )
    parser.add_argument("--app", required=True, help="AGILAB app name used for labels and environment.")
    parser.add_argument("--image", required=True, help="Container image that contains AGILAB and the selected app.")
    parser.add_argument("--namespace", default="default", help="Kubernetes namespace for the Job.")
    parser.add_argument("--job-name", help="Override the generated Kubernetes Job name.")
    parser.add_argument("--service-account", help="Optional Kubernetes service account name.")
    parser.add_argument("--pvc", dest="pvc_name", help="Optional PersistentVolumeClaim used for artifacts.")
    parser.add_argument("--mount-path", default=DEFAULT_MOUNT_PATH, help="Container artifact mount path.")
    parser.add_argument("--image-pull-policy", default="IfNotPresent")
    parser.add_argument("--backoff-limit", type=int, default=DEFAULT_BACKOFF_LIMIT)
    parser.add_argument(
        "--ttl-seconds-after-finished",
        type=int,
        default=DEFAULT_TTL_SECONDS_AFTER_FINISHED,
        help="Kubernetes Job TTL after completion. Use a negative value to omit it.",
    )
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Extra environment variable for the runner container. May be repeated.",
    )
    parser.add_argument("--format", choices=("yaml", "json"), default="yaml")
    parser.add_argument("--output", type=Path, help="Write the manifest to this file instead of stdout.")
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help=(
            "Command to run in the container after '--'. Defaults to "
            "'python -m agilab.lab_run first-proof --json --max-seconds 60'."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(argv or [])
    if raw_argv[:1] == ["manifest"]:
        raw_argv = raw_argv[1:]
    parser = _build_parser()
    args = parser.parse_args(raw_argv)
    try:
        env = parse_env_assignments(args.env)
        ttl = args.ttl_seconds_after_finished
        config = KubernetesJobConfig(
            app=args.app,
            image=args.image,
            namespace=args.namespace,
            job_name=args.job_name,
            command=_normalize_command(args.command),
            env=env,
            pvc_name=args.pvc_name,
            mount_path=args.mount_path,
            service_account=args.service_account,
            image_pull_policy=args.image_pull_policy,
            backoff_limit=args.backoff_limit,
            ttl_seconds_after_finished=None if ttl is not None and ttl < 0 else ttl,
        )
        manifest = build_kubernetes_job_manifest(config)
        rendered = render_manifest(manifest, output_format=args.format)
    except ValueError as exc:
        parser.error(str(exc))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(args.output)
    else:
        print(rendered)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
