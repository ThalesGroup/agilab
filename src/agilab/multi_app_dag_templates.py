from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DagTemplateOption:
    path: Path
    app_name: str
    label: str
    dag_id: str

    def repo_relative(self, repo_root: Path) -> str:
        try:
            return self.path.resolve(strict=False).relative_to(repo_root.resolve(strict=False)).as_posix()
        except ValueError:
            return str(self.path)


def discover_app_dag_templates(
    repo_root: Path,
    *,
    app_name: str | None = None,
    include_all_when_empty: bool = False,
) -> tuple[DagTemplateOption, ...]:
    builtin_root = repo_root / "src" / "agilab" / "apps" / "builtin"
    if not builtin_root.is_dir():
        return ()

    normalized_app = _normalize_app_name(app_name)
    app_dirs = _candidate_app_dirs(builtin_root, normalized_app)
    options = _discover_from_app_dirs(app_dirs)
    if options or not include_all_when_empty or normalized_app == "":
        return options
    return _discover_from_app_dirs(sorted(path for path in builtin_root.glob("*_project") if path.is_dir()))


def app_dag_template_paths(
    repo_root: Path,
    *,
    app_name: str | None = None,
    include_all_when_empty: bool = False,
) -> list[str]:
    return [
        option.repo_relative(repo_root)
        for option in discover_app_dag_templates(
            repo_root,
            app_name=app_name,
            include_all_when_empty=include_all_when_empty,
        )
    ]


def _candidate_app_dirs(builtin_root: Path, app_name: str) -> list[Path]:
    if app_name:
        candidates = [builtin_root / app_name]
        if not app_name.endswith("_project"):
            candidates.append(builtin_root / f"{app_name}_project")
        return [path for path in candidates if path.is_dir()]
    return sorted(path for path in builtin_root.glob("*_project") if path.is_dir())


def _discover_from_app_dirs(app_dirs: list[Path]) -> tuple[DagTemplateOption, ...]:
    discovered: list[DagTemplateOption] = []
    seen: set[Path] = set()
    for app_dir in app_dirs:
        candidates = [app_dir / "pipeline_view.json"]
        templates_dir = app_dir / "dag_templates"
        if templates_dir.is_dir():
            candidates.extend(sorted(templates_dir.glob("*.json")))
        for path in candidates:
            resolved = path.resolve(strict=False)
            if resolved in seen or not path.is_file():
                continue
            option = _template_option(path, app_dir.name)
            if option is None:
                continue
            seen.add(resolved)
            discovered.append(option)
    return tuple(sorted(discovered, key=lambda option: (option.app_name, option.label, option.path.name)))


def _template_option(path: Path, app_name: str) -> DagTemplateOption | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("schema", "")).strip() != "agilab.multi_app_dag.v1":
        return None
    label = str(payload.get("label", "") or payload.get("dag_id", "") or path.stem).strip()
    dag_id = str(payload.get("dag_id", "") or path.stem).strip()
    return DagTemplateOption(path=path, app_name=app_name, label=label, dag_id=dag_id)


def _normalize_app_name(app_name: str | None) -> str:
    if not app_name:
        return ""
    return Path(str(app_name)).name.strip()


__all__ = [
    "DagTemplateOption",
    "app_dag_template_paths",
    "discover_app_dag_templates",
]
