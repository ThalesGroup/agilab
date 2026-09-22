"""Build evidence and local-builder instructions shared by the public demos."""
from __future__ import annotations

import streamlit as st


def render_build_evidence(report: dict, *, extra_metrics: tuple[tuple[str, int], ...] = ()) -> None:
    """Render the common header and builder handoff after verifying the receipt."""
    cluster = report.get("cluster_build")
    st.title("Built by OpenCode with local Qwen" if cluster else "Built by an autonomous agent")
    with st.container(horizontal=True, wrap=True):
        st.metric("Build duration" if cluster else "Autonomous build", f"{report['seconds'] / 60:.2f} min", width=200)
        st.metric("AGILAB workflow stages", report["workflow_stages"], width=200)
        if metrics := report.get("code_metrics"):
            st.metric("Generated Python · KLOC", f"{metrics['kloc']:.3f}", width=200)
            if report['seconds'] > 0:
                rate = metrics['loc'] * 60 / report['seconds']
                st.metric("Build output · lines/min", f"{rate:.1f}", width=200)
        for label, value in extra_metrics:
            st.metric(label, value, width=200)
    if metrics := report.get("code_metrics"):
        st.caption(metrics["method"])
        st.caption("Lines/min = generated Python lines ÷ elapsed build minutes, including repairs and checks. It measures output volume, not code quality.")
    if cluster:
        st.caption(
            f"Built on {cluster['node']} · {cluster['hardware']}. "
            "OpenCode used local Qwen to generate the app code. Codex supervised the build "
            "and validation: local code generation with online supervision."
        )
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
