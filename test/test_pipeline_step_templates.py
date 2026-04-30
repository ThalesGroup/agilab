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

from agilab.pipeline_step_templates import (
    PIPELINE_STEP_TEMPLATE_ID_KEY,
    PIPELINE_STEP_TEMPLATE_SCHEMA,
    PIPELINE_STEP_TEMPLATE_VERSION_KEY,
    PipelineStepTemplate,
    PipelineStepTemplateRegistry,
    PipelineStepTemplateStatus,
    classify_pipeline_step_template,
    default_pipeline_step_templates,
    is_current_template_step,
    is_raw_python_step,
    is_stale_template_step,
    pipeline_step_classification_rows,
    pipeline_step_template_rows,
)


def _template(template_id: str, *, version: int = 1) -> PipelineStepTemplate:
    return PipelineStepTemplate(
        template_id=template_id,
        title=f"{template_id} title",
        description=f"{template_id} description",
        question=f"{template_id} question",
        code=f"APP = '{template_id}'\n",
        version=version,
        tags=("demo",),
    )


def test_pipeline_step_template_registry_returns_deterministic_rows() -> None:
    registry = PipelineStepTemplateRegistry(
        (
            _template("zeta.step", version=2),
            _template("alpha.step", version=1),
        )
    )

    assert registry.ids() == ("alpha.step", "zeta.step")
    assert registry.as_rows() == [
        {
            "schema": PIPELINE_STEP_TEMPLATE_SCHEMA,
            "template_id": "alpha.step",
            "version": "1",
            "title": "alpha.step title",
            "description": "alpha.step description",
            "runtime": "runpy",
            "model": "",
            "tags": "demo",
        },
        {
            "schema": PIPELINE_STEP_TEMPLATE_SCHEMA,
            "template_id": "zeta.step",
            "version": "2",
            "title": "zeta.step title",
            "description": "zeta.step description",
            "runtime": "runpy",
            "model": "",
            "tags": "demo",
        },
    ]


def test_saved_step_includes_template_metadata_without_rewriting_code() -> None:
    template = _template("generic.demo", version=3)
    step = template.saved_step(C="print('custom raw code')", Q="User edited question")

    assert step["C"] == "print('custom raw code')"
    assert step["Q"] == "User edited question"
    assert step["D"] == "generic.demo description"
    assert step["R"] == "runpy"
    assert step[PIPELINE_STEP_TEMPLATE_ID_KEY] == "generic.demo"
    assert step[PIPELINE_STEP_TEMPLATE_VERSION_KEY] == 3


def test_classifies_current_stale_and_raw_python_steps() -> None:
    registry = PipelineStepTemplateRegistry((_template("generic.demo", version=2),))
    current = {
        "C": "print(1)",
        PIPELINE_STEP_TEMPLATE_ID_KEY: "generic.demo",
        PIPELINE_STEP_TEMPLATE_VERSION_KEY: 2,
    }
    stale = {
        "C": "print(1)",
        PIPELINE_STEP_TEMPLATE_ID_KEY: "generic.demo",
        PIPELINE_STEP_TEMPLATE_VERSION_KEY: 1,
    }
    raw = {"C": "print(1)"}

    assert is_current_template_step(current, registry=registry) is True
    assert is_stale_template_step(stale, registry=registry) is True
    assert is_raw_python_step(raw, registry=registry) is True

    stale_result = classify_pipeline_step_template(stale, registry=registry)
    assert stale_result.status is PipelineStepTemplateStatus.STALE
    assert stale_result.saved_version == 1
    assert stale_result.current_version == 2
    assert stale_result.reason == "older template version"


def test_unknown_missing_and_future_template_versions_are_stale() -> None:
    registry = PipelineStepTemplateRegistry((_template("generic.demo", version=2),))

    unknown = classify_pipeline_step_template(
        {
            PIPELINE_STEP_TEMPLATE_ID_KEY: "generic.missing",
            PIPELINE_STEP_TEMPLATE_VERSION_KEY: 1,
        },
        registry=registry,
    )
    missing_version = classify_pipeline_step_template(
        {PIPELINE_STEP_TEMPLATE_ID_KEY: "generic.demo"},
        registry=registry,
    )
    future_version = classify_pipeline_step_template(
        {
            PIPELINE_STEP_TEMPLATE_ID_KEY: "generic.demo",
            PIPELINE_STEP_TEMPLATE_VERSION_KEY: 4,
        },
        registry=registry,
    )

    assert unknown.status is PipelineStepTemplateStatus.STALE
    assert unknown.reason == "unknown template"
    assert missing_version.status is PipelineStepTemplateStatus.STALE
    assert missing_version.reason == "missing template version"
    assert future_version.status is PipelineStepTemplateStatus.STALE
    assert future_version.reason == "newer template version"


def test_classification_rows_are_deterministic_and_preserve_input_order() -> None:
    registry = PipelineStepTemplateRegistry((_template("generic.demo", version=2),))
    rows = pipeline_step_classification_rows(
        [
            {"C": "print('raw')"},
            {
                PIPELINE_STEP_TEMPLATE_ID_KEY: "generic.demo",
                PIPELINE_STEP_TEMPLATE_VERSION_KEY: 2,
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
    rows = pipeline_step_template_rows()
    ids = tuple(row["template_id"] for row in rows)

    assert ids == tuple(sorted(ids, key=str.casefold))
    assert ids == tuple(template.template_id for template in default_pipeline_step_templates())
    assert {"generic.configure", "generic.execute", "generic.export_evidence"}.issubset(ids)


def test_pipeline_step_template_registry_reports_invalid_unknown_and_duplicate_names() -> None:
    first = _template("generic.demo")
    duplicate = _template("generic.demo", version=2)

    with pytest.raises(ValueError, match="id cannot be empty"):
        _template("")
    with pytest.raises(ValueError, match="version must be a positive integer"):
        _template("generic.bad", version=0)
    with pytest.raises(ValueError, match="Duplicate Pipeline step template"):
        PipelineStepTemplateRegistry((first, duplicate))
    with pytest.raises(KeyError, match="Unknown Pipeline step template 'missing'"):
        PipelineStepTemplateRegistry((first,)).require("missing")
