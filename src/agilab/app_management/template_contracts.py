"""Small TOML contract helpers for AGILAB scaffolding templates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import tomllib


TEMPLATE_CONTRACT_SCHEMA = "agilab.template_contract.v1"
TEMPLATE_CONTRACT_FILENAME = "agilab.template.toml"


@dataclass(frozen=True, slots=True)
class TemplateContract:
    """Parsed template contract metadata."""

    schema: str
    kind: str
    template_version: int
    package_name_pattern: str
    entrypoint: str
    required_files: tuple[str, ...] = ()


def load_template_contract(path: str | Path) -> TemplateContract:
    """Load a template contract from TOML."""

    contract_path = Path(path)
    data = tomllib.loads(contract_path.read_text(encoding="utf-8"))
    files = data.get("files", {})
    required = files.get("required", ()) if isinstance(files, dict) else ()
    return TemplateContract(
        schema=str(data.get("schema", "")).strip(),
        kind=str(data.get("kind", "")).strip(),
        template_version=_coerce_int(data.get("template_version", 0)),
        package_name_pattern=str(data.get("package_name_pattern", "")).strip(),
        entrypoint=str(data.get("entrypoint", "")).strip(),
        required_files=tuple(str(item).strip() for item in required if str(item).strip()),
    )


def contract_path_for(root_path: str | Path) -> Path:
    """Return the conventional contract path for a template or bundle root."""

    return Path(root_path) / TEMPLATE_CONTRACT_FILENAME


def load_optional_template_contract(root_path: str | Path) -> tuple[Path | None, TemplateContract | None]:
    """Load a contract when present below ``root_path``."""

    path = contract_path_for(root_path)
    if not path.is_file():
        return None, None
    resolved = path.resolve(strict=False)
    return resolved, load_template_contract(resolved)


def missing_required_files(root_path: str | Path, contract: TemplateContract) -> tuple[str, ...]:
    """Return required contract files absent from ``root_path``."""

    root = Path(root_path)
    missing: list[str] = []
    for rel_path in contract.required_files:
        if not (root / rel_path).is_file():
            missing.append(rel_path)
    return tuple(missing)


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
