"""Versioned fingerprints for persistent worker distribution plans."""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import CodeType
from typing import Any


DISTRIBUTION_CACHE_SCHEMA = "agilab.distribution_tree.v2"

_INPUT_PATH_FIELD_NAMES = {
    "data_in",
    "dataset",
    "dataset_dir",
    "dataset_file",
    "dataset_path",
    "inbox",
    "input",
    "input_dir",
    "input_file",
    "input_files",
    "input_path",
    "input_paths",
    "input_root",
    "source_dir",
    "source_file",
    "source_path",
    "source_root",
    "submission_inbox",
}


def _is_input_path_field(name: Any) -> bool:
    normalized = str(name or "").strip().lower()
    return (
        normalized in _INPUT_PATH_FIELD_NAMES
        or normalized.endswith("_data_in")
        or normalized.endswith("_input_dir")
        or normalized.endswith("_input_file")
        or normalized.endswith("_input_path")
        or normalized.endswith("_input_root")
        or normalized.endswith("_inbox")
    )


def _args_payload(args: Any) -> Any:
    model_dump = getattr(args, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="python")
    if isinstance(args, Mapping):
        return args
    values = getattr(args, "__dict__", None)
    return values if isinstance(values, Mapping) else {}


def _iter_declared_paths(value: Any) -> Iterable[Path]:
    if isinstance(value, Path):
        yield value
        return
    if isinstance(value, str):
        stripped = value.strip()
        if stripped and "://" not in stripped:
            yield Path(stripped).expanduser()
        return
    if isinstance(value, Mapping):
        for nested in value.values():
            yield from _iter_declared_paths(nested)
        return
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        for nested in value:
            yield from _iter_declared_paths(nested)


def _discover_input_paths(target_inst: Any) -> list[Path]:
    discovered: list[Path] = []

    def _visit(value: Any) -> None:
        if not isinstance(value, Mapping):
            return
        for field_name, field_value in value.items():
            if _is_input_path_field(field_name):
                discovered.extend(_iter_declared_paths(field_value))
            if isinstance(field_value, Mapping):
                _visit(field_value)

    declared_inputs = getattr(target_inst, "distribution_cache_inputs", None)
    input_mode = getattr(target_inst, "distribution_cache_inputs_mode", "augment")
    if input_mode not in {"augment", "replace"}:
        raise ValueError(
            "distribution_cache_inputs_mode must be 'augment' or 'replace', "
            f"got {input_mode!r}"
        )
    if input_mode == "augment":
        _visit(_args_payload(getattr(target_inst, "args", None)))
    elif declared_inputs is None:
        raise TypeError(
            "distribution_cache_inputs must be defined when "
            "distribution_cache_inputs_mode is 'replace'"
        )

    if declared_inputs is not None:
        if not callable(declared_inputs):
            raise TypeError("distribution_cache_inputs must be callable when defined")
        hook_value = declared_inputs()
        if inspect.isawaitable(hook_value):
            raise TypeError("distribution_cache_inputs must be synchronous")
        discovered.extend(_iter_declared_paths(hook_value))

    unique: dict[str, Path] = {}
    for candidate in discovered:
        resolved = candidate.resolve(strict=False)
        unique[resolved.as_posix()] = resolved
    return [unique[key] for key in sorted(unique)]


def _file_sha256(path: Path) -> tuple[str, Any]:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    before_identity = (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    after_identity = (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    if before_identity != after_identity:
        raise RuntimeError(f"distribution input changed while being fingerprinted: {path}")
    return digest.hexdigest(), after


def _path_fingerprint(path: Path) -> dict[str, Any]:
    root_payload: dict[str, Any] = {"path": path.as_posix()}
    if not path.exists():
        root_payload["kind"] = "missing"
        return root_payload
    if path.is_file():
        digest, stat_result = _file_sha256(path)
        root_payload.update(
            {
                "kind": "file",
                "size": stat_result.st_size,
                "sha256": digest,
            }
        )
        return root_payload
    if not path.is_dir():
        stat_result = path.stat()
        root_payload.update(
            {
                "kind": "other",
                "size": stat_result.st_size,
                "mtime_ns": stat_result.st_mtime_ns,
            }
        )
        return root_payload

    entries: list[dict[str, Any]] = []
    for candidate in sorted(path.rglob("*"), key=lambda item: item.as_posix()):
        relative = candidate.relative_to(path).as_posix()
        if candidate.is_file():
            digest, stat_result = _file_sha256(candidate)
            entries.append(
                {
                    "path": relative,
                    "kind": "file",
                    "size": stat_result.st_size,
                    "sha256": digest,
                }
            )
        elif candidate.is_dir():
            entries.append({"path": relative, "kind": "directory"})
        else:
            stat_result = candidate.stat()
            entries.append(
                {
                    "path": relative,
                    "kind": "other",
                    "size": stat_result.st_size,
                    "mtime_ns": stat_result.st_mtime_ns,
                }
            )
    root_payload.update({"kind": "directory", "entries": entries})
    return root_payload


def _stable_code_constant(value: Any) -> Any:
    if isinstance(value, CodeType):
        return {
            "kind": "code",
            "bytecode": value.co_code.hex(),
            "names": list(value.co_names),
            "constants": [_stable_code_constant(item) for item in value.co_consts],
        }
    if isinstance(value, tuple):
        return {
            "kind": "tuple",
            "items": [_stable_code_constant(item) for item in value],
        }
    if isinstance(value, frozenset):
        items = [_stable_code_constant(item) for item in value]
        return {
            "kind": "frozenset",
            "items": sorted(
                items,
                key=lambda item: json.dumps(item, sort_keys=True),
            ),
        }
    if isinstance(value, bytes):
        return {"kind": "bytes", "hex": value.hex()}
    if value is Ellipsis:
        return {"kind": "ellipsis"}
    if value is None or isinstance(value, (bool, int, float, complex, str)):
        return {"kind": type(value).__name__, "value": repr(value)}
    return {"kind": type(value).__name__}


def _planner_fingerprint(target_inst: Any) -> dict[str, str]:
    planner = target_inst.build_distribution
    callable_obj = getattr(planner, "__func__", planner)
    digest = hashlib.sha256()
    digest.update(
        f"{type(target_inst).__module__}.{type(target_inst).__qualname__}".encode(
            "utf-8"
        )
    )

    try:
        callable_source = inspect.getsource(callable_obj)
    except (OSError, TypeError):
        callable_source = None
    if callable_source is not None:
        digest.update(callable_source.encode("utf-8"))
    else:
        code = getattr(callable_obj, "__code__", None)
        if code is not None:
            code_payload = {
                "bytecode": code.co_code.hex(),
                "names": list(code.co_names),
                "constants": [
                    _stable_code_constant(value) for value in code.co_consts
                ],
            }
            digest.update(
                json.dumps(code_payload, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            )

    source_path_raw = inspect.getsourcefile(callable_obj)
    source_path = Path(source_path_raw).resolve() if source_path_raw else None
    if source_path is not None and source_path.is_file():
        source_digest, _stat_result = _file_sha256(source_path)
        digest.update(source_digest.encode("ascii"))

    return {
        "callable": f"{callable_obj.__module__}.{callable_obj.__qualname__}",
        "sha256": digest.hexdigest(),
    }


def build_cache_context(
    target_inst: Any,
    *,
    capacities: Iterable[float] | None,
) -> dict[str, Any]:
    """Return the deterministic context that makes a cached plan reusable."""

    input_roots = _discover_input_paths(target_inst)
    input_fingerprints = [_path_fingerprint(path) for path in input_roots]
    input_digest = hashlib.sha256(
        json.dumps(
            input_fingerprints,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    payload = {
        "planner": _planner_fingerprint(target_inst),
        "inputs": {
            "roots": [path.as_posix() for path in input_roots],
            "digest_sha256": input_digest,
        },
        "capacities": [] if capacities is None else [float(value) for value in capacities],
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {**payload, "digest_sha256": digest}


__all__ = ["DISTRIBUTION_CACHE_SCHEMA", "build_cache_context"]
