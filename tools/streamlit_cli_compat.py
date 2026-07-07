#!/usr/bin/env python3
"""Run Streamlit while repairing the Streamlit 1.58 top-level facade.

Streamlit 1.58.0 shipped with an empty top-level ``streamlit`` module while
internal CLI modules still import public names such as ``streamlit.secrets``.
AGILAB launches through this wrapper so source checkouts can keep accepting the
latest Streamlit release without patching site-packages or downgrading.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import os
import sys
from types import ModuleType
from typing import Any


_MAIN_DELTA_METHODS = (
    "altair_chart",
    "area_chart",
    "audio",
    "audio_input",
    "badge",
    "balloons",
    "bar_chart",
    "_bidi_component",
    "bokeh_chart",
    "button",
    "caption",
    "camera_input",
    "chat_message",
    "chat_input",
    "checkbox",
    "code",
    "columns",
    "tabs",
    "container",
    "dataframe",
    "data_editor",
    "date_input",
    "datetime_input",
    "divider",
    "download_button",
    "expander",
    "feedback",
    "pydeck_chart",
    "empty",
    "error",
    "exception",
    "file_uploader",
    "form",
    "form_submit_button",
    "graphviz_chart",
    "header",
    "help",
    "html",
    "iframe",
    "image",
    "info",
    "json",
    "latex",
    "line_chart",
    "link_button",
    "map",
    "markdown",
    "menu_button",
    "metric",
    "multiselect",
    "number_input",
    "page_link",
    "pdf",
    "pills",
    "plotly_chart",
    "popover",
    "progress",
    "pyplot",
    "radio",
    "scatter_chart",
    "selectbox",
    "select_slider",
    "segmented_control",
    "slider",
    "snow",
    "space",
    "spinner",
    "subheader",
    "success",
    "table",
    "text",
    "text_area",
    "text_input",
    "toggle",
    "time_input",
    "title",
    "vega_lite_chart",
    "video",
    "warning",
    "write",
    "write_stream",
    "color_picker",
    "status",
)


def _import_attr(module_name: str, attr_name: str) -> Any:
    return getattr(importlib.import_module(module_name), attr_name)


def _streamlit_version() -> str | None:
    try:
        return importlib.metadata.version("streamlit")
    except importlib.metadata.PackageNotFoundError:
        return None


def _install_streamlit_facade(streamlit: ModuleType) -> None:
    os.environ.setdefault("MPLBACKEND", "Agg")

    version = _streamlit_version()
    if version is not None:
        streamlit.__version__ = version

    DeltaGeneratorSingleton = _import_attr(
        "streamlit.delta_generator_singletons",
        "DeltaGeneratorSingleton",
    )
    DeltaGenerator = _import_attr("streamlit.delta_generator", "DeltaGenerator")
    StatusContainer = _import_attr(
        "streamlit.elements.lib.mutable_status_container",
        "StatusContainer",
    )
    Dialog = _import_attr("streamlit.elements.lib.dialog", "Dialog")
    ExpanderContainer = _import_attr(
        "streamlit.elements.lib.mutable_expander_container",
        "ExpanderContainer",
    )
    TabContainer = _import_attr("streamlit.elements.lib.mutable_tab_container", "TabContainer")
    PopoverContainer = _import_attr(
        "streamlit.elements.lib.mutable_popover_container",
        "PopoverContainer",
    )

    dg_singleton = DeltaGeneratorSingleton(
        delta_generator_cls=DeltaGenerator,
        status_container_cls=StatusContainer,
        dialog_container_cls=Dialog,
        expander_container_cls=ExpanderContainer,
        tab_container_cls=TabContainer,
        popover_container_cls=PopoverContainer,
    )
    streamlit._dg_singleton = dg_singleton
    streamlit._main = dg_singleton._main_dg
    streamlit.sidebar = dg_singleton._sidebar_dg
    streamlit._event = dg_singleton._event_dg

    try:
        BottomContainerProxy = _import_attr("streamlit.elements.bottom", "BottomContainerProxy")
        streamlit.bottom = BottomContainerProxy(dg_singleton._bottom_dg)
    except Exception:
        streamlit.bottom = dg_singleton._bottom_dg
    streamlit._bottom = dg_singleton._bottom_dg

    streamlit.echo = _import_attr("streamlit.commands.echo", "echo")
    streamlit.logo = _import_attr("streamlit.commands.logo", "logo")
    streamlit.navigation = _import_attr("streamlit.commands.navigation", "navigation")
    streamlit.Page = _import_attr("streamlit.navigation.page", "Page")
    streamlit.set_page_config = _import_attr("streamlit.commands.page_config", "set_page_config")
    streamlit.stop = _import_attr("streamlit.commands.execution_control", "stop")
    streamlit.rerun = _import_attr("streamlit.commands.execution_control", "rerun")
    streamlit.switch_page = _import_attr("streamlit.commands.execution_control", "switch_page")

    config = importlib.import_module("streamlit.config")
    gather_metrics = _import_attr("streamlit.runtime.metrics_util", "gather_metrics")
    streamlit.get_option = gather_metrics("get_option", config.get_option)
    streamlit.set_option = gather_metrics("set_option", config.set_user_option)

    streamlit.secrets = _import_attr("streamlit.runtime.secrets", "secrets_singleton")
    streamlit.session_state = _import_attr("streamlit.runtime.state", "SessionStateProxy")()
    streamlit.query_params = _import_attr("streamlit.runtime.state", "QueryParamsProxy")()
    streamlit.context = _import_attr("streamlit.runtime.context", "ContextProxy")()
    streamlit.cache_data = _import_attr("streamlit.runtime.caching", "cache_data")
    streamlit.cache_resource = _import_attr("streamlit.runtime.caching", "cache_resource")
    streamlit.cache = _import_attr("streamlit.runtime.caching", "cache")
    streamlit.column_config = importlib.import_module("streamlit.column_config")
    streamlit.connection = _import_attr("streamlit.runtime.connection_factory", "connection_factory")
    streamlit.dialog = _import_attr("streamlit.elements.dialog_decorator", "dialog_decorator")
    streamlit.fragment = _import_attr("streamlit.runtime.fragment", "fragment")
    streamlit.login = _import_attr("streamlit.user_info", "login")
    streamlit.logout = _import_attr("streamlit.user_info", "logout")
    streamlit.user = _import_attr("streamlit.user_info", "UserInfoProxy")()
    streamlit.App = _import_attr("streamlit.starlette", "App")

    for name in _MAIN_DELTA_METHODS:
        setattr(streamlit, name, getattr(streamlit._main, name))
    streamlit.toast = streamlit._event.toast

    importlib.import_module("streamlit.components.v1")
    importlib.import_module("streamlit.components.v2")


def patch_streamlit_top_level() -> None:
    streamlit = importlib.import_module("streamlit")
    if getattr(streamlit, "__version__", None) and hasattr(streamlit, "secrets") and hasattr(streamlit, "write"):
        return
    _install_streamlit_facade(streamlit)


def main() -> int:
    patch_streamlit_top_level()
    from streamlit.web.cli import main as streamlit_main

    result = streamlit_main()
    return 0 if result is None else int(result)


if __name__ == "__main__":
    raise SystemExit(main())
