"""Display-only helpers for the AGILab About page."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st


def quick_logo(resources_path: Path) -> None:
    """Render a lightweight banner with the AGILab logo."""
    try:
        from agi_gui.pagelib import get_base64_of_image

        img_data = get_base64_of_image(resources_path / "agilab_logo.png")
        img_src = f"data:image/png;base64,{img_data}"
        st.markdown(
            f"""
            <style>
              .agilab-hero {{
                --agilab-ink: #f7f2e8;
                --agilab-muted: rgba(247, 242, 232, 0.72);
                --agilab-line: rgba(255, 255, 255, 0.16);
                position: relative;
                overflow: hidden;
                max-width: 1180px;
                margin: 1.15rem auto 1.35rem;
                padding: clamp(1.4rem, 3vw, 2.7rem);
                border: 1px solid var(--agilab-line);
                border-radius: 30px;
                color: var(--agilab-ink);
                background:
                  radial-gradient(circle at 10% 5%, rgba(255, 190, 94, 0.34), transparent 32%),
                  radial-gradient(circle at 85% 20%, rgba(52, 211, 153, 0.24), transparent 34%),
                  linear-gradient(135deg, #08111f 0%, #102331 45%, #1f2a19 100%);
                box-shadow: 0 28px 72px rgba(7, 17, 31, 0.34);
                font-family: "Aptos Display", "Avenir Next", "Gill Sans", "Trebuchet MS", sans-serif;
              }}
              .agilab-hero::before {{
                content: "";
                position: absolute;
                inset: -40% -12% auto auto;
                width: 460px;
                height: 460px;
                border-radius: 999px;
                background: conic-gradient(from 130deg, rgba(255,255,255,0.24), rgba(255,255,255,0), rgba(255, 190, 94, 0.22));
                filter: blur(4px);
                opacity: 0.72;
              }}
              .agilab-hero__grid {{
                position: relative;
                display: grid;
                grid-template-columns: minmax(0, 1.25fr) minmax(280px, 0.75fr);
                gap: clamp(1.25rem, 4vw, 3rem);
                align-items: stretch;
              }}
              .agilab-hero__brand {{
                display: inline-flex;
                align-items: center;
                gap: 0.7rem;
                padding: 0.48rem 0.75rem;
                border: 1px solid var(--agilab-line);
                border-radius: 999px;
                background: rgba(255, 255, 255, 0.08);
                backdrop-filter: blur(10px);
                letter-spacing: 0.08em;
                text-transform: uppercase;
                font-size: 0.74rem;
                font-weight: 800;
              }}
              .agilab-hero__brand img {{
                width: 112px;
                height: auto;
                display: block;
              }}
              .agilab-hero__eyebrow {{
                margin: 1.4rem 0 0.55rem;
                color: #ffd28a;
                font-size: 0.8rem;
                font-weight: 800;
                letter-spacing: 0.16em;
                text-transform: uppercase;
              }}
              .agilab-hero h1 {{
                margin: 0;
                max-width: 760px;
                font-size: clamp(2.45rem, 5.5vw, 5.8rem);
                line-height: 0.92;
                letter-spacing: -0.075em;
              }}
              .agilab-hero__lead {{
                max-width: 720px;
                margin: 1.15rem 0 0;
                color: var(--agilab-muted);
                font-size: clamp(1.02rem, 1.8vw, 1.26rem);
                line-height: 1.55;
              }}
              .agilab-hero__panel {{
                align-self: end;
                border: 1px solid var(--agilab-line);
                border-radius: 24px;
                background: rgba(255, 255, 255, 0.09);
                box-shadow: inset 0 1px 0 rgba(255,255,255,0.18);
                backdrop-filter: blur(12px);
                padding: 1rem;
              }}
              .agilab-hero__panel-title {{
                margin: 0 0 0.75rem;
                color: #ffd28a;
                font-size: 0.76rem;
                font-weight: 900;
                letter-spacing: 0.13em;
                text-transform: uppercase;
              }}
              .agilab-hero__step {{
                display: grid;
                grid-template-columns: 2.1rem minmax(0, 1fr);
                gap: 0.72rem;
                align-items: start;
                padding: 0.84rem 0.25rem;
                border-top: 1px solid rgba(255,255,255,0.12);
              }}
              .agilab-hero__step:first-of-type {{
                border-top: 0;
              }}
              .agilab-hero__num {{
                display: grid;
                place-items: center;
                width: 2.1rem;
                height: 2.1rem;
                border-radius: 14px;
                background: #f7f2e8;
                color: #0e1a25;
                font-weight: 950;
              }}
              .agilab-hero__step strong {{
                display: block;
                margin: 0 0 0.12rem;
                color: #ffffff;
              }}
              .agilab-hero__step span {{
                color: var(--agilab-muted);
                font-size: 0.94rem;
                line-height: 1.38;
              }}
              .agilab-hero__chips {{
                display: flex;
                flex-wrap: wrap;
                gap: 0.55rem;
                margin-top: 1.25rem;
              }}
              .agilab-hero__chip {{
                border: 1px solid rgba(255,255,255,0.18);
                border-radius: 999px;
                padding: 0.48rem 0.74rem;
                background: rgba(6, 12, 20, 0.28);
                color: rgba(247, 242, 232, 0.84);
                font-size: 0.86rem;
                font-weight: 750;
              }}
              .agilab-hero__flow {{
                display: grid;
                grid-template-columns: repeat(4, minmax(0, 1fr));
                gap: 0.5rem;
                margin-top: 1.1rem;
                max-width: 760px;
              }}
              .agilab-hero__flow span {{
                position: relative;
                min-height: 3.35rem;
                padding: 0.65rem 0.72rem;
                border: 1px solid rgba(255,255,255,0.14);
                border-radius: 16px;
                background: rgba(255, 255, 255, 0.08);
                color: rgba(247, 242, 232, 0.88);
                font-size: 0.82rem;
                font-weight: 850;
                line-height: 1.25;
              }}
              .agilab-hero__flow span::after {{
                content: "";
                position: absolute;
                right: -0.38rem;
                top: 50%;
                width: 0.38rem;
                height: 1px;
                background: rgba(255,255,255,0.26);
              }}
              .agilab-hero__flow span:last-child::after {{
                display: none;
              }}
              @media (max-width: 820px) {{
                .agilab-hero__grid {{
                  grid-template-columns: 1fr;
                }}
                .agilab-hero__brand {{
                  align-items: flex-start;
                  border-radius: 18px;
                  flex-direction: column;
                }}
                .agilab-hero__flow {{
                  grid-template-columns: repeat(2, minmax(0, 1fr));
                }}
              }}
              @media (max-width: 520px) {{
                .agilab-hero__flow {{
                  grid-template-columns: 1fr;
                }}
                .agilab-hero__flow span::after {{
                  display: none;
                }}
              }}
            </style>
            <section class="agilab-hero" aria-label="AGILAB introduction">
              <div class="agilab-hero__grid">
                <div>
                  <div class="agilab-hero__brand">
                    <img src="{img_src}" alt="AGILAB logo">
                    <span>Thales open-source workbench</span>
                  </div>
                  <p class="agilab-hero__eyebrow">AI/ML experimentation workbench</p>
                  <h1>Reproducible AI engineering, from project to proof.</h1>
                  <p class="agilab-hero__lead">
                    AGILAB keeps project setup, environment management, execution,
                    and analysis on one operator path, so a demo can become a repeatable
                    engineering proof instead of a pile of scripts.
                  </p>
                  <div class="agilab-hero__chips" aria-label="AGILAB capabilities">
                    <span class="agilab-hero__chip">Project factory</span>
                    <span class="agilab-hero__chip">Local or worker execution</span>
                    <span class="agilab-hero__chip">Evidence-first analysis</span>
                  </div>
                  <div class="agilab-hero__flow" aria-label="AGILAB execution loop">
                    <span>Data intake</span>
                    <span>Pipeline assembly</span>
                    <span>Distributed run</span>
                    <span>Decision evidence</span>
                  </div>
                </div>
                <aside class="agilab-hero__panel" aria-label="AGILAB control path">
                  <p class="agilab-hero__panel-title">Control path</p>
                  <div class="agilab-hero__step">
                    <span class="agilab-hero__num">1</span>
                    <div><strong>Choose a project</strong><span>Start from a built-in app or your own workflow.</span></div>
                  </div>
                  <div class="agilab-hero__step">
                    <span class="agilab-hero__num">2</span>
                    <div><strong>Execute with evidence</strong><span>Install, run, and record what changed.</span></div>
                  </div>
                  <div class="agilab-hero__step">
                    <span class="agilab-hero__num">3</span>
                    <div><strong>Inspect the result</strong><span>Open ANALYSIS and validate generated artifacts.</span></div>
                  </div>
                </aside>
              </div>
            </section>
            """,
            unsafe_allow_html=True,
        )
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        st.info(str(exc))
        st.info("Welcome to AGILAB")


def landing_page_sections() -> dict[str, Any]:
    """Return compact secondary guidance shown under the first-step path."""
    return {
        "after_first_demo": [
            "try another built-in demo",
            "keep cluster mode for later",
        ],
        "explore_cards": [
            {
                "title": "Project",
                "body": "Select or clone a workflow without leaving the UI.",
            },
            {
                "title": "Orchestrate",
                "body": "Install and execute with visible runtime choices.",
            },
            {
                "title": "Analysis",
                "body": "Open the generated result and keep proof artifacts traceable.",
            },
        ],
    }


def display_landing_page(resources_path: Path) -> None:
    """Display compact secondary context under the first-step instructions."""
    del resources_path
    cards_html = "".join(
        (
            f"""<article class="agilab-next__card">
                 <span>{card["title"]}</span>
                 <p>{card["body"]}</p>
               </article>"""
        )
        for card in landing_page_sections()["explore_cards"]
    )
    st.markdown(
        f"""
        <style>
          .agilab-next {{
            margin: 1rem 0 0.2rem;
            padding: 1rem;
            border: 1px solid rgba(10, 31, 51, 0.10);
            border-radius: 22px;
            background:
              linear-gradient(135deg, rgba(255,255,255,0.92), rgba(242, 247, 244, 0.86)),
              radial-gradient(circle at 100% 0%, rgba(255, 190, 94, 0.24), transparent 34%);
            box-shadow: 0 16px 44px rgba(12, 27, 42, 0.09);
            font-family: "Aptos", "Avenir Next", "Gill Sans", "Trebuchet MS", sans-serif;
          }}
          .agilab-next__kicker {{
            margin: 0 0 0.8rem;
            color: #39513f;
            font-size: 0.74rem;
            font-weight: 900;
            letter-spacing: 0.13em;
            text-transform: uppercase;
          }}
          .agilab-next__grid {{
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.75rem;
          }}
          .agilab-next__card {{
            min-height: 116px;
            padding: 0.9rem;
            border: 1px solid rgba(10, 31, 51, 0.10);
            border-radius: 17px;
            background: rgba(255, 255, 255, 0.72);
          }}
          .agilab-next__card span {{
            display: inline-block;
            margin-bottom: 0.55rem;
            color: #0a1f33;
            font-size: 1rem;
            font-weight: 900;
          }}
          .agilab-next__card p {{
            margin: 0;
            color: #587064;
            font-size: 0.92rem;
            line-height: 1.45;
          }}
          .agilab-next__note {{
            margin: 0.85rem 0 0;
            color: #5f6f69;
            font-size: 0.9rem;
          }}
          @media (max-width: 820px) {{
            .agilab-next__grid {{
              grid-template-columns: 1fr;
            }}
          }}
        </style>
        <section class="agilab-next" aria-label="Next AGILAB exploration paths">
          <p class="agilab-next__kicker">After the first demo</p>
          <div class="agilab-next__grid">{cards_html}</div>
          <p class="agilab-next__note">
            Recommended sequence: try another built-in demo, then enable cluster or
            service mode once the local path is proven.
          </p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def clean_openai_key(key: str | None) -> str | None:
    """Return None for missing/placeholder keys to avoid confusing 401s."""
    if not key:
        return None
    trimmed = key.strip()
    placeholders = {"your-key", "sk-your-key", "sk-XXXX"}
    if trimmed in placeholders or len(trimmed) < 12:
        return None
    return trimmed


def openai_status_banner(env: Any, *, env_file_path: Path) -> None:
    """Show a non-blocking banner when OpenAI features are unavailable."""
    env_key = getattr(env, "OPENAI_API_KEY", None)
    key = clean_openai_key(os.environ.get("OPENAI_API_KEY") or env_key)
    if not key:
        st.warning(
            "OpenAI features are disabled. Set OPENAI_API_KEY below in "
            "'Environment Variables', then reload the app. The value will be "
            f"saved in {env_file_path}.",
            icon="⚠️",
        )


def render_package_versions() -> None:
    """Render installed AGILAB package versions."""
    try:
        from importlib import metadata as importlib_metadata
    except ImportError:
        import importlib_metadata  # type: ignore

    packages = [
        ("agilab", "agilab"),
        ("agi-core", "agi-core"),
        ("agi-gui", "agi-gui"),
        ("agi-node", "agi-node"),
        ("agi-env", "agi-env"),
    ]

    for label, pkg_name in packages:
        try:
            version = importlib_metadata.version(pkg_name)
        except importlib_metadata.PackageNotFoundError:
            version = "not installed"
        st.write(f"{label}: {version}")


def render_system_information() -> None:
    """Render local OS and CPU information."""
    os_label, cpu_name = system_information_summary()

    st.write(f"OS: {os_label}")
    st.write(f"CPU: {cpu_name}")


def system_information_summary() -> tuple[str, str]:
    """Return compact local OS and CPU labels for display surfaces."""
    import platform

    os_label = " ".join(part for part in (platform.system(), platform.release()) if part).strip()
    cpu_name = platform.processor() or platform.machine()
    return os_label or "Unknown OS", cpu_name or "Unknown CPU"


def render_sidebar_system_information() -> None:
    """Render compact local OS and CPU information in the sidebar."""
    os_label, cpu_name = system_information_summary()
    st.sidebar.caption(f"OS: {os_label}")
    st.sidebar.caption(f"CPU: {cpu_name}")


def render_footer() -> None:
    """Render the About page legal footer."""
    current_year = datetime.now().year
    st.markdown(
        f"""
    <div class='footer' style="display: flex; justify-content: flex-end;">
        <span>&copy; 2020-{current_year} Thales SIX GTS. Licensed under the BSD 3-Clause License.</span>
    </div>
    """,
        unsafe_allow_html=True,
    )
