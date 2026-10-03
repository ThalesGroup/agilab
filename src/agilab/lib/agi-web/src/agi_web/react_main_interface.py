"""React workspace chrome hosted by Streamlit, with one-shot Python actions.

Importing this adapter does not import Streamlit or affect notebook renderers.
"""

from functools import lru_cache
from importlib.resources import files
from typing import Any, Callable, Mapping


@lru_cache(maxsize=2)
def _asset(name: str) -> str:
    return files("agi_web").joinpath("react_main_interface_assets", name).read_text(encoding="utf-8")


@lru_cache(maxsize=8)
def _mount(factory: Callable[..., Any], manager: Any) -> Any:
    return factory(
        "agilab_react_main_interface",
        js=_asset("agilab_react_main_interface.js"),
        css=_asset("agilab_react_main_interface.css"),
        isolate_styles=True,
    )


def render_main_interface(streamlit: Any, data: Mapping[str, Any]) -> Any:
    """Render controlled navigation/project inputs; actions expire after a rerun."""
    factory = streamlit.components.v2.component
    runtime = getattr(streamlit, "runtime", None)
    manager = runtime.get_instance().bidi_component_registry if runtime and runtime.exists() else factory
    return _mount(factory, manager)(
        key="agilab:main-interface",
        data=dict(data),
        height="content",
        width="stretch",
        on_action_change=lambda: None,
    )
