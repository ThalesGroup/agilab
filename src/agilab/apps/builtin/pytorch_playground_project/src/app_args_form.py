from __future__ import annotations

from pathlib import Path
import sys

import streamlit as st
from pydantic import ValidationError

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from agi_env.streamlit_args import load_args_state, persist_args, render_form
from pytorch_playground import app_args


def _get_env():
    env = st.session_state.get("env") or st.session_state.get("_env")
    if env is None:
        st.error("AGILAB environment is not initialised yet. Return to the main page and try again.")
        st.stop()
    return env


env = _get_env()
defaults_model, defaults_payload, settings_path = load_args_state(env, args_module=app_args)

artifact_root = Path(getattr(env, "AGILAB_EXPORT_ABS", Path.home() / "export")) / env.target / "pytorch_playground"

st.caption(
    "PyTorch Playground is an executable app: ORCHESTRATE runs the configured "
    "training job and exports replayable evidence."
)
st.caption(f"Analysis artifacts are exported to `{artifact_root}`.")

with st.sidebar:
    st.markdown("### PyTorch Playground")
    st.caption("These fields are persisted as app arguments.")
    form_values = render_form(defaults_model, container=st.sidebar)

try:
    parsed = app_args.ensure_defaults(app_args.ArgsModel(**form_values), env=env)
except ValidationError as exc:
    st.error("\n".join(env.humanize_validation_errors(exc)))
else:
    try:
        config = app_args.to_playground_config(parsed)
    except ValueError as exc:
        st.error(str(exc))
    else:
        persist_args(
            app_args,
            parsed,
            settings_path=settings_path,
            defaults_payload=defaults_payload,
        )
        st.json(
            {
                "dataset": config.dataset,
                "samples": config.sample_count,
                "features": list(config.feature_names),
                "hidden_layers": list(config.hidden_layers),
                "epochs": config.epochs,
                "loss_landscape": parsed.compute_loss_landscape,
            }
        )
