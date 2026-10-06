"""Exercise Python-authored controls and observable native view payloads."""

import base64
from datetime import date, datetime, timedelta
import io
import sys
from types import ModuleType, SimpleNamespace

import pytest

from agi_web import python_ui as ui
from agi_web.python_view_session import RerunView, UIError, ViewSession, use_session


@pytest.fixture
def session():
    value = ViewSession(lambda: None)
    with use_session(value):
        yield value


def test_session_mapping_behaves_as_mapping_and_attributes(session):
    ui.session_state["first"] = 1
    ui.session_state.second = 2
    assert ui.session_state.first == 1
    assert ui.session_state.get("second") == 2
    assert set(ui.session_state) == {"first", "second"}
    assert len(ui.session_state) == 2
    del ui.session_state["first"]
    with pytest.raises(AttributeError):
        _ = ui.session_state.first
    ui.query_params.from_dict({"filter": ["old", "new"]})
    assert ui.query_params.filter == "new"


def test_layout_placeholders_replace_content_and_progress_updates(session):
    with ui.expander("Details", expanded=True):
        columns = ui.columns([1, 2], gap="large")
        columns[0].text("left")
        columns[1].text("right")
    placeholder = ui.empty()
    placeholder.text("old")
    placeholder.text("new")
    assert [node["props"]["body"] for node in placeholder.node["children"]] == ["new"]
    placeholder.empty()
    assert placeholder.node["children"] == []
    progress = ui.progress(20)
    progress.progress(value=0.75, text="almost")
    assert progress.node["props"]["value"] == 0.75
    progress.progress(100)
    assert progress.node["props"]["value"] == 1
    assert ui.Container().empty().update(value=1).node is None
    with pytest.raises(AttributeError):
        _ = placeholder._private_control
    with pytest.raises(UIError, match="positive"):
        ui.columns([])
    with pytest.raises(UIError, match="positive"):
        ui.columns([1, -1])
    with pytest.raises(UIError, match="nested"), ui.form("outer"):
        ui.form("inner")
    with pytest.raises(UIError, match="belong"):
        ui.form_submit_button()


def test_text_and_status_helpers_preserve_visible_content(session):
    helpers = [ui.title, ui.header, ui.subheader, ui.caption, ui.text, ui.html,
               ui.code, ui.latex, ui.info, ui.warning, ui.error, ui.success]
    for helper in helpers:
        assert helper("fixture").node["props"]["body"] == "fixture"
    assert ui.exception(ValueError("bad")).node["props"]["body"] == "ValueError: bad"
    assert ui.markdown("<b>body</b>", unsafe_allow_html=True).node["kind"] == "html"
    assert ui.json({"value": 2}).node["props"]["body"] == '{\n  "value": 2\n}'
    assert ui.json("already encoded").node["props"]["body"] == "already encoded"
    assert ui.metric("Count", 2, 1)["props"]["delta"] == "1"
    assert ui.metric("Count", 2)["props"]["delta"] is None
    assert ui.divider()["kind"] == "divider"
    assert ui.help(SimpleNamespace(__doc__="fixture docs")).node["props"]["body"] == "fixture docs"
    ui.write({"value": 2}, [1, 2], "markdown body")
    assert [node["kind"] for node in session.roots["main"][-3:]] == ["json", "json", "markdown"]
    with ui.spinner("working") as spinner:
        assert spinner.node["props"]["state"] == "running"
    assert spinner.node["props"]["state"] == "complete"
    assert ui.status("Done", state="complete").node["props"]["state"] == "complete"


def test_duplicate_control_keys_and_numeric_defaults(session):
    assert ui.toggle("Toggle", key="toggle") is False
    assert ui.text_area("Notes", value="kept", key="notes") == "kept"
    assert ui.number_input("Integer", key="integer") == 0
    assert ui.number_input("Fraction", step=0.5, key="fraction") == 0.0
    assert ui.number_input("Lower", min_value=4, key="lower") == 4
    assert ui.slider("Default", key="default") == 0
    assert ui.slider("Lower", min_value=2, key="slider_lower") == 2
    assert ui.slider("Fraction", value=0.25, key="slider_fraction") == 0.25
    assert ui.slider("Range", value=(1, 3), key="slider_range") == (1, 3)
    with pytest.raises(UIError, match="already in use"):
        ui.text_input("Duplicate", key="integer")
    with pytest.raises(UIError, match="numeric range"):
        ui.select_slider("Invalid", [1, 2], value=(1, 2))
    assert ui.select_slider("Valid", ["a", "b"], value="b") == "b"
    assert ui.pills("Multi", ["a", "b"], selection_mode="multi", default=["b"]) == ["b"]
    assert ui.segmented_control("Single", ["a", "b"], default="b") == "b"


@pytest.mark.parametrize("default", [date(2026, 1, 2), datetime(2026, 1, 2), "today"])
def test_date_control_round_trips_python_dates(session, default):
    value = ui.date_input("Day", value=default)
    assert isinstance(value, date) and not isinstance(value, datetime)
    widget = next(iter(session.widgets.values()))
    assert widget.validate("2026-01-03") == date(2026, 1, 3)
    with pytest.raises(UIError, match="Expected a date"):
        widget.validate("not-a-date")


@pytest.mark.parametrize("raw", [["2026-01-01", "2026-01-02", "2026-01-03"],
                                  ["2025-12-31"], ["2026-01-04"], [None]])
def test_date_ranges_reject_invalid_or_out_of_bounds_values(session, raw):
    ui.date_input("Range", value=(date(2026, 1, 1), date(2026, 1, 3)),
                  min_value=date(2026, 1, 1), max_value=date(2026, 1, 3))
    widget = next(iter(session.widgets.values()))
    assert widget.validate(["2026-01-02"]) == (date(2026, 1, 2),)
    with pytest.raises(UIError):
        widget.validate(raw)


@pytest.mark.parametrize("raw", [None, [{}, {}], [None], [{"name": 4, "data": ""}],
                                  [{"name": "bad.exe", "data": ""}],
                                  [{"name": "ok.txt", "data": "%%%"}]])
def test_upload_control_rejects_malformed_or_disallowed_files(session, raw):
    ui.file_uploader("File", type="txt")
    widget = next(iter(session.widgets.values()))
    with pytest.raises(UIError):
        widget.validate(raw)


def test_uploaded_files_are_private_named_buffers_with_multiple_selection(session):
    ui.file_uploader("Files", type=[".TXT"], accept_multiple_files=True)
    widget = next(iter(session.widgets.values()))
    files = widget.validate([{"name": "C:\\private\\fixture.TXT", "data": base64.b64encode(b"hello").decode(), "type": "text/plain"}])
    assert files[0].name == "fixture.TXT"
    assert files[0].size == 5 and files[0].type == "text/plain"
    assert files[0].read() == b"hello"
    assert widget.validate([]) == []


def test_upload_control_enforces_its_size_limit_before_storing(session, monkeypatch):
    ui.file_uploader("File")
    widget = next(iter(session.widgets.values()))
    monkeypatch.setattr(ui.base64, "b64decode", lambda *args, **kwargs: b"x" * (32 * 1024 * 1024 + 1))
    with pytest.raises(UIError, match="too large"):
        widget.validate([{"name": "fixture.txt", "data": "ignored"}])
    assert widget.validate([]) is None


@pytest.mark.parametrize("data,expected", [
    ({"a": [1, 2], "b": 3}, {"columns": ["a", "b"], "rows": [[1, 3]]}),
    ([{"a": 1}, {"a": 2}], {"columns": ["a"], "rows": [[1], [2]]}),
    ([1, 2], {"columns": ["Value"], "rows": [[1], [2]]}),
    (None, {"columns": ["Value"], "rows": []}),
])
def test_table_payload_preserves_records_and_columns(session, data, expected):
    table = ui.table(data)
    assert {key: table.node["props"][key] for key in expected} == expected


@pytest.mark.parametrize("raw", [None, {"rows": "0"}, {"rows": [True]}, {"rows": [-1]},
                                  {"rows": [2]}, {"rows": [0, 1]}])
def test_table_selection_rejects_forged_or_multiple_single_row_indices(session, raw):
    ui.dataframe([{"value": "a"}, {"value": "b"}], on_select="rerun", selection_mode="single-row")
    widget = next(iter(session.widgets.values()))
    assert widget.validate({"rows": [1]}).selection.rows == [1]
    with pytest.raises(UIError):
        widget.validate(raw)


@pytest.mark.parametrize("data", ["download text", b"download text", io.BytesIO(b"download text")])
def test_download_content_remains_in_session_private_assets(session, data):
    assert ui.download_button("Save", data) is False
    asset = next(iter(session.assets.values()))
    assert asset == (b"download text", "application/octet-stream", "download")
    assert session.roots["main"][-1]["props"]["filename"] == "download"


def test_image_file_like_and_external_sources_preserve_mime_and_content(session, tmp_path):
    svg_path = tmp_path / "owned.svg"
    svg_path.write_text("<svg></svg>")
    ui.image(["https://example.invalid/image.png", svg_path, io.StringIO("<svg></svg>"), b"unknown"])
    props = session.roots["main"][-1]["props"]
    assert props["urls"][0] == "https://example.invalid/image.png"
    assert len(props["urls"]) == 4
    assert any(value[:2] == (b"<svg></svg>", "image/svg+xml") for value in session.assets.values())
    assert ui.link_button("Open", "https://example.invalid")["props"]["url"] == "https://example.invalid"
    assert ui.components.v1.iframe("https://example.invalid")["kind"] == "iframe"
    assert ui.components.v1.html("body")["props"]["body"] == "body"


def test_navigation_file_pages_hidden_routes_and_route_errors(session, tmp_path):
    source = tmp_path / "owned_page.py"
    source.write_text("from agi_web import python_ui as ui\nui.text('file view')\n")
    home = ui.Page(lambda: ui.text("home"), default=True, title="Home")
    file_page = ui.Page(source, visibility="hidden", url_path="/file/")
    assert ui.navigation({"Views": [home, file_page]}, position="top") is home
    assert len(session.roots["main"][0]["children"]) == 1
    session.set_location("/file", {"old": "value"})
    assert ui.navigation([home, file_page], position="hidden") is file_page
    file_page.run()
    assert session.roots["main"][-1]["props"]["body"] == "file view"
    assert ui.page_link(source)["props"]["url"] == "/file"
    assert ui.page_link("https://example.invalid")["props"]["url"] == "https://example.invalid"
    with pytest.raises(RerunView):
        ui.switch_page(source, query_params={"new": "value"})
    assert session.query == {"new": "value"}
    with pytest.raises(UIError, match="parameters"):
        ui.switch_page(home, query_params=[])
    with pytest.raises(UIError, match="registered"):
        ui.switch_page(tmp_path / "missing.py")
    with pytest.raises(UIError, match="registered"):
        ui.page_link(tmp_path / "missing.py")
    with pytest.raises(UIError, match="No application"):
        ui.navigation([])


def test_dialog_and_fragment_refresh_are_scoped_to_the_view():
    @ui.fragment(run_every=timedelta(seconds=3))
    def refresh(): return "refreshed"
    assert refresh() == "refreshed"
    def view():
        refresh()
        ui.fragment(lambda: None, run_every="2s")()
        @ui.dialog("Details")
        def detail(value): ui.text(value)
        detail("dialog body")
    session = ViewSession(view)
    payload = session.render()
    assert payload["auto_refresh"] == 2
    assert payload["nodes"]["main"][-1]["kind"] == "dialog"
    assert payload["nodes"]["main"][-1]["children"][0]["props"]["body"] == "dialog body"
    with use_session(session), pytest.raises(RerunView):
        ui.rerun(scope="fragment")
    assert session.active_dialog is not None
    with use_session(session), pytest.raises(RerunView):
        ui.rerun()
    assert session.active_dialog is None


def test_cached_results_expire_evict_and_bypass_unserializable_arguments(monkeypatch):
    ui.cache_data.clear()
    clock = [0.0]
    monkeypatch.setattr(ui.time, "monotonic", lambda: clock[0])
    calls = []
    @ui.cache_data(ttl=timedelta(seconds=2), max_entries=1)
    def calculate(value):
        calls.append(value)
        return [value]
    assert calculate(1) == calculate(1) == [1]
    clock[0] = 3
    assert calculate(1) == [1]
    assert calculate(2) == [2]
    assert calculate(1) == [1]
    assert calls == [1, 1, 2, 1]
    class Unserializable:
        def __reduce__(self): raise TypeError("not serializable")
    value = Unserializable()
    calculate(value)
    calculate(value)
    assert calls[-2:] == [value, value]
    calculate.clear()
    ui.cache_data.clear()



def test_optional_plot_adapters_preserve_library_assets_and_figure_arguments(session, monkeypatch):
    calls = []
    plotly = ModuleType("plotly")
    plotly.__path__ = []
    plotly.io = ModuleType("plotly.io")
    plotly.io.to_json = lambda figure: '{"data": ["' + figure + '"]}'
    offline = ModuleType("plotly.offline")
    offline.get_plotlyjs = lambda: "fixture plotly library"
    express = ModuleType("plotly.express")
    express.line = lambda data, x, y: calls.append(("line", data, x, y)) or "line figure"
    express.bar = lambda data, x, y: calls.append(("bar", data, x, y)) or "bar figure"
    plotly.offline, plotly.express = offline, express
    for name, module in [("plotly", plotly), ("plotly.io", plotly.io),
                         ("plotly.offline", offline), ("plotly.express", express)]:
        monkeypatch.setitem(sys.modules, name, module)
    assert ui.line_chart([1], x="x", y="y")["props"]["figure"] == {"data": ["line figure"]}
    assert ui.bar_chart([2])["props"]["figure"] == {"data": ["bar figure"]}
    assert calls == [("line", [1], "x", "y"), ("bar", [2], None, None)]
    assert any(asset[:2] == (b"fixture plotly library", "text/javascript") for asset in session.assets.values())
    assert ui.altair_chart({"mark": "point"})["props"]["spec"] == {"mark": "point"}
    assert ui.altair_chart(SimpleNamespace(to_dict=lambda: {"mark": "bar"}))["props"]["spec"] == {"mark": "bar"}
    assert ui.graphviz_chart("digraph{a->b}")["props"]["source"] == "digraph{a->b}"
    assert ui.graphviz_chart(SimpleNamespace(source="graph{a--b}"))["props"]["source"] == "graph{a--b}"
    deck = SimpleNamespace(to_html=lambda **kwargs: "deck" if kwargs == {"as_string": True} else "wrong")
    assert ui.pydeck_chart(deck)["props"]["body"] == "deck"


def test_plot_and_image_adapters_encode_provider_results_as_private_png_assets(session, monkeypatch):
    class Figure:
        def savefig(self, buffer, **kwargs):
            assert kwargs == {"format": "png", "bbox_inches": "tight"}
            buffer.write(b"owned figure PNG")
    figure = Figure()
    matplotlib = ModuleType("matplotlib")
    matplotlib.__path__ = []
    pyplot = ModuleType("matplotlib.pyplot")
    pyplot.gcf = lambda: figure
    matplotlib.pyplot = pyplot
    monkeypatch.setitem(sys.modules, "matplotlib", matplotlib)
    monkeypatch.setitem(sys.modules, "matplotlib.pyplot", pyplot)
    ui.pyplot()
    ui.pyplot(figure)
    class Image:
        def save(self, buffer, **kwargs):
            assert kwargs == {"format": "PNG"}
            buffer.write(b"owned image PNG")
    pil = ModuleType("PIL")
    pil.Image = SimpleNamespace(fromarray=lambda array: Image())
    monkeypatch.setitem(sys.modules, "PIL", pil)
    ui.image(Image())
    ui.image(object())
    assert any(asset[:2] == (b"owned figure PNG", "image/png") for asset in session.assets.values())
    assert any(asset[:2] == (b"owned image PNG", "image/png") for asset in session.assets.values())


def test_frame_and_array_values_are_rendered_as_tables(session):
    class Array:
        def __iter__(self): return iter([1, 2])
        def tolist(self): return [1, 2]
    class Frame:
        columns = ["value"]
        def reset_index(self): return self
        def to_dict(self): return {"value": [1, 2]}
        def to_numpy(self): return SimpleNamespace(tolist=lambda: [[1], [2]])
    ui.write(Frame())
    assert session.roots["main"][-1]["props"]["rows"] == [[1], [2]]
    table = ui.dataframe({"value": Array()})
    assert table.node["props"]["rows"] == [[1], [2]]


def test_fragmentless_stop_and_non_session_address_configuration(monkeypatch):
    monkeypatch.delenv("AGILAB_UI_HOST", raising=False)
    monkeypatch.setenv("AGILAB_UI_ADDRESS", " 127.0.0.3 ")
    assert ui.get_option("address") == "127.0.0.3"
    monkeypatch.setenv("AGILAB_UI_HOST", "127.0.0.2")
    assert ui.get_option("server.address") == "127.0.0.2"
    monkeypatch.delenv("AGILAB_UI_HOST")
    monkeypatch.delenv("AGILAB_UI_ADDRESS")
    assert ui.get_option("address") == "127.0.0.1"
    assert ViewSession(ui.stop).render()["error"] == ""


def test_component_duplicate_keys_config_and_private_secret_files(session, monkeypatch, tmp_path):
    component = ui.components.v2.component("fixture_component", js="export default () => {}", css="p{}")
    result = component(key="unique", data={"value": 1}, default={"kept": 2}, on_change_change=None)
    assert result.kept == 2 and result.change is None
    with pytest.raises(UIError, match="already in use"):
        component(key="unique")
    ui.set_page_config(server_address="127.0.0.2")
    assert ui.get_option("server.address") == "127.0.0.2"
    assert ui.get_option("unknown") is None
    assert ui.runtime.exists()
    assert ui.runtime.get_instance().bidi_component_registry is not None
    assert ui.get_script_run_ctx().session_state is session.state
    assert ui.column_config.NumberColumn("Amount", min_value=0) == {"kind": "NumberColumn", "label": "Amount", "min_value": 0}
    secret_path = tmp_path / "fixture_secrets.toml"
    monkeypatch.setenv("AGILAB_SECRETS_FILE", str(secret_path))
    assert len(ui.secrets) == 0 and list(ui.secrets) == []
    secret_path.write_text('fixture = "synthetic fixture value"\n')
    assert list(ui.secrets) == ["fixture"] and len(ui.secrets) == 1
    assert ui.secrets.fixture == ui.secrets["fixture"] == "synthetic fixture value"
    with pytest.raises(AttributeError):
        _ = ui.secrets.missing
