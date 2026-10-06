"""Verify shared analysis curves normalize naive dates consistently with UTC."""

from agi_web import analysis_curves_component


def test_naive_and_offset_dates_share_the_same_utc_analysis_axis():
    component = analysis_curves_component([
        {"time": "2026-01-02T01:00:00+01:00", "value": 2},
        {"time": "2026-01-01T00:00:00", "value": 1},
        {"time": "invalid", "value": 3},
    ], x="time", series=["value"])
    rows = component.payload["rows"]
    assert [row["values"]["value"] for row in rows] == [1.0, 2.0]
    assert rows[1]["x"] - rows[0]["x"] == 24 * 60 * 60 * 1000
    assert component.payload["invalid_rows"] == 1
    assert rows[0]["label"] == "2026-01-01T00:00:00"
