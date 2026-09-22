"""A flat generated report must undergo the same checks as a nested report."""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def verifier(monkeypatch):
    directory = Path(__file__).parents[1] / 'tools/demos'
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location('forecast_layout_verifier', directory / 'verify_forecast_notebook_demo.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_flat_report_exposes_original_values_to_independent_checks(verifier):
    report = {'context':[1, 2], 'forecast':[3], 'mae':99, 'coverage':0.2}
    fixture, prediction, metrics = verifier.analysis_sections(report)
    assert fixture['context'] == [1, 2]
    assert prediction['forecast'] == [3]
    # A wrong reported metric is preserved for comparison, never recomputed away.
    assert metrics['mae'] == 99


def test_nested_report_and_incomplete_mixture(verifier):
    report = {'fixture':{'context':[1]}, 'predictions':{'forecast':[2]}, 'metrics':{'mae':3}}
    assert verifier.analysis_sections(report) == (report['fixture'], report['predictions'], report['metrics'])
    with pytest.raises(ValueError, match='incomplete'):
        verifier.analysis_sections({'fixture':{'context':[1]}, 'forecast':[2], 'mae':3})
    with pytest.raises(ValueError, match='Invalid analysis'):
        verifier.analysis_sections({**report, 'metrics':None})
