import json
from importlib.metadata import PackageNotFoundError
from importlib.metadata import distribution as pkg_distribution
from pathlib import Path
from urllib.parse import unquote, urlparse

from agi_cluster.agi_distributor.deployment_stage_cache_support import (
    _deploy_stage_project_inputs,
)


def _is_python_project(path: Path) -> bool:
    return path.is_dir() and any(
        (path / marker).exists() for marker in ("pyproject.toml", "setup.py")
    )


def _resolve_distribution_install_spec(
    package_name: str,
    *,
    distribution_fn=pkg_distribution,
) -> str | None:
    try:
        distribution = distribution_fn(package_name)
    except PackageNotFoundError:
        return None

    direct_url_text = distribution.read_text("direct_url.json")
    if direct_url_text:
        try:
            direct_url = json.loads(direct_url_text)
        except json.JSONDecodeError:
            direct_url = None
        if isinstance(direct_url, dict):
            raw_url = direct_url.get("url")
            subdirectory = direct_url.get("subdirectory")
            if isinstance(raw_url, str) and raw_url:
                parsed = urlparse(raw_url)
                if parsed.scheme == "file":
                    local_path = Path(unquote(parsed.path))
                    if _is_python_project(local_path):
                        return str(local_path)

                vcs_info = direct_url.get("vcs_info")
                if isinstance(vcs_info, dict):
                    vcs = vcs_info.get("vcs")
                    if isinstance(vcs, str) and vcs:
                        spec = f"{package_name} @ {vcs}+{raw_url}"
                        requested_revision = vcs_info.get(
                            "requested_revision"
                        ) or vcs_info.get("commit_id")
                        if isinstance(requested_revision, str) and requested_revision:
                            spec += f"@{requested_revision}"
                        if isinstance(subdirectory, str) and subdirectory:
                            spec += f"#subdirectory={subdirectory}"
                        return spec

                spec = f"{package_name} @ {raw_url}"
                if isinstance(subdirectory, str) and subdirectory:
                    spec += f"#subdirectory={subdirectory}"
                return spec

    return f"{package_name}=={distribution.version}"


def _resolve_install_spec(project_path: Path | None, package_name: str) -> str | None:
    if isinstance(project_path, Path) and _is_python_project(project_path):
        return str(project_path)
    return _resolve_distribution_install_spec(package_name)


def _is_local_project_install_spec(spec: str) -> bool:
    try:
        return _is_python_project(Path(spec).expanduser())
    except (OSError, ValueError):
        return False


def _build_worker_core_add_commands(
    uv_worker: str,
    wenv_abs: Path,
    specs: list[str],
    *,
    offline_flag: str = "",
    prefix: str = "",
) -> list[str]:
    editable_specs = []
    normal_specs = []
    for spec in specs:
        if _is_local_project_install_spec(spec):
            editable_specs.append(spec)
        else:
            normal_specs.append(spec)
    commands = []

    if editable_specs:
        quoted_specs = " ".join(f'"{spec}"' for spec in editable_specs)
        commands.append(
            f"{prefix}{uv_worker} {offline_flag}--project {wenv_abs} add --editable {quoted_specs}"
        )

    if normal_specs:
        quoted_specs = " ".join(f'"{spec}"' for spec in normal_specs)
        commands.append(
            f"{prefix}{uv_worker} {offline_flag}--project {wenv_abs} add {quoted_specs}"
        )

    return commands


def _deploy_stage_inputs_for_specs(specs: list[str]) -> list[Path]:
    projects: list[Path] = []
    for spec in specs:
        if _is_local_project_install_spec(spec):
            projects.append(Path(spec).expanduser())
    return _deploy_stage_project_inputs(*projects)
