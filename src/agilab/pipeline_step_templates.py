"""Typed registry for generic Pipeline stage templates."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any


PIPELINE_STEP_TEMPLATE_SCHEMA = "agilab.pipeline_step_templates.v1"
PIPELINE_STEP_TEMPLATE_ID_KEY = "template_id"
PIPELINE_STEP_TEMPLATE_VERSION_KEY = "template_version"


class PipelineStepTemplateStatus(StrEnum):
    """Template classification for a saved Pipeline stage."""

    CURRENT = "current"
    STALE = "stale"
    RAW_PYTHON = "raw_python"


@dataclass(frozen=True, slots=True)
class PipelineStepTemplate:
    """Resolved metadata and default code for one generic Pipeline stage."""

    template_id: str
    title: str
    question: str
    code: str
    version: int = 1
    description: str = ""
    runtime: str = "runpy"
    model: str = ""
    tags: tuple[str, ...] = ()
    schema: str = PIPELINE_STEP_TEMPLATE_SCHEMA

    def __post_init__(self) -> None:
        normalized_id = _normalize_template_id(self.template_id)
        if not normalized_id:
            raise ValueError("Pipeline stage template id cannot be empty.")
        normalized_version = _coerce_version(self.version)
        if normalized_version is None or normalized_version < 1:
            raise ValueError("Pipeline stage template version must be a positive integer.")
        object.__setattr__(self, "template_id", normalized_id)
        object.__setattr__(self, "title", str(self.title).strip())
        object.__setattr__(self, "question", str(self.question).strip())
        object.__setattr__(self, "code", str(self.code))
        object.__setattr__(self, "version", normalized_version)
        object.__setattr__(self, "description", str(self.description).strip())
        object.__setattr__(self, "runtime", str(self.runtime or "runpy").strip() or "runpy")
        object.__setattr__(self, "model", str(self.model or "").strip())
        object.__setattr__(self, "tags", tuple(str(tag).strip() for tag in self.tags if str(tag).strip()))

    def saved_step(self, **overrides: Any) -> dict[str, Any]:
        """Return a lab_steps-compatible stage dictionary for this template."""

        step: dict[str, Any] = {
            "D": self.description or self.title,
            "Q": self.question,
            "M": self.model,
            "C": self.code,
            "R": self.runtime,
            PIPELINE_STEP_TEMPLATE_ID_KEY: self.template_id,
            PIPELINE_STEP_TEMPLATE_VERSION_KEY: self.version,
        }
        step.update(overrides)
        return step

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
class PipelineStepTemplateClassification:
    """Version check result for one saved Pipeline stage."""

    status: PipelineStepTemplateStatus
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


class PipelineStepTemplateRegistry:
    """Immutable registry for resolving generic Pipeline stage templates."""

    def __init__(self, templates: Iterable[PipelineStepTemplate] = ()) -> None:
        self._templates = tuple(
            sorted(
                templates,
                key=lambda template: (template.template_id.casefold(), template.version),
            )
        )
        self._by_id = self._build_lookup(self._templates)

    @staticmethod
    def _build_lookup(
        templates: tuple[PipelineStepTemplate, ...],
    ) -> dict[str, PipelineStepTemplate]:
        lookup: dict[str, PipelineStepTemplate] = {}
        for template in templates:
            key = _template_key(template.template_id)
            existing = lookup.get(key)
            if existing is not None:
                raise ValueError(
                    f"Duplicate Pipeline stage template {template.template_id!r}: "
                    f"versions {existing.version} and {template.version}"
                )
            lookup[key] = template
        return lookup

    def __contains__(self, template_id: object) -> bool:
        return isinstance(template_id, str) and _template_key(template_id) in self._by_id

    def __iter__(self) -> Iterator[PipelineStepTemplate]:
        return iter(self._templates)

    def __len__(self) -> int:
        return len(self._templates)

    @property
    def templates(self) -> tuple[PipelineStepTemplate, ...]:
        """Return templates in deterministic display order."""

        return self._templates

    def ids(self) -> tuple[str, ...]:
        """Return template ids in deterministic display order."""

        return tuple(template.template_id for template in self._templates)

    def get(self, template_id: str, default: Any = None) -> PipelineStepTemplate | Any:
        """Return a template by id, or ``default`` when absent."""

        return self._by_id.get(_template_key(template_id), default)

    def require(self, template_id: str) -> PipelineStepTemplate:
        """Return a template by id, raising a useful error when absent."""

        template = self.get(template_id)
        if template is not None:
            return template
        available = ", ".join(self.ids()) or "<empty>"
        raise KeyError(f"Unknown Pipeline stage template {template_id!r}. Available templates: {available}")

    def select(self, template_ids: Sequence[str]) -> tuple[PipelineStepTemplate, ...]:
        """Return templates by id, preserving input order and removing duplicates."""

        selected: list[PipelineStepTemplate] = []
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

    def saved_step(self, template_id: str, **overrides: Any) -> dict[str, Any]:
        """Return a lab_steps-compatible stage dictionary for a registered template."""

        return self.require(template_id).saved_step(**overrides)

    def classify_step(self, entry: Mapping[str, Any] | Any) -> PipelineStepTemplateClassification:
        """Classify a saved stage as raw Python, current template, or stale template."""

        return classify_pipeline_step_template(entry, registry=self)

    def as_rows(self) -> list[dict[str, str]]:
        """Return registry rows suitable for rendering as a deterministic table."""

        return [template.as_row() for template in self._templates]


def default_pipeline_step_templates() -> tuple[PipelineStepTemplate, ...]:
    """Return built-in generic stage templates."""

    return (
        PipelineStepTemplate(
            template_id="generic.configure",
            title="Configure Pipeline Inputs",
            description="Define app, input, output, and runtime parameters for a Pipeline stage.",
            question="Configure the app inputs and runtime values for this Pipeline stage.",
            code=(
                "APP = 'your_project'\n"
                "data_in = 'input/path'\n"
                "data_out = 'output/path'\n"
                "mode = 'local'\n"
            ),
            tags=("generic", "configuration"),
        ),
        PipelineStepTemplate(
            template_id="generic.execute",
            title="Execute Pipeline Stage",
            description="Run a generic Pipeline stage without changing existing raw snippets.",
            question="Execute the configured Pipeline stage and produce its declared outputs.",
            code=(
                "APP = 'your_project'\n"
                "reset_target = False\n"
                "workers = {}\n"
            ),
            tags=("generic", "execution"),
        ),
        PipelineStepTemplate(
            template_id="generic.export_evidence",
            title="Export Pipeline Evidence",
            description="Write reusable output paths for ANALYSIS and downstream stages.",
            question="Export summary metrics and artifact paths for later Pipeline stages.",
            code=(
                "APP = 'your_project'\n"
                "artifact_dir = '~/export/your_project/pipeline'\n"
                "summary_file = artifact_dir + '/summary.json'\n"
            ),
            tags=("generic", "evidence"),
        ),
    )


def classify_pipeline_step_template(
    entry: Mapping[str, Any] | Any,
    *,
    registry: PipelineStepTemplateRegistry | None = None,
) -> PipelineStepTemplateClassification:
    """Classify a saved Pipeline stage against the current template registry."""

    registry = registry or DEFAULT_PIPELINE_STEP_TEMPLATE_REGISTRY

    if not isinstance(entry, Mapping):
        return PipelineStepTemplateClassification(
            status=PipelineStepTemplateStatus.RAW_PYTHON,
            reason="stage is not a mapping",
        )

    template_id = _normalize_template_id(entry.get(PIPELINE_STEP_TEMPLATE_ID_KEY, ""))
    if not template_id:
        return PipelineStepTemplateClassification(
            status=PipelineStepTemplateStatus.RAW_PYTHON,
            reason="no template metadata",
        )

    saved_version = _coerce_version(entry.get(PIPELINE_STEP_TEMPLATE_VERSION_KEY))
    template = registry.get(template_id)
    if template is None:
        return PipelineStepTemplateClassification(
            status=PipelineStepTemplateStatus.STALE,
            template_id=template_id,
            saved_version=saved_version,
            reason="unknown template",
        )

    if saved_version is None:
        return PipelineStepTemplateClassification(
            status=PipelineStepTemplateStatus.STALE,
            template_id=template_id,
            current_version=template.version,
            reason="missing template version",
        )

    if saved_version != template.version:
        if saved_version < template.version:
            reason = "older template version"
        else:
            reason = "newer template version"
        return PipelineStepTemplateClassification(
            status=PipelineStepTemplateStatus.STALE,
            template_id=template_id,
            saved_version=saved_version,
            current_version=template.version,
            reason=reason,
        )

    return PipelineStepTemplateClassification(
        status=PipelineStepTemplateStatus.CURRENT,
        template_id=template_id,
        saved_version=saved_version,
        current_version=template.version,
        reason="template version matches",
    )


def is_current_template_step(
    entry: Mapping[str, Any] | Any,
    *,
    registry: PipelineStepTemplateRegistry | None = None,
) -> bool:
    """Return True when a saved stage references the current template version."""

    return classify_pipeline_step_template(entry, registry=registry).status is PipelineStepTemplateStatus.CURRENT


def is_stale_template_step(
    entry: Mapping[str, Any] | Any,
    *,
    registry: PipelineStepTemplateRegistry | None = None,
) -> bool:
    """Return True when a saved stage has template metadata that needs review."""

    return classify_pipeline_step_template(entry, registry=registry).status is PipelineStepTemplateStatus.STALE


def is_raw_python_step(
    entry: Mapping[str, Any] | Any,
    *,
    registry: PipelineStepTemplateRegistry | None = None,
) -> bool:
    """Return True when a saved stage has no template metadata."""

    return classify_pipeline_step_template(entry, registry=registry).status is PipelineStepTemplateStatus.RAW_PYTHON


def pipeline_step_template_rows(
    registry: PipelineStepTemplateRegistry | None = None,
) -> list[dict[str, str]]:
    """Return deterministic rows for the available Pipeline stage templates."""

    return (registry or DEFAULT_PIPELINE_STEP_TEMPLATE_REGISTRY).as_rows()


def pipeline_step_classification_rows(
    entries: Iterable[Mapping[str, Any] | Any],
    *,
    registry: PipelineStepTemplateRegistry | None = None,
) -> list[dict[str, str]]:
    """Return deterministic classification rows for saved stages in input order."""

    rows: list[dict[str, str]] = []
    for index, entry in enumerate(entries):
        row = classify_pipeline_step_template(entry, registry=registry).as_row()
        row["index"] = str(index)
        rows.append(row)
    return rows


def with_template_version(template: PipelineStepTemplate, version: int) -> PipelineStepTemplate:
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


DEFAULT_PIPELINE_STEP_TEMPLATE_REGISTRY = PipelineStepTemplateRegistry(default_pipeline_step_templates())
