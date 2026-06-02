"""Dependency-light audience bridge commands for AGILAB evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
import time
from typing import Any, Callable, Mapping, Sequence

from agilab import run_manifest

try:
    from agilab.security.secret_uri import redact_mapping, redact_text
except Exception:  # pragma: no cover - standalone fallback

    def redact_text(text: object) -> str:
        return str(text)

    def redact_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
        return {str(key): value for key, value in values.items()}


Runner = Callable[..., subprocess.CompletedProcess[str]]
NotebookExecutor = Callable[
    [Path, Path, Path, Path, Mapping[str, Any], int, str | None, bool],
    Mapping[str, Any],
]
SCHEMA_PREFIX = "agilab.bridge"
_TEXT_EXTENSIONS = {
    ".cfg",
    ".env",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".qmd",
    ".r",
    ".rst",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b("
    r"OPENAI_API_KEY|ANTHROPIC_API_KEY|HF_TOKEN|HUGGINGFACE_TOKEN|"
    r"AGILAB_[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|KEY)|"
    r"[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|CREDENTIAL)[A-Z0-9_]*"
    r")\s*=\s*['\"]?([^'\"\s]+)"
)
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _read_json_if_present(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    return _read_json(path)


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def _repo_root(start: Path | None = None) -> Path:
    base = (start or Path.cwd()).resolve(strict=False)
    for candidate in (base, *base.parents):
        if (candidate / "pyproject.toml").is_file() and (
            candidate / "src" / "agilab"
        ).is_dir():
            return candidate
    return Path.cwd().resolve(strict=False)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_run_manifest(
    path: Path,
) -> tuple[run_manifest.RunManifest, dict[str, Any], Path]:
    resolved = path.expanduser().resolve(strict=False)
    payload = _read_json(resolved)
    return run_manifest.RunManifest.from_dict(payload), payload, resolved


def _resolve_artifact_path(artifact_path: str, manifest_path: Path) -> Path:
    path = Path(artifact_path).expanduser()
    if path.is_absolute():
        return path
    return (manifest_path.parent / path).resolve(strict=False)


def _markdown_cell(value: object) -> str:
    text = str(value if value is not None else "")
    return text.replace("\n", "<br>").replace("|", "\\|")


def _command_text(argv: Sequence[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in argv)


def _safe_identifier(value: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"Unsafe SQL identifier: {value!r}")
    return value


def _notebook_parameter_cell_source(params_path: Path, artifact_dir: Path) -> str:
    return "\n".join(
        [
            "# AGILAB notebook sandbox parameters.",
            "import json",
            "from pathlib import Path",
            f"AGILAB_PARAMS_PATH = Path({str(params_path)!r})",
            f"AGILAB_ARTIFACT_DIR = Path({str(artifact_dir)!r})",
            "AGILAB_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)",
            "AGILAB_PARAMS = json.loads(AGILAB_PARAMS_PATH.read_text(encoding='utf-8'))",
            "for _agilab_key, _agilab_value in AGILAB_PARAMS.items():",
            "    if isinstance(_agilab_key, str) and _agilab_key.isidentifier():",
            "        globals()[_agilab_key] = _agilab_value",
        ]
    )


def _load_notebook_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected notebook JSON object in {path}")
    cells = payload.get("cells")
    if not isinstance(cells, list):
        raise ValueError(f"Expected notebook cells list in {path}")
    return payload


def _ensure_notebook_cell_ids(notebook: dict[str, Any]) -> None:
    cells = notebook.get("cells", [])
    if not isinstance(cells, list):
        return
    used_ids = {
        str(cell.get("id"))
        for cell in cells
        if isinstance(cell, Mapping) and cell.get("id")
    }
    next_id = 1
    for cell in cells:
        if not isinstance(cell, dict) or cell.get("id"):
            continue
        while True:
            candidate = f"agilab-cell-{next_id:04d}"
            next_id += 1
            if candidate not in used_ids:
                cell["id"] = candidate
                used_ids.add(candidate)
                break


def _prepare_notebook_for_sandbox(
    notebook_path: Path,
    prepared_notebook_path: Path,
    *,
    params_path: Path,
    artifact_dir: Path,
) -> None:
    notebook = _load_notebook_json(notebook_path)
    injection_cell = {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {"tags": ["agilab-parameters"]},
        "outputs": [],
        "source": _notebook_parameter_cell_source(params_path, artifact_dir),
    }
    notebook["cells"] = [injection_cell, *notebook["cells"]]
    _ensure_notebook_cell_ids(notebook)
    prepared_notebook_path.write_text(
        json.dumps(notebook, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _execute_notebook_with_nbclient(
    prepared_notebook_path: Path,
    executed_notebook_path: Path,
    work_dir: Path,
    _artifact_dir: Path,
    _params: Mapping[str, Any],
    timeout_seconds: int,
    kernel_name: str | None,
    allow_errors: bool,
) -> Mapping[str, Any]:
    try:
        import nbformat
        from nbclient import NotebookClient
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Notebook sandbox requires optional notebook dependencies. "
            "Install `agilab[notebook]` or run with `uv run --extra notebook`."
        ) from exc

    notebook = nbformat.read(prepared_notebook_path, as_version=4)
    client_kwargs: dict[str, Any] = {
        "timeout": timeout_seconds,
        "resources": {"metadata": {"path": str(work_dir)}},
        "allow_errors": allow_errors,
    }
    if kernel_name:
        client_kwargs["kernel_name"] = kernel_name
    client = NotebookClient(notebook, **client_kwargs)
    try:
        client.execute()
    finally:
        nbformat.write(notebook, executed_notebook_path)
    return {"status": "pass"}


def _text_from_notebook_value(value: object) -> str:
    if isinstance(value, list):
        return "".join(str(item) for item in value)
    return "" if value is None else str(value)


def _extract_notebook_streams(notebook_path: Path) -> dict[str, str]:
    if not notebook_path.is_file():
        return {"stdout": "", "stderr": ""}
    try:
        notebook = _load_notebook_json(notebook_path)
    except Exception:
        return {"stdout": "", "stderr": ""}
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    for cell in notebook.get("cells", []):
        if not isinstance(cell, Mapping):
            continue
        outputs = cell.get("outputs", [])
        if not isinstance(outputs, list):
            continue
        for output in outputs:
            if not isinstance(output, Mapping):
                continue
            output_type = str(output.get("output_type", ""))
            if output_type == "stream":
                text = _text_from_notebook_value(output.get("text"))
                if output.get("name") == "stderr":
                    stderr_parts.append(text)
                else:
                    stdout_parts.append(text)
            elif output_type == "error":
                traceback = output.get("traceback")
                if isinstance(traceback, list):
                    stderr_parts.append("\n".join(str(line) for line in traceback))
                else:
                    stderr_parts.append(_text_from_notebook_value(output.get("evalue")))
    return {"stdout": "".join(stdout_parts), "stderr": "".join(stderr_parts)}


def _notebook_artifact_rows(artifact_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not artifact_dir.exists():
        return rows
    for path in sorted(artifact_dir.rglob("*")):
        if not path.is_file():
            continue
        rows.append(
            {
                "path": str(path),
                "relative_path": path.relative_to(artifact_dir).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return rows


def _redact_exception(exc: BaseException) -> str:
    return redact_text(f"{exc.__class__.__name__}: {exc}")


def _redact_notebook_json_value(value: object) -> object:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [_redact_notebook_json_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _redact_notebook_json_value(item) for key, item in value.items()
        }
    return value


def _redact_notebook_text_fields(path: Path) -> None:
    if not path.is_file():
        return
    try:
        notebook = _load_notebook_json(path)
    except Exception:
        return
    for cell in notebook.get("cells", []):
        if not isinstance(cell, dict):
            continue
        if "source" in cell:
            cell["source"] = _redact_notebook_json_value(cell["source"])
        outputs = cell.get("outputs", [])
        if not isinstance(outputs, list):
            continue
        for output in outputs:
            if not isinstance(output, dict):
                continue
            for key in ("text", "evalue", "traceback", "data"):
                if key in output:
                    output[key] = _redact_notebook_json_value(output[key])
    path.write_text(
        json.dumps(notebook, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _artifact_rows(
    manifest: run_manifest.RunManifest,
    manifest_path: Path,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for artifact in manifest.artifacts:
        artifact_path = _resolve_artifact_path(artifact.path, manifest_path)
        exists = artifact_path.exists()
        rows.append(
            {
                "name": artifact.name,
                "kind": artifact.kind,
                "path": str(artifact_path),
                "exists": exists,
                "size_bytes": artifact_path.stat().st_size
                if exists and artifact_path.is_file()
                else artifact.size_bytes,
                "sha256": _sha256(artifact_path)
                if exists and artifact_path.is_file()
                else "",
            }
        )
    return rows


def _manifest_metrics(manifest: run_manifest.RunManifest) -> dict[str, float]:
    metrics: dict[str, float] = {
        "duration_seconds": float(manifest.timing.duration_seconds),
        "artifact_count": float(len(manifest.artifacts)),
        "validation_count": float(len(manifest.validations)),
        "validation_pass_count": float(
            sum(1 for validation in manifest.validations if validation.status == "pass")
        ),
    }
    for validation in manifest.validations:
        prefix = re.sub(r"[^A-Za-z0-9_]+", "_", validation.label).strip("_").lower()
        for key, value in validation.details.items():
            if isinstance(value, bool):
                metrics[f"{prefix}_{key}"] = 1.0 if value else 0.0
            elif isinstance(value, int | float):
                metrics[f"{prefix}_{key}"] = float(value)
    return metrics


def build_quarto_report_markdown(
    manifest: run_manifest.RunManifest,
    manifest_path: Path,
) -> str:
    summary = run_manifest.manifest_summary(manifest)
    artifact_rows = _artifact_rows(manifest, manifest_path)
    validation_rows = [
        {
            "label": validation.label,
            "status": validation.status,
            "summary": validation.summary,
        }
        for validation in manifest.validations
    ]
    command = _command_text(manifest.command.argv)
    environment = manifest.environment
    lines = [
        "---",
        f'title: "AGILAB Run Report: {manifest.label or manifest.run_id}"',
        "format: html",
        "---",
        "",
        "# Run summary",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Run ID | `{_markdown_cell(manifest.run_id)}` |",
        f"| Label | {_markdown_cell(manifest.label)} |",
        f"| Status | `{_markdown_cell(manifest.status)}` |",
        f"| Path ID | `{_markdown_cell(manifest.path_id)}` |",
        f"| Duration | `{summary['duration_seconds']}` seconds |",
        f"| Manifest | `{_markdown_cell(manifest_path)}` |",
        "",
        "# Command",
        "",
        "```bash",
        command,
        "```",
        "",
        "# Environment",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| App | `{_markdown_cell(environment.app_name)}` |",
        f"| Active app | `{_markdown_cell(environment.active_app)}` |",
        f"| Repository | `{_markdown_cell(environment.repo_root)}` |",
        f"| Python | `{_markdown_cell(environment.python_version)}` |",
        f"| Platform | `{_markdown_cell(environment.platform)}` |",
        "",
        "# Validations",
        "",
        "| Label | Status | Summary |",
        "|---|---|---|",
    ]
    if validation_rows:
        lines.extend(
            f"| {_markdown_cell(row['label'])} | `{_markdown_cell(row['status'])}` | {_markdown_cell(row['summary'])} |"
            for row in validation_rows
        )
    else:
        lines.append("| - | - | No validation rows recorded. |")

    lines.extend(
        [
            "",
            "# Artifacts",
            "",
            "| Name | Kind | Exists | Size | SHA-256 | Path |",
            "|---|---|---:|---:|---|---|",
        ]
    )
    if artifact_rows:
        lines.extend(
            (
                f"| {_markdown_cell(row['name'])} | {_markdown_cell(row['kind'])} | "
                f"{'yes' if row['exists'] else 'no'} | {_markdown_cell(row['size_bytes'])} | "
                f"`{_markdown_cell(row['sha256'])}` | `{_markdown_cell(row['path'])}` |"
            )
            for row in artifact_rows
        )
    else:
        lines.append("| - | - | - | - | - | No artifacts recorded. |")

    metrics = _manifest_metrics(manifest)
    lines.extend(["", "# Metrics", "", "| Name | Value |", "|---|---:|"])
    lines.extend(
        f"| `{_markdown_cell(key)}` | {value} |"
        for key, value in sorted(metrics.items())
    )
    lines.extend(
        [
            "",
            "# Handoff",
            "",
            "AGILAB owns the reproducible execution context. Quarto owns the publishable report.",
            "If MLflow tracking is enabled, keep MLflow as the experiment tracking system and link this report back to the AGILAB manifest.",
            "",
        ]
    )
    return "\n".join(lines)


def export_quarto_report(
    manifest_path: Path,
    output_path: Path,
    *,
    render: bool = False,
    quarto_bin: str = "quarto",
    runner: Runner = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, Any]:
    manifest, manifest_payload, resolved_manifest = _load_run_manifest(manifest_path)
    output = output_path.expanduser().resolve(strict=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        build_quarto_report_markdown(manifest, resolved_manifest), encoding="utf-8"
    )
    copied_manifest = _write_json(output.parent / "manifest.json", manifest_payload)

    render_payload: dict[str, Any] = {
        "requested": render,
        "status": "not_requested",
        "html_path": str(output.with_suffix(".html")),
    }
    if render:
        if which(quarto_bin) is None:
            render_payload.update(
                {
                    "status": "skipped",
                    "reason": f"{quarto_bin!r} was not found on PATH",
                }
            )
        else:
            completed = runner(
                [quarto_bin, "render", str(output)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            render_payload.update(
                {
                    "status": "pass" if completed.returncode == 0 else "fail",
                    "returncode": completed.returncode,
                    "stdout": redact_text(completed.stdout),
                    "stderr": redact_text(completed.stderr),
                }
            )

    payload = {
        "schema": f"{SCHEMA_PREFIX}.quarto_export.v1",
        "status": "pass",
        "manifest_path": str(resolved_manifest),
        "qmd_path": str(output),
        "copied_manifest_path": str(copied_manifest),
        "render": render_payload,
    }
    return payload


def _copy_project_tree(project_path: Path, destination: Path) -> None:
    ignore = shutil.ignore_patterns(
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "*.pyc",
    )
    shutil.copytree(project_path, destination, ignore=ignore)


def _secret_findings(root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or (
            path.suffix.lower() not in _TEXT_EXTENSIONS
            and path.name.lower() not in _TEXT_EXTENSIONS
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "secret://" in text or "vault://" in text:
            findings.append({"path": str(path), "reason": "secret reference URI"})
        for match in _SECRET_ASSIGNMENT_RE.finditer(text):
            if match.group(2).lower() in {
                "<redacted>",
                "redacted",
                "example",
                "changeme",
            }:
                continue
            findings.append(
                {
                    "path": str(path),
                    "reason": f"secret-like assignment {match.group(1)}",
                }
            )
    return findings


def export_hf_space(
    project_path: Path,
    output_dir: Path,
    *,
    evidence_path: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    project = project_path.expanduser().resolve(strict=False)
    if not project.is_dir():
        raise FileNotFoundError(f"Project path does not exist: {project}")
    findings = _secret_findings(project)
    if findings:
        raise RuntimeError(
            f"Cannot export Hugging Face Space with secret-like project inputs: {findings[0]}"
        )

    output = output_dir.expanduser().resolve(strict=False)
    project_dest = output / "agilab_project"
    if output.exists() and any(output.iterdir()) and not force:
        raise FileExistsError(
            f"Output directory is not empty: {output}. Use --force to replace generated files."
        )
    output.mkdir(parents=True, exist_ok=True)
    if project_dest.exists():
        shutil.rmtree(project_dest)
    _copy_project_tree(project, project_dest)

    evidence_dest = None
    if evidence_path is not None:
        evidence = evidence_path.expanduser().resolve(strict=False)
        evidence_dest = output / "evidence"
        if evidence_dest.exists():
            shutil.rmtree(evidence_dest)
        if evidence.is_dir():
            shutil.copytree(evidence, evidence_dest)
        elif evidence.is_file():
            evidence_dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(evidence, evidence_dest / evidence.name)

    (output / "requirements.txt").write_text("agilab[ui]\n", encoding="utf-8")
    (output / "Dockerfile").write_text(
        textwrap.dedent(
            """\
            FROM python:3.13-slim
            WORKDIR /app
            COPY requirements.txt .
            RUN pip install --no-cache-dir -r requirements.txt
            COPY . .
            ENV AGILAB_UI_HOST=0.0.0.0
            ENV AGILAB_PUBLIC_BIND_OK=1
            ENV AGILAB_TLS_TERMINATED=1
            EXPOSE 7860
            CMD ["streamlit", "run", "app.py", "--server.address", "0.0.0.0", "--server.port", "7860"]
            """
        ),
        encoding="utf-8",
    )
    (output / "app.py").write_text(
        textwrap.dedent(
            f"""\
            from pathlib import Path
            import streamlit as st

            st.set_page_config(page_title="AGILAB Space", layout="wide")
            st.title("AGILAB evidence demo")
            st.write("Project: `{project.name}`")
            st.write("This Docker Space packages an AGILAB project and optional sample evidence.")
            st.write("Run AGILAB locally for controlled execution; use this Space as a public inspection surface.")
            project_readme = Path("agilab_project") / "README.md"
            if project_readme.exists():
                st.markdown(project_readme.read_text(encoding="utf-8"))
            """
        ),
        encoding="utf-8",
    )
    (output / "README.md").write_text(
        f"# AGILAB Hugging Face Space\n\nPackaged project: `{project.name}`.\n\n",
        encoding="utf-8",
    )
    manifest = {
        "schema": f"{SCHEMA_PREFIX}.hf_space_export.v1",
        "status": "pass",
        "project_path": str(project),
        "output_dir": str(output),
        "project_copy": str(project_dest),
        "evidence_copy": str(evidence_dest) if evidence_dest else "",
    }
    _write_json(output / "hf_space_manifest.json", manifest)
    return manifest


def export_mlflow_handoff(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest, _, resolved_manifest = _load_run_manifest(manifest_path)
    artifact_rows = _artifact_rows(manifest, resolved_manifest)
    payload = {
        "schema": f"{SCHEMA_PREFIX}.mlflow_export.v1",
        "status": "pass",
        "mlflow_boundary": "MLflow tracks experiments; AGILAB owns reproducible execution evidence.",
        "params": {
            "agilab_run_id": manifest.run_id,
            "agilab_path_id": manifest.path_id,
            "agilab_label": manifest.label,
            "agilab_app": manifest.environment.app_name,
            "agilab_status": manifest.status,
        },
        "metrics": _manifest_metrics(manifest),
        "tags": {
            "agilab.manifest": str(resolved_manifest),
            "agilab.repo_root": manifest.environment.repo_root,
            "agilab.command": _command_text(manifest.command.argv),
        },
        "artifacts": artifact_rows,
    }
    _write_json(output_path.expanduser(), payload)
    return payload | {
        "output_path": str(output_path.expanduser().resolve(strict=False))
    }


def import_mlflow_handoff(
    experiment: str,
    output_path: Path,
    *,
    input_path: Path | None = None,
) -> dict[str, Any]:
    if input_path is None:
        raise RuntimeError(
            "MLflow import MVP requires --input JSON unless the optional MLflow SDK adapter is added."
        )
    source = _read_json(input_path.expanduser())
    runs = source.get("runs")
    if not isinstance(runs, list):
        runs = [source]
    payload = {
        "schema": f"{SCHEMA_PREFIX}.mlflow_import.v1",
        "status": "pass",
        "experiment": experiment,
        "imported_run_count": len(runs),
        "runs": runs,
        "boundary": "Imported MLflow tracking metadata is evidence input, not an AGILAB execution proof by itself.",
    }
    _write_json(output_path.expanduser(), payload)
    return payload | {
        "output_path": str(output_path.expanduser().resolve(strict=False))
    }


def init_vscode_bridge(root: Path, *, force: bool = False) -> dict[str, Any]:
    target = root.expanduser().resolve(strict=False)
    files = {
        target / ".devcontainer" / "devcontainer.json": {
            "name": "AGILAB",
            "image": "mcr.microsoft.com/devcontainers/python:3.13",
            "postCreateCommand": "pip install -e '.[ui,dev]'",
            "customizations": {"vscode": {"extensions": ["ms-python.python"]}},
        },
        target / ".vscode" / "tasks.json": {
            "version": "2.0.0",
            "tasks": [
                {
                    "label": "AGILAB: first proof",
                    "type": "shell",
                    "command": "agilab first-proof --json",
                },
                {"label": "AGILAB: start UI", "type": "shell", "command": "agilab"},
                {
                    "label": "AGILAB: security check",
                    "type": "shell",
                    "command": "agilab security-check --json",
                },
                {
                    "label": "AGILAB: export Quarto report",
                    "type": "shell",
                    "command": "agilab export quarto --run ${input:manifest} --output report.qmd",
                },
            ],
            "inputs": [
                {
                    "id": "manifest",
                    "type": "promptString",
                    "description": "Path to AGILAB run_manifest.json",
                    "default": "~/log/execute/flight_telemetry/run_manifest.json",
                }
            ],
        },
        target / ".vscode" / "launch.json": {
            "version": "0.2.0",
            "configurations": [
                {
                    "name": "AGILAB first proof",
                    "type": "python",
                    "request": "launch",
                    "module": "agilab.lab_run",
                    "args": ["first-proof", "--json"],
                    "console": "integratedTerminal",
                }
            ],
        },
    }
    written: list[str] = []
    for path, payload in files.items():
        if path.exists() and not force:
            raise FileExistsError(
                f"{path} already exists. Use --force to overwrite generated VS Code bridge files."
            )
        _write_json(path, payload)
        written.append(str(path))
    quickstart = target / "AGILAB_QUICKSTART.md"
    if quickstart.exists() and not force:
        raise FileExistsError(
            f"{quickstart} already exists. Use --force to overwrite it."
        )
    quickstart.write_text(
        textwrap.dedent(
            """\
            # AGILAB Quickstart

            Start with the VS Code task `AGILAB: first proof`.

            Useful commands:

            - `agilab first-proof --json`
            - `agilab export quarto --run path/to/run_manifest.json --output report.qmd`
            - `agilab security-check --json`
            - `agilab`
            """
        ),
        encoding="utf-8",
    )
    written.append(str(quickstart))
    return {
        "schema": f"{SCHEMA_PREFIX}.vscode_init.v1",
        "status": "pass",
        "files": written,
    }


def run_notebook_sandbox(
    notebook_path: Path,
    output_dir: Path,
    *,
    params_path: Path | None = None,
    timeout_seconds: int = 600,
    kernel_name: str | None = None,
    allow_errors: bool = False,
    executor: NotebookExecutor | None = None,
) -> dict[str, Any]:
    notebook = notebook_path.expanduser().resolve(strict=False)
    output = output_dir.expanduser().resolve(strict=False)
    artifact_dir = output / "artifacts"
    output.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    params_source = (
        params_path.expanduser().resolve(strict=False) if params_path else None
    )
    params: dict[str, Any] = {}
    sandbox_params = output / "params.json"
    prepared_notebook = output / "prepared_notebook.ipynb"
    executed_notebook = output / "executed_notebook.ipynb"
    stdout_log = output / "stdout.log"
    stderr_log = output / "stderr.log"
    evidence_path = output / "notebook_sandbox_evidence.json"
    manifest_path = run_manifest.run_manifest_path(output)

    started_at = run_manifest.utc_now()
    started_monotonic = time.monotonic()
    status = "pass"
    error = ""
    execution_payload: Mapping[str, Any] = {}

    argv = [
        "agilab",
        "run",
        "notebook",
        "--notebook",
        str(notebook),
        "--output",
        str(output),
        "--timeout",
        str(timeout_seconds),
    ]
    if params_source is not None:
        argv.extend(["--params", str(params_source)])
    if kernel_name:
        argv.extend(["--kernel-name", kernel_name])
    if allow_errors:
        argv.append("--allow-errors")

    try:
        params = _read_json_if_present(params_source)
        _write_json(sandbox_params, params)
        _prepare_notebook_for_sandbox(
            notebook,
            prepared_notebook,
            params_path=sandbox_params,
            artifact_dir=artifact_dir,
        )
        notebook_executor = executor or _execute_notebook_with_nbclient
        execution_payload = notebook_executor(
            prepared_notebook,
            executed_notebook,
            output,
            artifact_dir,
            params,
            timeout_seconds,
            kernel_name,
            allow_errors,
        )
        if str(execution_payload.get("status", "pass")).lower() not in {
            "pass",
            "ok",
            "success",
        }:
            status = "fail"
    except Exception as exc:  # keep failed notebooks inspectable as evidence
        status = "fail"
        error = _redact_exception(exc)
        if prepared_notebook.is_file() and not executed_notebook.is_file():
            shutil.copy2(prepared_notebook, executed_notebook)
    finally:
        _redact_notebook_text_fields(prepared_notebook)
        _redact_notebook_text_fields(executed_notebook)

    streams = _extract_notebook_streams(executed_notebook)
    stdout_parts = [streams["stdout"]]
    stderr_parts = [streams["stderr"]]
    if execution_payload.get("stdout"):
        stdout_parts.append(str(execution_payload["stdout"]))
    if execution_payload.get("stderr"):
        stderr_parts.append(str(execution_payload["stderr"]))
    if error:
        stderr_parts.append(error)
    stdout_log.write_text(redact_text("\n".join(stdout_parts)), encoding="utf-8")
    stderr_log.write_text(redact_text("\n".join(stderr_parts)), encoding="utf-8")

    artifact_rows = _notebook_artifact_rows(artifact_dir)
    duration_seconds = round(time.monotonic() - started_monotonic, 6)
    finished_at = run_manifest.utc_now()
    payload: dict[str, Any] = {
        "schema": f"{SCHEMA_PREFIX}.notebook_sandbox.v1",
        "status": status,
        "security_boundary": (
            "Jupyter execution uses a kernel/process boundary for evidence "
            "capture; it is not hostile-code isolation."
        ),
        "notebook_path": str(notebook),
        "prepared_notebook_path": str(prepared_notebook),
        "executed_notebook_path": str(executed_notebook),
        "params_path": str(params_source) if params_source else "",
        "sandbox_params_path": str(sandbox_params),
        "output_dir": str(output),
        "artifact_dir": str(artifact_dir),
        "stdout_log": str(stdout_log),
        "stderr_log": str(stderr_log),
        "run_manifest_path": str(manifest_path),
        "params": redact_mapping(params),
        "artifacts": artifact_rows,
        "execution": {
            "timeout_seconds": timeout_seconds,
            "kernel_name": kernel_name or "",
            "allow_errors": allow_errors,
            "duration_seconds": duration_seconds,
            "error": error,
        },
    }
    _write_json(evidence_path, payload)

    manifest_artifacts = [
        run_manifest.RunManifestArtifact.from_path(
            sandbox_params, name="notebook-params", kind="json"
        ),
        run_manifest.RunManifestArtifact.from_path(
            prepared_notebook, name="prepared-notebook", kind="notebook"
        ),
        run_manifest.RunManifestArtifact.from_path(
            executed_notebook, name="executed-notebook", kind="notebook"
        ),
        run_manifest.RunManifestArtifact.from_path(
            stdout_log, name="stdout", kind="log"
        ),
        run_manifest.RunManifestArtifact.from_path(
            stderr_log, name="stderr", kind="log"
        ),
        run_manifest.RunManifestArtifact.from_path(
            artifact_dir, name="notebook-artifacts", kind="directory"
        ),
        run_manifest.RunManifestArtifact.from_path(
            evidence_path, name="notebook-sandbox-evidence", kind="json"
        ),
    ]
    manifest = run_manifest.build_run_manifest(
        path_id="notebook-sandbox",
        label=f"Notebook sandbox: {notebook.name}",
        status=status,
        command=run_manifest.RunManifestCommand(
            label="agilab run notebook",
            argv=tuple(argv),
            cwd=str(output),
            env_overrides={},
        ),
        environment=run_manifest.RunManifestEnvironment(
            python_version=platform.python_version(),
            python_executable=sys.executable,
            platform=platform.platform(),
            repo_root=str(_repo_root(notebook.parent)),
            active_app=str(notebook),
            app_name=notebook.stem,
        ),
        timing=run_manifest.RunManifestTiming(
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration_seconds,
            target_seconds=float(timeout_seconds),
        ),
        artifacts=manifest_artifacts,
        validations=[
            run_manifest.RunManifestValidation(
                label="notebook execution",
                status=status,
                summary=(
                    "Notebook executed and evidence was captured."
                    if status == "pass"
                    else "Notebook execution failed; failure evidence was captured."
                ),
                details={
                    "artifact_count": len(artifact_rows),
                    "allow_errors": allow_errors,
                    "has_error": bool(error),
                },
            )
        ],
    )
    run_manifest.write_run_manifest(manifest, manifest_path)
    return payload


def run_duckdb_query(
    query_path: Path,
    output_dir: Path,
    *,
    input_path: Path | None = None,
    params_path: Path | None = None,
    table_name: str = "input_data",
    plan_only: bool = False,
    duckdb_module: Any | None = None,
) -> dict[str, Any]:
    query_file = query_path.expanduser().resolve(strict=False)
    query = query_file.read_text(encoding="utf-8")
    output = output_dir.expanduser().resolve(strict=False)
    output.mkdir(parents=True, exist_ok=True)
    params = _read_json(params_path.expanduser()) if params_path else {}
    safe_table_name = _safe_identifier(table_name)
    base_payload = {
        "schema": f"{SCHEMA_PREFIX}.duckdb_run.v1",
        "query_path": str(query_file),
        "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "input_path": str(input_path.expanduser().resolve(strict=False))
        if input_path
        else "",
        "params": redact_mapping(params),
        "output_dir": str(output),
    }
    if plan_only:
        payload = base_payload | {"status": "planned", "reason": "plan-only requested"}
        _write_json(output / "duckdb_manifest.json", payload)
        return payload

    if duckdb_module is None:
        try:
            import duckdb as duckdb_module  # type: ignore[no-redef]
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "DuckDB bridge requires the optional `duckdb` package or --plan-only."
            ) from exc

    connection = duckdb_module.connect(database=":memory:")
    if input_path is not None:
        source = input_path.expanduser().resolve(strict=False)
        suffix = source.suffix.lower()
        if suffix == ".csv":
            connection.execute(
                f"CREATE VIEW {safe_table_name} AS SELECT * FROM read_csv_auto(?)",
                [str(source)],
            )
        elif suffix in {".parquet", ".pq"}:
            connection.execute(
                f"CREATE VIEW {safe_table_name} AS SELECT * FROM read_parquet(?)",
                [str(source)],
            )
        elif suffix in {".json", ".jsonl", ".ndjson"}:
            connection.execute(
                f"CREATE VIEW {safe_table_name} AS SELECT * FROM read_json_auto(?)",
                [str(source)],
            )
        else:
            raise ValueError(f"Unsupported DuckDB input format: {source.suffix}")
    cursor = connection.execute(query, params or None)
    rows = cursor.fetchall()
    columns = [item[0] for item in (cursor.description or [])]
    result_json = [dict(zip(columns, row, strict=False)) for row in rows]
    csv_path = output / "result.csv"
    json_path = output / "result.json"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(result_json)
    _write_json(json_path, {"columns": columns, "rows": result_json})
    payload = base_payload | {
        "status": "pass",
        "row_count": len(rows),
        "columns": columns,
        "result_csv": str(csv_path),
        "result_json": str(json_path),
        "result_sha256": _sha256(json_path),
    }
    _write_json(output / "duckdb_manifest.json", payload)
    return payload


def export_airflow_dag(
    manifest_path: Path, output_path: Path, *, dag_id: str = "agilab_replay"
) -> dict[str, Any]:
    manifest, _, resolved_manifest = _load_run_manifest(manifest_path)
    command = _command_text(manifest.command.argv)
    cwd = shlex.quote(manifest.command.cwd or ".")
    dag_text = textwrap.dedent(
        f"""\
        from __future__ import annotations

        import pendulum
        from airflow import DAG
        from airflow.operators.bash import BashOperator

        with DAG(
            dag_id={dag_id!r},
            start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
            schedule=None,
            catchup=False,
            tags=["agilab", "handoff"],
        ) as dag:
            BashOperator(
                task_id="replay_agilab_command",
                bash_command={f"cd {cwd} && {command}"!r},
            )
        """
    )
    output = output_path.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(dag_text, encoding="utf-8")
    payload = {
        "schema": f"{SCHEMA_PREFIX}.airflow_export.v1",
        "status": "pass",
        "manifest_path": str(resolved_manifest),
        "dag_path": str(output.resolve(strict=False)),
        "dag_id": dag_id,
    }
    _write_json(output.with_suffix(".json"), payload)
    return payload


def export_dagster_job(
    manifest_path: Path, output_path: Path, *, job_name: str = "agilab_replay_job"
) -> dict[str, Any]:
    manifest, _, resolved_manifest = _load_run_manifest(manifest_path)
    argv = list(manifest.command.argv)
    cwd = manifest.command.cwd or None
    job_text = textwrap.dedent(
        f"""\
        from __future__ import annotations

        import subprocess
        from dagster import job, op

        @op
        def replay_agilab_command():
            completed = subprocess.run({argv!r}, cwd={cwd!r}, check=False)
            if completed.returncode:
                raise RuntimeError(f"AGILAB replay failed with {{completed.returncode}}")

        @job(name={job_name!r})
        def agilab_job():
            replay_agilab_command()
        """
    )
    output = output_path.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(job_text, encoding="utf-8")
    payload = {
        "schema": f"{SCHEMA_PREFIX}.dagster_export.v1",
        "status": "pass",
        "manifest_path": str(resolved_manifest),
        "job_path": str(output.resolve(strict=False)),
        "job_name": job_name,
    }
    _write_json(output.with_suffix(".json"), payload)
    return payload


def _emit(payload: Mapping[str, Any], *, json_output: bool = False) -> int:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(payload.get("status", "pass"))
        for key, value in payload.items():
            if key not in {"status", "schema"}:
                print(f"{key}: {value}")
    return 0 if payload.get("status") in {"pass", "planned"} else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AGILAB bridge commands.")
    subparsers = parser.add_subparsers(dest="group", required=True)

    export = subparsers.add_parser("export")
    export_sub = export.add_subparsers(dest="bridge", required=True)
    quarto = export_sub.add_parser("quarto")
    quarto.add_argument("--run", "--manifest", dest="manifest", required=True)
    quarto.add_argument("--output", required=True)
    quarto.add_argument("--render", action="store_true")
    quarto.add_argument("--quarto-bin", default="quarto")
    quarto.add_argument("--json", action="store_true")

    hf = export_sub.add_parser("hf-space")
    hf.add_argument("--project", required=True)
    hf.add_argument("--output", required=True)
    hf.add_argument("--evidence")
    hf.add_argument("--force", action="store_true")
    hf.add_argument("--json", action="store_true")

    mlflow_export = export_sub.add_parser("mlflow")
    mlflow_export.add_argument("--run", "--manifest", dest="manifest", required=True)
    mlflow_export.add_argument("--output", required=True)
    mlflow_export.add_argument("--json", action="store_true")

    airflow = export_sub.add_parser("airflow-dag")
    airflow.add_argument("--run", "--manifest", dest="manifest", required=True)
    airflow.add_argument("--output", required=True)
    airflow.add_argument("--dag-id", default="agilab_replay")
    airflow.add_argument("--json", action="store_true")

    dagster = export_sub.add_parser("dagster-job")
    dagster.add_argument("--run", "--manifest", dest="manifest", required=True)
    dagster.add_argument("--output", required=True)
    dagster.add_argument("--job-name", default="agilab_replay_job")
    dagster.add_argument("--json", action="store_true")

    run = subparsers.add_parser("run")
    run_sub = run.add_subparsers(dest="bridge", required=True)
    run_quarto = run_sub.add_parser("quarto")
    run_quarto.add_argument("--run", "--manifest", dest="manifest", required=True)
    run_quarto.add_argument("--output", required=True)
    run_quarto.add_argument("--no-render", action="store_true")
    run_quarto.add_argument("--quarto-bin", default="quarto")
    run_quarto.add_argument("--json", action="store_true")

    duckdb = run_sub.add_parser("duckdb")
    duckdb.add_argument("--query", required=True)
    duckdb.add_argument("--input")
    duckdb.add_argument("--params")
    duckdb.add_argument("--output", required=True)
    duckdb.add_argument("--table-name", default="input_data")
    duckdb.add_argument("--plan-only", action="store_true")
    duckdb.add_argument("--json", action="store_true")

    notebook = run_sub.add_parser("notebook")
    notebook.add_argument("--notebook", required=True)
    notebook.add_argument("--params")
    notebook.add_argument("--output", required=True)
    notebook.add_argument("--timeout", type=int, default=600)
    notebook.add_argument("--kernel-name")
    notebook.add_argument("--allow-errors", action="store_true")
    notebook.add_argument("--json", action="store_true")

    init = subparsers.add_parser("init")
    init_sub = init.add_subparsers(dest="bridge", required=True)
    vscode = init_sub.add_parser("vscode")
    vscode.add_argument("--root", default=".")
    vscode.add_argument("--force", action="store_true")
    vscode.add_argument("--json", action="store_true")

    import_group = subparsers.add_parser("import")
    import_sub = import_group.add_subparsers(dest="bridge", required=True)
    mlflow_import = import_sub.add_parser("mlflow")
    mlflow_import.add_argument("--experiment", required=True)
    mlflow_import.add_argument("--input", required=True)
    mlflow_import.add_argument("--output", required=True)
    mlflow_import.add_argument("--json", action="store_true")

    mcp = subparsers.add_parser("mcp")
    mcp.add_argument("args", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.group == "export" and args.bridge == "quarto":
        return _emit(
            export_quarto_report(
                Path(args.manifest),
                Path(args.output),
                render=args.render,
                quarto_bin=args.quarto_bin,
            ),
            json_output=args.json,
        )
    if args.group == "export" and args.bridge == "hf-space":
        return _emit(
            export_hf_space(
                Path(args.project),
                Path(args.output),
                evidence_path=Path(args.evidence) if args.evidence else None,
                force=args.force,
            ),
            json_output=args.json,
        )
    if args.group == "export" and args.bridge == "mlflow":
        return _emit(
            export_mlflow_handoff(Path(args.manifest), Path(args.output)),
            json_output=args.json,
        )
    if args.group == "export" and args.bridge == "airflow-dag":
        return _emit(
            export_airflow_dag(
                Path(args.manifest), Path(args.output), dag_id=args.dag_id
            ),
            json_output=args.json,
        )
    if args.group == "export" and args.bridge == "dagster-job":
        return _emit(
            export_dagster_job(
                Path(args.manifest), Path(args.output), job_name=args.job_name
            ),
            json_output=args.json,
        )
    if args.group == "run" and args.bridge == "quarto":
        return _emit(
            export_quarto_report(
                Path(args.manifest),
                Path(args.output),
                render=not args.no_render,
                quarto_bin=args.quarto_bin,
            ),
            json_output=args.json,
        )
    if args.group == "run" and args.bridge == "duckdb":
        return _emit(
            run_duckdb_query(
                Path(args.query),
                Path(args.output),
                input_path=Path(args.input) if args.input else None,
                params_path=Path(args.params) if args.params else None,
                table_name=args.table_name,
                plan_only=args.plan_only,
            ),
            json_output=args.json,
        )
    if args.group == "run" and args.bridge == "notebook":
        return _emit(
            run_notebook_sandbox(
                Path(args.notebook),
                Path(args.output),
                params_path=Path(args.params) if args.params else None,
                timeout_seconds=args.timeout,
                kernel_name=args.kernel_name,
                allow_errors=args.allow_errors,
            ),
            json_output=args.json,
        )
    if args.group == "init" and args.bridge == "vscode":
        return _emit(
            init_vscode_bridge(Path(args.root), force=args.force), json_output=args.json
        )
    if args.group == "import" and args.bridge == "mlflow":
        return _emit(
            import_mlflow_handoff(
                args.experiment, Path(args.output), input_path=Path(args.input)
            ),
            json_output=args.json,
        )
    if args.group == "mcp":
        from agilab_mcp import server

        mcp_args = list(args.args)
        if mcp_args[:1] == ["--"]:
            mcp_args = mcp_args[1:]
        return server.main(mcp_args)
    raise SystemExit(
        f"Unsupported bridge command: {args.group} {getattr(args, 'bridge', '')}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
