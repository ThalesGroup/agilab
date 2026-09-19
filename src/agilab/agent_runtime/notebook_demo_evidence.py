"""Build evidence and local-builder instructions shared by the public demos."""
from __future__ import annotations

import streamlit as st


def render_build_evidence(report: dict, *, extra_metrics: tuple[tuple[str, int], ...] = ()) -> None:
    """Render the common header and builder handoff after verifying the receipt."""
    st.title("Built by an autonomous agent")
    with st.container(horizontal=True, wrap=True):
        st.metric("Autonomous build", f"{report['seconds'] / 60:.2f} min", width=200)
        st.metric("AGILAB workflow stages", report["workflow_stages"], width=200)
        for label, value in extra_metrics:
            st.metric(label, value, width=200)
    st.caption(
        "This public Space runs the completed app. New autonomous builds run in a local "
        "Tokki environment with your configured provider."
    )
    with st.expander("Build from your own notebook", icon=":material/rocket_launch:"):
        st.write(
            "Run the builder on your computer with your own Tokki installation and configured "
            "Codex provider. Start with a self-contained Python notebook using data and "
            "dependencies available locally."
        )
        st.markdown(
            "1. Set up your licensed [Tokki installation]"
            "(https://github.com/jpmorard/tokki-public/blob/main/RELEASES.md) and provider.\n"
            "2. Install the AGILAB builder with [uv]"
            "(https://docs.astral.sh/uv/getting-started/installation/).\n"
            "3. Open the local interface and choose **Local notebook** or **Pinned GitHub notebook**."
        )
        st.code(
            'uv tool install "agilab[notebook-agent] @ git+https://github.com/ThalesGroup/agilab.git"\n'
            "agilab-notebook-demo --ui",
            language="bash",
        )
        st.caption(
            "Your notebook and provider credentials stay out of this public Space. The local agent "
            "reads your notebook through your provider and executes generated Python on your "
            "computer. Checks establish execution and interface behavior; review scientific "
            "conclusions yourself."
        )
        st.write(
            "After your first successful build, the local app offers a completion receipt you can "
            "voluntarily report on GitHub. It contains no notebook or credentials. Nothing is "
            "uploaded automatically; a public report is associated with your GitHub account."
        )
