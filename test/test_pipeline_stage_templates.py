from __future__ import annotations

from pathlib import Path
import sys

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
SRC_PACKAGE = SRC_ROOT / "agilab"
sys.path.insert(0, str(SRC_ROOT))

import agilab as _agilab_package

if str(SRC_PACKAGE) not in _agilab_package.__path__:
    _agilab_package.__path__.insert(0, str(SRC_PACKAGE))

from agilab.pipeline_stage_templates import (
    PIPELINE_STAGE_TEMPLATE_ID_KEY,
    PIPELINE_STAGE_TEMPLATE_SCHEMA,
    PIPELINE_STAGE_TEMPLATE_VERSION_KEY,
    PipelineStageTemplate,
    PipelineStageTemplateRegistry,
    PipelineStageTemplateStatus,
    classify_pipeline_stage_template,
    default_pipeline_stage_templates,
    is_current_template_stage,
    is_raw_python_stage,
    is_stale_template_stage,
    pipeline_stage_classification_rows,
    pipeline_stage_template_rows,
    with_template_version,
)


def _template(template_id: str, *, version: int = 1) -> PipelineStageTemplate:
    return PipelineStageTemplate(
        template_id=template_id,
        title=f"{template_id} title",
        description=f"{template_id} description",
        question=f"{template_id} question",
        code=f"APP = '{template_id}'\n",
        version=version,
        tags=("demo",),
    )


def test_pipeline_stage_template_registry_returns_deterministic_rows() -> None:
    registry = PipelineStageTemplateRegistry(
        (
            _template("zeta.stage", version=2),
            _template("alpha.stage", version=1),
        )
    )

    assert registry.ids() == ("alpha.stage", "zeta.stage")
    assert registry.as_rows() == [
        {
            "schema": PIPELINE_STAGE_TEMPLATE_SCHEMA,
            "template_id": "alpha.stage",
            "version": "1",
            "title": "alpha.stage title",
            "description": "alpha.stage description",
            "runtime": "runpy",
            "model": "",
            "tags": "demo",
        },
        {
            "schema": PIPELINE_STAGE_TEMPLATE_SCHEMA,
            "template_id": "zeta.stage",
            "version": "2",
            "title": "zeta.stage title",
            "description": "zeta.stage description",
            "runtime": "runpy",
            "model": "",
            "tags": "demo",
        },
    ]


def test_pipeline_stage_template_registry_collection_helpers_and_selection() -> None:
    alpha = _template("alpha.stage", version=2)
    beta = _template("beta.stage")
    registry = PipelineStageTemplateRegistry((beta, alpha))

    assert len(registry) == 2
    assert "alpha.stage" in registry
    assert "ALPHA.STAGE" in registry
    assert 42 not in registry
    assert tuple(template.template_id for template in registry) == ("alpha.stage", "beta.stage")
    assert registry.templates == (alpha, beta)
    assert registry.get("missing", default="fallback") == "fallback"
    assert registry.require("alpha.stage") is alpha

    selected = registry.select(
        [
            "",
            "beta.stage",
            "missing.stage",
            " BETA.STAGE ",
            "alpha.stage",
        ]
    )
    assert selected == (beta, alpha)

    saved = registry.saved_stage("alpha.stage", M="manual-model")
    assert saved["D"] == "alpha.stage description"
    assert saved["M"] == "manual-model"
    assert saved[PIPELINE_STAGE_TEMPLATE_ID_KEY] == "alpha.stage"

    classified = registry.classify_stage(
        {
            PIPELINE_STAGE_TEMPLATE_ID_KEY: "alpha.stage",
            PIPELINE_STAGE_TEMPLATE_VERSION_KEY: 2,
        }
    )
    assert classified.status is PipelineStageTemplateStatus.CURRENT


def test_saved_stage_includes_template_metadata_without_rewriting_code() -> None:
    template = _template("generic.demo", version=3)
    stage = template.saved_stage(C="print('custom raw code')", Q="User edited question")

    assert stage["C"] == "print('custom raw code')"
    assert stage["Q"] == "User edited question"
    assert stage["D"] == "generic.demo description"
    assert stage["R"] == "runpy"
    assert stage[PIPELINE_STAGE_TEMPLATE_ID_KEY] == "generic.demo"
    assert stage[PIPELINE_STAGE_TEMPLATE_VERSION_KEY] == 3


def test_classifies_current_stale_and_raw_python_stages() -> None:
    registry = PipelineStageTemplateRegistry((_template("generic.demo", version=2),))
    current = {
        "C": "print(1)",
        PIPELINE_STAGE_TEMPLATE_ID_KEY: "generic.demo",
        PIPELINE_STAGE_TEMPLATE_VERSION_KEY: 2,
    }
    stale = {
        "C": "print(1)",
        PIPELINE_STAGE_TEMPLATE_ID_KEY: "generic.demo",
        PIPELINE_STAGE_TEMPLATE_VERSION_KEY: 1,
    }
    raw = {"C": "print(1)"}

    assert is_current_template_stage(current, registry=registry) is True
    assert is_stale_template_stage(stale, registry=registry) is True
    assert is_raw_python_stage(raw, registry=registry) is True

    stale_result = classify_pipeline_stage_template(stale, registry=registry)
    assert stale_result.status is PipelineStageTemplateStatus.STALE
    assert stale_result.saved_version == 1
    assert stale_result.current_version == 2
    assert stale_result.reason == "older template version"


def test_template_normalization_handles_blank_runtime_title_fallback_and_tags() -> None:
    template = PipelineStageTemplate(
        template_id=" generic.normalized ",
        title="  Normalized title  ",
        description="   ",
        question="  What should run?  ",
        code=123,
        version="4",
        runtime="  ",
        model="  gpt-demo  ",
        tags=(" keep ", "", "also-keep"),
    )

    assert template.template_id == "generic.normalized"
    assert template.title == "Normalized title"
    assert template.description == ""
    assert template.question == "What should run?"
    assert template.code == "123"
    assert template.version == 4
    assert template.runtime == "runpy"
    assert template.model == "gpt-demo"
    assert template.tags == ("keep", "also-keep")
    assert template.saved_stage()["D"] == "Normalized title"


def test_non_mapping_stages_and_invalid_versions_are_classified_or_rejected() -> None:
    result = classify_pipeline_stage_template("print('raw')")

    assert result.status is PipelineStageTemplateStatus.RAW_PYTHON
    assert result.reason == "stage is not a mapping"

    with pytest.raises(ValueError, match="version must be a positive integer"):
        PipelineStageTemplate(
            template_id="generic.bad",
            title="Bad",
            question="Bad?",
            code="pass",
            version="not-an-int",
        )


def test_unknown_missing_and_future_template_versions_are_stale() -> None:
    registry = PipelineStageTemplateRegistry((_template("generic.demo", version=2),))

    unknown = classify_pipeline_stage_template(
        {
            PIPELINE_STAGE_TEMPLATE_ID_KEY: "generic.missing",
            PIPELINE_STAGE_TEMPLATE_VERSION_KEY: 1,
        },
        registry=registry,
    )
    missing_version = classify_pipeline_stage_template(
        {PIPELINE_STAGE_TEMPLATE_ID_KEY: "generic.demo"},
        registry=registry,
    )
    future_version = classify_pipeline_stage_template(
        {
            PIPELINE_STAGE_TEMPLATE_ID_KEY: "generic.demo",
            PIPELINE_STAGE_TEMPLATE_VERSION_KEY: 4,
        },
        registry=registry,
    )

    assert unknown.status is PipelineStageTemplateStatus.STALE
    assert unknown.reason == "unknown template"
    assert missing_version.status is PipelineStageTemplateStatus.STALE
    assert missing_version.reason == "missing template version"
    assert future_version.status is PipelineStageTemplateStatus.STALE
    assert future_version.reason == "newer template version"


def test_classification_rows_are_deterministic_and_preserve_input_order() -> None:
    registry = PipelineStageTemplateRegistry((_template("generic.demo", version=2),))
    rows = pipeline_stage_classification_rows(
        [
            {"C": "print('raw')"},
            {
                PIPELINE_STAGE_TEMPLATE_ID_KEY: "generic.demo",
                PIPELINE_STAGE_TEMPLATE_VERSION_KEY: 2,
            },
        ],
        registry=registry,
    )

    assert rows == [
        {
            "status": "raw_python",
            "template_id": "",
            "saved_version": "",
            "current_version": "",
            "reason": "no template metadata",
            "index": "0",
        },
        {
            "status": "current",
            "template_id": "generic.demo",
            "saved_version": "2",
            "current_version": "2",
            "reason": "template version matches",
            "index": "1",
        },
    ]


def test_default_registry_exposes_generic_templates_as_rows() -> None:
    rows = pipeline_stage_template_rows()
    ids = tuple(row["template_id"] for row in rows)

    assert ids == tuple(sorted(ids, key=str.casefold))
    assert ids == tuple(template.template_id for template in default_pipeline_stage_templates())
    assert {"generic.configure", "generic.execute", "generic.export_evidence"}.issubset(ids)


def test_with_template_version_returns_replaced_template_without_mutating_original() -> None:
    template = _template("generic.demo", version=1)

    newer = with_template_version(template, 5)

    assert template.version == 1
    assert newer.version == 5
    assert newer.template_id == template.template_id
    assert newer.code == template.code


def test_pipeline_stage_template_registry_reports_invalid_unknown_and_duplicate_names() -> None:
    first = _template("generic.demo")
    duplicate = _template("generic.demo", version=2)

    with pytest.raises(ValueError, match="id cannot be empty"):
        _template("")
    with pytest.raises(ValueError, match="version must be a positive integer"):
        _template("generic.bad", version=0)
    with pytest.raises(ValueError, match="Duplicate Workflow stage template"):
        PipelineStageTemplateRegistry((first, duplicate))
    with pytest.raises(KeyError, match="Unknown Workflow stage template 'missing'"):
        PipelineStageTemplateRegistry((first,)).require("missing")
