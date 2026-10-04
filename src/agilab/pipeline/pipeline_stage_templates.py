"""Typed registry for generic Workflow stage templates."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
import math
from typing import Any


PIPELINE_STAGE_TEMPLATE_SCHEMA = "agilab.pipeline_stage_templates.v1"
PIPELINE_STAGE_TEMPLATE_ID_KEY = "template_id"
PIPELINE_STAGE_TEMPLATE_VERSION_KEY = "template_version"
PIPELINE_STAGE_PAYLOAD_SCHEMA = "agilab.pipeline_stage_payload.v1"
PIPELINE_STAGE_STRUCTURED_KEYS = (
    "template_id", "template_version", "template_fingerprint", "template_payload",
    "payload_fingerprint",
)


def _literal_payload(value: Any, *, depth: int = 0) -> Any:
    """Copy values supported by both Python literals and persisted TOML."""
    if depth > 32:
        raise ValueError("Template parameters exceed the supported nesting depth.")
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, list):
        return [_literal_payload(item, depth=depth + 1) for item in value]
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        return {key: _literal_payload(item, depth=depth + 1) for key, item in value.items()}
    raise ValueError("Template parameters must contain finite TOML-compatible literal values.")


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _literal_bindings(code: str) -> list[tuple[str, Any, ast.AST]]:
    bindings = []
    for node in ast.parse(code).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        try:
            value = _literal_payload(ast.literal_eval(node.value))
        except (ValueError, TypeError):
            continue
        bindings.append((node.targets[0].id, value, node.value))
    if len({name for name, _, _ in bindings}) != len(bindings):
        raise ValueError("A template parameter may only be assigned once.")
    return bindings


class PipelineStageTemplateStatus(StrEnum):
    """Template classification for a saved Workflow stage."""

    CURRENT = "current"
    STALE = "stale"
    RAW_PYTHON = "raw_python"


@dataclass(frozen=True, slots=True)
class PipelineStageTemplate:
    """Resolved metadata and default code for one generic Workflow stage."""

    template_id: str
    title: str
    question: str
    code: str
    version: int = 1
    description: str = ""
    runtime: str = "runpy"
    model: str = ""
    tags: tuple[str, ...] = ()
    schema: str = PIPELINE_STAGE_TEMPLATE_SCHEMA

    def __post_init__(self) -> None:
        normalized_id = _normalize_template_id(self.template_id)
        if not normalized_id:
            raise ValueError("Workflow stage template id cannot be empty.")
        normalized_version = _coerce_version(self.version)
        if normalized_version is None or normalized_version < 1:
            raise ValueError("Workflow stage template version must be a positive integer.")
        object.__setattr__(self, "template_id", normalized_id)
        object.__setattr__(self, "title", str(self.title).strip())
        object.__setattr__(self, "question", str(self.question).strip())
        object.__setattr__(self, "code", str(self.code))
        object.__setattr__(self, "version", normalized_version)
        object.__setattr__(self, "description", str(self.description).strip())
        object.__setattr__(self, "runtime", str(self.runtime or "runpy").strip() or "runpy")
        object.__setattr__(self, "model", str(self.model or "").strip())
        object.__setattr__(self, "tags", tuple(str(tag).strip() for tag in self.tags if str(tag).strip()))

    def saved_stage(self, **overrides: Any) -> dict[str, Any]:
        """Return a persisted stage dictionary for this template."""

        stage: dict[str, Any] = {
            "D": self.description or self.title,
            "Q": self.question,
            "M": self.model,
            "C": self.code,
            "R": self.runtime,
            PIPELINE_STAGE_TEMPLATE_ID_KEY: self.template_id,
            PIPELINE_STAGE_TEMPLATE_VERSION_KEY: self.version,
        }
        stage.update(overrides)
        payload = stage.get("template_payload", self.default_payload())
        rendered = self.render(payload)
        # A caller supplying custom Python owns that code. Never replace it by
        # generated Python, even when the caller started from a template.
        if "C" in overrides and str(overrides["C"]) != rendered:
            stage["kind"] = "raw_python"
            return stage
        stage.update(
            kind="template", C=rendered, template_payload=copy.deepcopy(payload),
            template_fingerprint=self.fingerprint,
            payload_fingerprint=_fingerprint(payload),
        )
        return stage

    @property
    def fingerprint(self) -> str:
        """Identify the renderer contract, even if a version was not bumped."""
        return _fingerprint({"id": self.template_id, "version": self.version,
                             "code": self.code, "runtime": self.runtime,
                             "schema": PIPELINE_STAGE_PAYLOAD_SCHEMA})

    def default_payload(self) -> dict[str, Any]:
        return {"schema": PIPELINE_STAGE_PAYLOAD_SCHEMA,
                "parameters": {name: copy.deepcopy(value) for name, value, _ in
                               _literal_bindings(self.code)}}

    def render(self, payload: Any) -> str:
        """Render literal parameters while preserving the registered code shape."""
        if not isinstance(payload, Mapping) or payload.get("schema") != PIPELINE_STAGE_PAYLOAD_SCHEMA:
            raise ValueError("Unsupported or missing pipeline template payload schema.")
        if set(payload) != {"schema", "parameters"}:
            raise ValueError("Unknown pipeline template payload fields.")
        parameters = payload.get("parameters")
        bindings = _literal_bindings(self.code)
        if not isinstance(parameters, Mapping) or set(parameters) != {name for name, _, _ in bindings}:
            raise ValueError("Template parameters must match the registered parameter names.")
        normalized = _literal_payload(parameters)
        if self.template_id == "pipeline.agi_run.single_action":
            if not isinstance(normalized["app"], str) or not normalized["app"].strip():
                raise ValueError("The template app must be a non-empty string.")
            if not isinstance(normalized["action"], str) or not normalized["action"].strip():
                raise ValueError("The template action must be a non-empty string.")
            if not isinstance(normalized["args"], dict):
                raise ValueError("The template args must be a table.")
            if not isinstance(normalized["apps_path"], str) or not normalized["apps_path"].strip():
                raise ValueError("The template apps_path must be a non-empty string.")
        lines = self.code.splitlines(keepends=True)
        # Positions returned by ast are UTF-8 byte offsets. Operate on bytes so
        # accented strings before a parameter cannot corrupt the replacement.
        data = self.code.encode("utf-8")
        starts = [0]
        for line in lines:
            starts.append(starts[-1] + len(line.encode("utf-8")))
        replacements = []
        for name, _, node in bindings:
            start = starts[node.lineno - 1] + node.col_offset
            end = starts[node.end_lineno - 1] + node.end_col_offset
            replacements.append((start, end, repr(normalized[name]).encode("utf-8")))
        for start, end, replacement in sorted(replacements, reverse=True):
            data = data[:start] + replacement + data[end:]
        return data.decode("utf-8")

    def as_row(self) -> dict[str, str]:
        """Return a stable row for diagnostics, docs, or table rendering."""

        return {
            "schema": self.schema,
            "template_id": self.template_id,
            "version": str(self.version),
            "title": self.title,
            "description": self.description,
            "runtime": self.runtime,
            "model": self.model,
            "tags": ",".join(self.tags),
        }


@dataclass(frozen=True, slots=True)
class PipelineStageTemplateClassification:
    """Version check result for one saved Workflow stage."""

    status: PipelineStageTemplateStatus
    template_id: str = ""
    saved_version: int | None = None
    current_version: int | None = None
    reason: str = ""

    def as_row(self) -> dict[str, str]:
        """Return a stable diagnostic row."""

        return {
            "status": self.status.value,
            "template_id": self.template_id,
            "saved_version": "" if self.saved_version is None else str(self.saved_version),
            "current_version": "" if self.current_version is None else str(self.current_version),
            "reason": self.reason,
        }


class PipelineStageTemplateRegistry:
    """Immutable registry for resolving generic Workflow stage templates."""

    def __init__(self, templates: Iterable[PipelineStageTemplate] = ()) -> None:
        self._templates = tuple(
            sorted(
                templates,
                key=lambda template: (template.template_id.casefold(), template.version),
            )
        )
        self._by_id = self._build_lookup(self._templates)

    @staticmethod
    def _build_lookup(
        templates: tuple[PipelineStageTemplate, ...],
    ) -> dict[str, PipelineStageTemplate]:
        lookup: dict[str, PipelineStageTemplate] = {}
        for template in templates:
            key = _template_key(template.template_id)
            existing = lookup.get(key)
            if existing is not None:
                raise ValueError(
                    f"Duplicate Workflow stage template {template.template_id!r}: "
                    f"versions {existing.version} and {template.version}"
                )
            lookup[key] = template
        return lookup

    def __contains__(self, template_id: object) -> bool:
        return isinstance(template_id, str) and _template_key(template_id) in self._by_id

    def __iter__(self) -> Iterator[PipelineStageTemplate]:
        return iter(self._templates)

    def __len__(self) -> int:
        return len(self._templates)

    @property
    def templates(self) -> tuple[PipelineStageTemplate, ...]:
        """Return templates in deterministic display order."""

        return self._templates

    def ids(self) -> tuple[str, ...]:
        """Return template ids in deterministic display order."""

        return tuple(template.template_id for template in self._templates)

    def get(self, template_id: str, default: Any = None) -> PipelineStageTemplate | Any:
        """Return a template by id, or ``default`` when absent."""

        return self._by_id.get(_template_key(template_id), default)

    def require(self, template_id: str) -> PipelineStageTemplate:
        """Return a template by id, raising a useful error when absent."""

        template = self.get(template_id)
        if template is not None:
            return template
        available = ", ".join(self.ids()) or "<empty>"
        raise KeyError(f"Unknown Workflow stage template {template_id!r}. Available templates: {available}")

    def select(self, template_ids: Sequence[str]) -> tuple[PipelineStageTemplate, ...]:
        """Return templates by id, preserving input order and removing duplicates."""

        selected: list[PipelineStageTemplate] = []
        seen: set[str] = set()
        for template_id in template_ids:
            key = _template_key(template_id)
            if not key or key in seen:
                continue
            template = self.get(template_id)
            if template is None:
                continue
            seen.add(key)
            selected.append(template)
        return tuple(selected)

    def saved_stage(self, template_id: str, **overrides: Any) -> dict[str, Any]:
        """Return a persisted stage dictionary for a registered template."""

        return self.require(template_id).saved_stage(**overrides)

    def classify_stage(self, entry: Mapping[str, Any] | Any) -> PipelineStageTemplateClassification:
        """Classify a saved stage as raw Python, current template, or stale template."""

        return classify_pipeline_stage_template(entry, registry=self)

    def as_rows(self) -> list[dict[str, str]]:
        """Return registry rows suitable for rendering as a deterministic table."""

        return [template.as_row() for template in self._templates]


def default_pipeline_stage_templates() -> tuple[PipelineStageTemplate, ...]:
    """Return built-in generic stage templates."""

    return tuple(sorted((
        PipelineStageTemplate(
            template_id="pipeline.agi_run.single_action",
            title="Run an app action",
            description="Run one named action with the current RunRequest API.",
            question="Run the selected app action with explicit arguments.",
            code=(
                "import asyncio\n"
                "from agi_cluster.agi_distributor import AGI, RunRequest, StageRequest\n"
                "from agi_env import AgiEnv\n\n"
                "app = 'your_project'\n"
                "apps_path = '.'\n"
                "action = 'action_name'\n"
                "args = {}\n\n"
                "async def main():\n"
                "    env = AgiEnv(apps_path=apps_path, app=app)\n"
                "    request = RunRequest(stages=[StageRequest(name=action, args=args)])\n"
                "    result = await AGI.run(env, request=request)\n"
                "    print(result)\n"
                "    return result\n\n"
                "if __name__ == '__main__':\n"
                "    asyncio.run(main())\n"
            ),
            tags=("generic", "execution", "app-action"),
        ),
        PipelineStageTemplate(
            template_id="generic.configure",
            title="Configure Workflow Inputs",
            description="Define app, input, output, and runtime parameters for a Workflow stage.",
            question="Configure the app inputs and runtime values for this Workflow stage.",
            code=(
                "APP = 'your_project'\n"
                "data_in = 'input/path'\n"
                "data_out = 'output/path'\n"
                "mode = 'local'\n"
            ),
            tags=("generic", "configuration"),
        ),
        PipelineStageTemplate(
            template_id="generic.execute",
            title="Execute Workflow Stage",
            description="Run a generic Workflow stage without changing existing raw snippets.",
            question="Execute the configured Workflow stage and produce its declared outputs.",
            code=(
                "APP = 'your_project'\n"
                "reset_target = False\n"
                "workers = {}\n"
            ),
            tags=("generic", "execution"),
        ),
        PipelineStageTemplate(
            template_id="generic.export_evidence",
            title="Export Workflow Evidence",
            description="Write reusable output paths for ANALYSIS and downstream stages.",
            question="Export summary metrics and artifact paths for later Workflow stages.",
            code=(
                "APP = 'your_project'\n"
                "artifact_dir = '~/export/your_project/pipeline'\n"
                "summary_file = artifact_dir + '/summary.json'\n"
            ),
            tags=("generic", "evidence"),
        ),
    ), key=lambda template: template.template_id.casefold()))


def classify_pipeline_stage_template(
    entry: Mapping[str, Any] | Any,
    *,
    registry: PipelineStageTemplateRegistry | None = None,
) -> PipelineStageTemplateClassification:
    """Classify a saved Workflow stage against the current template registry."""

    registry = registry or DEFAULT_PIPELINE_STAGE_TEMPLATE_REGISTRY

    if not isinstance(entry, Mapping):
        return PipelineStageTemplateClassification(
            status=PipelineStageTemplateStatus.RAW_PYTHON,
            reason="stage is not a mapping",
        )

    if entry.get("kind") == "raw_python":
        return PipelineStageTemplateClassification(
            status=PipelineStageTemplateStatus.RAW_PYTHON,
            reason="explicit custom Python",
        )

    template_id = _normalize_template_id(entry.get(PIPELINE_STAGE_TEMPLATE_ID_KEY, ""))
    if not template_id:
        if entry.get("kind") == "template":
            return PipelineStageTemplateClassification(
                status=PipelineStageTemplateStatus.STALE,
                reason="missing template id",
            )
        return PipelineStageTemplateClassification(
            status=PipelineStageTemplateStatus.RAW_PYTHON,
            reason="no template metadata",
        )

    saved_version = _coerce_version(entry.get(PIPELINE_STAGE_TEMPLATE_VERSION_KEY))
    template = registry.get(template_id)
    if template is None:
        return PipelineStageTemplateClassification(
            status=PipelineStageTemplateStatus.STALE,
            template_id=template_id,
            saved_version=saved_version,
            reason="unknown template",
        )

    if saved_version is None:
        return PipelineStageTemplateClassification(
            status=PipelineStageTemplateStatus.STALE,
            template_id=template_id,
            current_version=template.version,
            reason="missing template version",
        )

    if saved_version != template.version:
        if saved_version < template.version:
            reason = "older template version"
        else:
            reason = "newer template version"
        return PipelineStageTemplateClassification(
            status=PipelineStageTemplateStatus.STALE,
            template_id=template_id,
            saved_version=saved_version,
            current_version=template.version,
            reason=reason,
        )

    if entry.get("kind") == "template":
        reason = ""
        try:
            rendered = template.render(entry.get("template_payload"))
        except (TypeError, ValueError, SyntaxError) as exc:
            reason = str(exc)
        else:
            if entry.get("template_fingerprint") != template.fingerprint:
                reason = "template renderer fingerprint changed"
            elif entry.get("payload_fingerprint") != _fingerprint(entry["template_payload"]):
                reason = "template payload fingerprint changed"
            elif "C" in entry and entry["C"] != rendered:
                reason = "rendered Python differs from the template payload"
        if reason:
            return PipelineStageTemplateClassification(
                status=PipelineStageTemplateStatus.STALE,
                template_id=template_id, saved_version=saved_version,
                current_version=template.version, reason=reason,
            )

    return PipelineStageTemplateClassification(
        status=PipelineStageTemplateStatus.CURRENT,
        template_id=template_id,
        saved_version=saved_version,
        current_version=template.version,
        reason="template version matches",
    )


def is_current_template_stage(
    entry: Mapping[str, Any] | Any,
    *,
    registry: PipelineStageTemplateRegistry | None = None,
) -> bool:
    """Return True when a saved stage references the current template version."""

    return classify_pipeline_stage_template(entry, registry=registry).status is PipelineStageTemplateStatus.CURRENT


def pipeline_stage_execution_error(
    entry: Mapping[str, Any], *, registry: PipelineStageTemplateRegistry | None = None,
) -> str:
    """Refuse drifted structured stages without changing their saved source."""
    if entry.get("kind") != "template":
        return ""
    classification = classify_pipeline_stage_template(entry, registry=registry)
    if classification.status is PipelineStageTemplateStatus.STALE:
        return (f"Stage template {classification.template_id or '(missing id)'} is stale: "
                f"{classification.reason}. Refresh from template or keep it as custom Python explicitly.")
    return ""


def rendered_pipeline_stage_code(
    entry: Mapping[str, Any], *, registry: PipelineStageTemplateRegistry | None = None,
) -> str:
    """Return runnable Python from the canonical stage kind."""
    error = pipeline_stage_execution_error(entry, registry=registry)
    if error:
        raise ValueError(error)
    if entry.get("kind") == "template":
        registry = registry or DEFAULT_PIPELINE_STAGE_TEMPLATE_REGISTRY
        return registry.require(str(entry["template_id"])).render(entry["template_payload"])
    return str(entry.get("C", "") or "")


def detach_pipeline_stage_template(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Keep exact Python as custom code, retaining its template provenance."""
    result = copy.deepcopy(dict(entry))
    provenance = {key: result.pop(key) for key in PIPELINE_STAGE_STRUCTURED_KEYS if key in result}
    if provenance:
        result["template_origin"] = provenance
    result["kind"] = "raw_python"
    return result


def normalize_pipeline_stage_for_save(
    entry: Mapping[str, Any], *, previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """A deliberate editor code change relinquishes template ownership."""
    result = copy.deepcopy(dict(entry))
    if result.get("kind") == "template":
        template = DEFAULT_PIPELINE_STAGE_TEMPLATE_REGISTRY.get(str(result.get("template_id", "")))
        try:
            expected_code = template.render(result.get("template_payload")) if template else None
        except (TypeError, ValueError):
            expected_code = None
        if (previous and previous.get("kind") == "template"
                and result.get("C") != previous.get("C")
                and result.get("C") != expected_code
                and all(result.get(key) == previous.get(key) for key in PIPELINE_STAGE_STRUCTURED_KEYS)):
            return detach_pipeline_stage_template(result)
        error = pipeline_stage_execution_error(result)
        if error:
            raise ValueError(error)
    elif "kind" not in result:
        result["kind"] = "raw_python"
    return result


def reconcile_imported_pipeline_template_stage(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Explicit notebook import keeps code edits as custom Python, with provenance."""
    result = copy.deepcopy(dict(entry))
    if result.get("kind") != "template":
        return result
    template = DEFAULT_PIPELINE_STAGE_TEMPLATE_REGISTRY.get(str(result.get("template_id", "")))
    if template is None:
        return result
    try:
        rendered = template.render(result.get("template_payload"))
    except (TypeError, ValueError):
        return result
    # Do not disguise registry/schema drift as a notebook code edit.
    if (result.get("template_version") == template.version
            and result.get("template_fingerprint") == template.fingerprint
            and result.get("payload_fingerprint") == _fingerprint(result["template_payload"])
            and result.get("C", rendered) != rendered):
        return detach_pipeline_stage_template(result)
    return result


def refresh_pipeline_stage_template(
    entry: Mapping[str, Any], *, payload: Mapping[str, Any] | None = None,
    registry: PipelineStageTemplateRegistry | None = None,
) -> dict[str, Any]:
    """Explicitly refresh a renderer; retain all user metadata and parameters."""
    registry = registry or DEFAULT_PIPELINE_STAGE_TEMPLATE_REGISTRY
    template = registry.require(str(entry.get("template_id", "")))
    result = copy.deepcopy(dict(entry))
    current_payload = payload if payload is not None else entry.get("template_payload")
    if current_payload is None:
        # Legacy metadata alone never authorizes rewriting custom code.
        converted = convert_legacy_pipeline_stage(entry, registry=registry)
        if converted.get("kind") != "template":
            raise ValueError("Legacy custom Python cannot be refreshed; keep it as raw Python.")
        current_payload = converted["template_payload"]
    rendered = template.render(current_payload)
    result.update(template.saved_stage(template_payload=current_payload))
    for key in ("D", "Q", "M", "E"):
        if key in entry:
            result[key] = copy.deepcopy(entry[key])
    result["C"] = rendered
    result["R"] = template.runtime
    return result


def convert_legacy_pipeline_stage(
    entry: Mapping[str, Any], *, registry: PipelineStageTemplateRegistry | None = None,
) -> dict[str, Any]:
    """Convert only exactly recognized generated shapes; preserve all custom code."""
    result = copy.deepcopy(dict(entry))
    if result.get("kind") in {"template", "raw_python"}:
        return result
    registry = registry or DEFAULT_PIPELINE_STAGE_TEMPLATE_REGISTRY
    code = str(result.get("C", "") or "")
    for template in registry:
        try:
            bindings = {name: value for name, value, _ in _literal_bindings(code)}
            payload = {"schema": PIPELINE_STAGE_PAYLOAD_SCHEMA, "parameters": bindings}
            if template.render(payload) != code:
                continue
        except (TypeError, ValueError, SyntaxError):
            continue
        expected_runtime = str(result.get("R", "") or template.runtime)
        if expected_runtime != template.runtime:
            continue
        structured = template.saved_stage(template_payload=payload)
        for key in PIPELINE_STAGE_STRUCTURED_KEYS:
            result[key] = structured[key]
        result["kind"] = "template"
        return result
    return detach_pipeline_stage_template(result)


def convert_legacy_pipeline_stages(
    data: Mapping[str, Any], *, registry: PipelineStageTemplateRegistry | None = None,
) -> dict[str, Any]:
    """Build a conversion preview; the caller chooses whether to persist it."""
    result = copy.deepcopy(dict(data))
    for module, entries in result.items():
        if module != "__meta__" and isinstance(entries, list):
            result[module] = [convert_legacy_pipeline_stage(entry, registry=registry)
                              if isinstance(entry, Mapping) else entry for entry in entries]
    return result


def is_stale_template_stage(
    entry: Mapping[str, Any] | Any,
    *,
    registry: PipelineStageTemplateRegistry | None = None,
) -> bool:
    """Return True when a saved stage has template metadata that needs review."""

    return classify_pipeline_stage_template(entry, registry=registry).status is PipelineStageTemplateStatus.STALE


def is_raw_python_stage(
    entry: Mapping[str, Any] | Any,
    *,
    registry: PipelineStageTemplateRegistry | None = None,
) -> bool:
    """Return True when a saved stage has no template metadata."""

    return classify_pipeline_stage_template(entry, registry=registry).status is PipelineStageTemplateStatus.RAW_PYTHON


def pipeline_stage_template_rows(
    registry: PipelineStageTemplateRegistry | None = None,
) -> list[dict[str, str]]:
    """Return deterministic rows for the available Workflow stage templates."""

    return (registry or DEFAULT_PIPELINE_STAGE_TEMPLATE_REGISTRY).as_rows()


def pipeline_stage_classification_rows(
    entries: Iterable[Mapping[str, Any] | Any],
    *,
    registry: PipelineStageTemplateRegistry | None = None,
) -> list[dict[str, str]]:
    """Return deterministic classification rows for saved stages in input order."""

    rows: list[dict[str, str]] = []
    for index, entry in enumerate(entries):
        row = classify_pipeline_stage_template(entry, registry=registry).as_row()
        row["index"] = str(index)
        rows.append(row)
    return rows


def with_template_version(template: PipelineStageTemplate, version: int) -> PipelineStageTemplate:
    """Return ``template`` with a different version for tests or migrations."""

    return replace(template, version=version)


def _normalize_template_id(value: Any) -> str:
    return str(value or "").strip()


def _template_key(value: Any) -> str:
    return _normalize_template_id(value).casefold()


def _coerce_version(value: Any) -> int | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


DEFAULT_PIPELINE_STAGE_TEMPLATE_REGISTRY = PipelineStageTemplateRegistry(default_pipeline_stage_templates())
