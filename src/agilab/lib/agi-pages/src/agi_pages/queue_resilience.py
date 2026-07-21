"""Shared lifecycle and rendering support for queue-resilience pages.

The owning page bundles inject their Streamlit, environment, and dataframe
implementations so ``agi-pages`` keeps its lightweight dependency boundary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .runtime import (
    artifact_root,
    configure_streamlit_page,
    discover_files,
    ensure_app_scoped_env,
    render_streamlit_page_header,
    resolve_active_app_path,
    safe_metric,
)


QUEUE_PEER_CSV_SUFFIXES = (
    "queue_timeseries",
    "packet_events",
    "node_positions",
    "routing_summary",
)
QUEUE_ARTIFACT_SUBDIR = "queue_analysis"
QUEUE_SUMMARY_GLOB = "**/*_summary_metrics.json"
QUEUE_PIPELINE_INFO = (
    "Each run also writes `pipeline/topology.gml`, `pipeline/allocations_steps.csv`, "
    "`pipeline/_trajectory_summary.json`, and per-node trajectory CSVs so the same result "
    "can be explored in `view_maps_network`."
)


@dataclass(frozen=True, slots=True)
class QueueResiliencePageContext:
    """Resolved app environment and queue-summary inventory for one page run."""

    active_app_path: Path
    env: Any
    artifact_root: Path
    summary_files: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class QueueResilienceRun:
    """One validated queue run with dataframe objects supplied by the page."""

    summary_path: Path
    summary: Mapping[str, Any]
    queue_frame: Any
    packet_frame: Any
    positions_frame: Any
    routing_frame: Any


def prepare_queue_resilience_page(
    streamlit: Any,
    *,
    env_factory: Callable[[Path], Any],
    title: str,
    logo_title: str,
    caption: str,
    data_dir_key: str,
    summary_glob_key: str,
    app_scope_key: str,
    app_scoped_keys: tuple[str, ...],
) -> QueueResiliencePageContext:
    """Render common page setup and return the available queue summaries."""

    configure_streamlit_page(streamlit, title=title)
    active_app_path = resolve_active_app_path(
        error_fn=streamlit.error,
        stop_fn=streamlit.stop,
    )

    env = ensure_app_scoped_env(
        streamlit.session_state,
        active_app_path,
        scope_key=app_scope_key,
        env_factory=env_factory,
        keys=app_scoped_keys,
    )
    render_streamlit_page_header(
        streamlit,
        title=title,
        logo_title=logo_title,
        caption=caption,
    )
    streamlit.info(QUEUE_PIPELINE_INFO)

    default_root = artifact_root(env, QUEUE_ARTIFACT_SUBDIR)
    streamlit.session_state.setdefault(data_dir_key, str(default_root))
    artifact_root_value = streamlit.sidebar.text_input(
        "Artifact directory",
        key=data_dir_key,
    )
    selected_artifact_root = Path(artifact_root_value).expanduser()

    streamlit.session_state.setdefault(summary_glob_key, QUEUE_SUMMARY_GLOB)
    summary_pattern = streamlit.sidebar.text_input(
        "Summary glob",
        key=summary_glob_key,
    )
    summary_files = (
        tuple(discover_files(selected_artifact_root, summary_pattern))
        if selected_artifact_root.exists()
        else ()
    )

    if not selected_artifact_root.exists():
        streamlit.warning(
            f"Artifact directory does not exist yet: {selected_artifact_root}"
        )
        streamlit.stop()
    if not summary_files:
        streamlit.warning(
            f"No summary metrics file found in {selected_artifact_root} "
            f"with pattern {summary_pattern!r}."
        )
        streamlit.stop()

    return QueueResiliencePageContext(
        active_app_path=active_app_path,
        env=env,
        artifact_root=selected_artifact_root,
        summary_files=summary_files,
    )


def peer_csv_path(summary_path: Path, suffix: str) -> Path:
    """Return one CSV path belonging to a queue summary export."""

    stem = summary_path.name.removesuffix("_summary_metrics.json")
    return summary_path.with_name(f"{stem}_{suffix}.csv")


def queue_peer_csv_paths(summary_path: Path) -> dict[str, Path]:
    """Return the queue-analysis CSV paths associated with a summary export."""

    return {
        suffix: peer_csv_path(summary_path, suffix)
        for suffix in QUEUE_PEER_CSV_SUFFIXES
    }


def load_queue_summary(path: Path) -> dict[str, Any]:
    """Load one queue summary JSON object."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"Queue summary must contain a JSON object: {path}")
    return payload


def load_queue_resilience_run(
    streamlit: Any,
    summary_path: Path,
    *,
    csv_loader: Callable[[Path], Any],
) -> QueueResilienceRun:
    """Validate and load the detail artifacts associated with one summary."""

    summary_path = Path(summary_path)
    peer_paths = queue_peer_csv_paths(summary_path)
    missing = tuple(path for path in peer_paths.values() if not path.is_file())
    if missing:
        streamlit.error("Related queue artifacts are missing for the selected summary:")
        for path in missing:
            streamlit.code(str(path))
        streamlit.stop()

    return QueueResilienceRun(
        summary_path=summary_path,
        summary=load_queue_summary(summary_path),
        queue_frame=csv_loader(peer_paths["queue_timeseries"]),
        packet_frame=csv_loader(peer_paths["packet_events"]),
        positions_frame=csv_loader(peer_paths["node_positions"]),
        routing_frame=csv_loader(peer_paths["routing_summary"]),
    )


def render_queue_resilience_run(streamlit: Any, run: QueueResilienceRun) -> None:
    """Render a validated queue run using the shared detail surface."""

    render_queue_resilience_detail(
        streamlit,
        summary=run.summary,
        queue_frame=run.queue_frame,
        packet_frame=run.packet_frame,
        positions_frame=run.positions_frame,
        routing_frame=run.routing_frame,
    )


def render_queue_resilience_detail(
    streamlit: Any,
    *,
    summary: Mapping[str, Any],
    queue_frame: Any,
    packet_frame: Any,
    positions_frame: Any,
    routing_frame: Any,
) -> None:
    """Render the shared single-run queue and relay evidence surface.

    Frames are supplied by the owning page so this support module does not add a
    pandas dependency to ``agi-pages``.
    """

    intro_left, intro_right = streamlit.columns([1.6, 1.2])
    with intro_left:
        streamlit.subheader("Why this run is useful")
        streamlit.markdown(
            "- one scenario file becomes a reproducible project\n"
            "- one routing knob changes queue buildup and delivery outcomes\n"
            "- the exported packet and queue telemetry stays explorable across reruns\n"
            "- the producer can later be swapped while preserving the analysis contract"
        )
    with intro_right:
        streamlit.subheader("Run metadata")
        streamlit.json(
            {
                "scenario": summary.get("scenario"),
                "routing_policy": summary.get("routing_policy"),
                "source_rate_pps": summary.get("source_rate_pps"),
                "random_seed": summary.get("random_seed"),
                "bottleneck_relay": summary.get("bottleneck_relay"),
            }
        )

    metric_columns = streamlit.columns(4)
    metric_specs = (
        ("PDR", summary.get("pdr")),
        ("Mean delay (ms)", summary.get("mean_e2e_delay_ms")),
        ("Queue wait (ms)", summary.get("mean_queue_wait_ms")),
        ("Max queue", summary.get("max_queue_depth_pkts")),
    )
    for column, (label, value) in zip(metric_columns, metric_specs, strict=False):
        column.metric(label, safe_metric(value))

    streamlit.subheader("Queue occupancy over time")
    queue_chart = queue_frame.pivot_table(
        index="time_s",
        columns="relay",
        values="queue_depth_pkts",
        aggfunc="last",
    ).sort_index()
    streamlit.line_chart(queue_chart)

    relay_positions = positions_frame.loc[positions_frame["role"] == "relay"].copy()
    if not relay_positions.empty:
        streamlit.subheader("Relay mobility trace (y axis)")
        relay_chart = relay_positions.pivot_table(
            index="time_s",
            columns="node",
            values="y_m",
            aggfunc="last",
        ).sort_index()
        streamlit.line_chart(relay_chart)

    if not routing_frame.empty:
        streamlit.subheader("Route usage")
        route_metrics = routing_frame.set_index("relay")[
            ["packets_delivered", "packets_dropped"]
        ]
        streamlit.bar_chart(route_metrics)
        streamlit.dataframe(routing_frame, width="stretch", hide_index=True)

    source_packets = packet_frame.loc[packet_frame["origin_kind"] == "source"].copy()
    delivered_packets = source_packets.loc[
        source_packets["status"] == "delivered"
    ].copy()
    if not delivered_packets.empty:
        streamlit.subheader("Highest-delay source packets")
        slowest = delivered_packets.sort_values("e2e_delay_ms", ascending=False).head(
            30
        )
        streamlit.dataframe(slowest, width="stretch", hide_index=True)
    else:
        streamlit.info("No delivered source packet is available in this run.")

    notes = str(summary.get("notes", "") or "").strip()
    if notes:
        streamlit.subheader("Notes")
        streamlit.info(notes)
