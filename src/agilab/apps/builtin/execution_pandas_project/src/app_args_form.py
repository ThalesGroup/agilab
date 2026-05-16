from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import streamlit as st
from pydantic import ValidationError

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from execution_pandas.app_args import ExecutionPandasArgs, dump_args, load_args


PAGE_ID = "execution_pandas_project:app_args_form"


def _k(name: str) -> str:
    return f"{PAGE_ID}:{name}"


def _get_env():
    env = st.session_state.get("env") or st.session_state.get("_env")
    if env is None:
        st.error("AGILab environment is not initialised yet. Return to the main page and try again.")
        st.stop()
    return env


def _load_current_args(settings_path: Path) -> ExecutionPandasArgs:
    try:
        return load_args(settings_path)
    except Exception as exc:
        st.warning(f"Unable to load Execution Pandas args from `{settings_path}`: {exc}")
        return ExecutionPandasArgs()


def _safe_rows_per_partition(rows_per_file: int, n_partitions: int) -> int:
    if n_partitions <= 0:
        return 0
    return rows_per_file // n_partitions


env = _get_env()
settings_path = Path(env.app_settings_file)
current_args = _load_current_args(settings_path)
current_payload = current_args.model_dump(mode="json")

st.caption(
    "Execution Pandas generates a synthetic CSV dataset and runs the distributed Pandas worker path. "
    "Use this form to size the playground workload before EXECUTE."
)

for key, default in (
    ("data_in", str(current_payload.get("data_in", "execution_playground/dataset") or "execution_playground/dataset")),
    ("data_out", str(current_payload.get("data_out", "execution_pandas/results") or "execution_pandas/results")),
    ("files", str(current_payload.get("files", "*.csv") or "*.csv")),
    ("nfile", int(current_payload.get("nfile", 16) or 16)),
    ("n_partitions", int(current_payload.get("n_partitions", 16) or 16)),
    ("rows_per_file", int(current_payload.get("rows_per_file", 100_000) or 100_000)),
    ("n_groups", int(current_payload.get("n_groups", 32) or 32)),
    ("compute_passes", int(current_payload.get("compute_passes", 32) or 32)),
    ("kernel_mode", str(current_payload.get("kernel_mode", "typed_numeric") or "typed_numeric")),
    ("output_format", str(current_payload.get("output_format", "csv") or "csv")),
    ("seed", int(current_payload.get("seed", 42) or 42)),
    ("reset_target", bool(current_payload.get("reset_target", False))),
):
    st.session_state.setdefault(_k(key), default)

c1, c2, c3 = st.columns([2, 2, 1.2])
with c1:
    st.text_input("Dataset directory", key=_k("data_in"))
with c2:
    st.text_input("Results directory", key=_k("data_out"))
with c3:
    st.selectbox("Output format", options=["csv", "parquet"], key=_k("output_format"))

c4, c5, c6, c7 = st.columns([1.2, 1.2, 1.2, 1.2])
with c4:
    st.text_input("Files glob", key=_k("files"))
with c5:
    st.number_input("Files", key=_k("nfile"), min_value=1, step=1)
with c6:
    st.number_input("Partitions", key=_k("n_partitions"), min_value=1, step=1)
with c7:
    st.number_input("Rows / file", key=_k("rows_per_file"), min_value=1, step=10_000)

c8, c9, c10, c11 = st.columns([1.2, 1.2, 1.2, 1.2])
with c8:
    st.number_input("Groups", key=_k("n_groups"), min_value=1, step=1)
with c9:
    st.number_input("Compute passes", key=_k("compute_passes"), min_value=1, step=1)
with c10:
    st.selectbox(
        "Kernel",
        options=["typed_numeric", "dataframe"],
        format_func=lambda value: "Typed numeric" if value == "typed_numeric" else "DataFrame",
        key=_k("kernel_mode"),
    )
with c11:
    st.checkbox("Reset output", key=_k("reset_target"))

c12, _ = st.columns([1.2, 3.6])
with c12:
    st.number_input("Seed", key=_k("seed"), min_value=0, step=1)

candidate: dict[str, Any] = {
    "data_in": (st.session_state.get(_k("data_in")) or "").strip(),
    "data_out": (st.session_state.get(_k("data_out")) or "").strip(),
    "files": (st.session_state.get(_k("files")) or "*.csv").strip() or "*.csv",
    "nfile": st.session_state.get(_k("nfile"), 16),
    "n_partitions": st.session_state.get(_k("n_partitions"), 16),
    "rows_per_file": st.session_state.get(_k("rows_per_file"), 100_000),
    "n_groups": st.session_state.get(_k("n_groups"), 32),
    "compute_passes": st.session_state.get(_k("compute_passes"), 32),
    "kernel_mode": st.session_state.get(_k("kernel_mode")) or "typed_numeric",
    "output_format": st.session_state.get(_k("output_format")) or "csv",
    "seed": st.session_state.get(_k("seed"), 42),
    "reset_target": bool(st.session_state.get(_k("reset_target"), False)),
}

try:
    validated = ExecutionPandasArgs(**candidate)
except ValidationError as exc:
    st.error("Invalid Execution Pandas parameters:")
    if hasattr(env, "humanize_validation_errors"):
        for msg in env.humanize_validation_errors(exc):
            st.markdown(msg)
    else:
        st.code(str(exc))
else:
    validated_payload = validated.model_dump(mode="json")
    if validated_payload != current_payload:
        dump_args(validated, settings_path)
        app_settings = st.session_state.get("app_settings")
        if not isinstance(app_settings, dict):
            app_settings = {}
        app_settings.setdefault("cluster", {})
        app_settings["args"] = validated_payload
        st.session_state["app_settings"] = app_settings
        st.session_state["is_args_from_ui"] = True
        st.success(f"Saved to `{settings_path}`.")
    else:
        st.info("No changes to save.")

    total_rows = validated.nfile * validated.rows_per_file
    rows_per_partition = _safe_rows_per_partition(validated.rows_per_file, validated.n_partitions)
    st.caption(
        f"Planned workload: `{validated.nfile}` files, about `{total_rows:,}` rows total, "
        f"`{validated.n_partitions}` partitions per file, about `{rows_per_partition:,}` rows per partition, "
        f"`{validated.kernel_mode}` kernel."
    )
