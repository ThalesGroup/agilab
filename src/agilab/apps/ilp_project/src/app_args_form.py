"""Streamlit UI for ILP application parameters."""

from __future__ import annotations

import streamlit as st
from pydantic import ValidationError

from agi_env.streamlit_args import load_args_state, persist_args, render_form
import ilp as args_module
from ilp import ArgsModel


env = st.session_state._env

defaults_model, defaults_payload, settings_path = load_args_state(env, args_module=args_module)

if not st.session_state.get("toggle_edit", False):
    col1, col2 = st.columns(2)

    with col1:
        topology = st.text_input("Topology", value=defaults_model.topology)
        num_demands = st.number_input("Number of demands", min_value=1, value=int(defaults_model.num_demands))

    with col2:
        seed = st.number_input("Random seed", value=int(defaults_model.seed))
        demand_scale = st.number_input(
            "Demand scale",
            min_value=0.1,
            step=0.1,
            value=float(defaults_model.demand_scale),
        )

    form_values = {
        "topology": topology,
        "num_demands": int(num_demands),
        "seed": int(seed),
        "demand_scale": float(demand_scale),
        "data_uri": str(defaults_model.data_uri),
    }
else:
    form_values = render_form(defaults_model)

try:
    parsed = ArgsModel(**form_values)
except ValidationError as exc:  # pragma: no cover - UI feedback only
    messages = env.humanize_validation_errors(exc)
    st.warning("\n".join(messages))
    st.session_state.pop("is_args_from_ui", None)
else:
    persist_args(args_module, parsed, settings_path=settings_path, defaults_payload=defaults_payload)
    st.success("All params are valid!")
