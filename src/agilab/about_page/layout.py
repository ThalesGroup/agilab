"""Display-only helpers for the AGILab About page."""

from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import platform
import re
import subprocess
import tomllib
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import streamlit as st


def _hero_target_svg_data_uri() -> str:
    """Return the banner target diagram as an image-safe SVG data URI."""
    svg = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 300" role="img" aria-label="Digital twin assisted generalization map linking simulation, bias variance controls, underfit overfit symptoms, and train test diagnosis">
  <defs>
    <filter id="glow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="2.4" result="blur" />
      <feMerge>
        <feMergeNode in="blur" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>
    <linearGradient id="cardFill" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0" stop-color="#102334" stop-opacity=".98" />
      <stop offset="1" stop-color="#1f2c24" stop-opacity=".94" />
    </linearGradient>
    <linearGradient id="twinFill" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0" stop-color="#123f3d" stop-opacity=".98" />
      <stop offset="1" stop-color="#322a17" stop-opacity=".96" />
    </linearGradient>
  </defs>
  <style>
    .title{fill:#f7f2e8;fill-opacity:.9;font:850 14px 'Aptos Display','Avenir Next',sans-serif;letter-spacing:.1em;text-transform:uppercase}
    .eyebrow{fill:#ffd28a;font:850 8.8px 'Aptos Display','Avenir Next',sans-serif;letter-spacing:.13em;text-transform:uppercase}
    .main{fill:#f7f2e8;font:850 12.5px 'Aptos Display','Avenir Next',sans-serif;letter-spacing:.04em}
    .tiny{fill:#f7f2e8;fill-opacity:.72;font:700 8.6px 'Aptos Display','Avenir Next',sans-serif;letter-spacing:.05em;text-transform:uppercase}
    .note{fill:#ffd28a;font:850 10.5px 'Aptos Display','Avenir Next',sans-serif;letter-spacing:.08em}
    .card{fill:url(#cardFill);stroke:#f7f2e8;stroke-opacity:.22;stroke-width:1}
    .target{fill:#f7f2e8;fill-opacity:.07;stroke:#f7f2e8;stroke-opacity:.32;stroke-width:1.4}
    .twin-shell{fill:url(#twinFill);stroke:#72d6b4;stroke-opacity:.78;stroke-width:1.35}
    .twin-grid{fill:none;stroke:#72d6b4;stroke-opacity:.26;stroke-width:.75}
    .twin-divider{stroke:#f7f2e8;stroke-opacity:.2;stroke-width:1}
    .ring{fill:none;stroke:#f7f2e8;stroke-opacity:.24;stroke-width:1.1}
    .core{fill:none;stroke:#ffd28a;stroke-opacity:.58;stroke-width:1.2}
    .axis{stroke:#f7f2e8;stroke-opacity:.18}
    .connector{fill:none;stroke:#f7f2e8;stroke-opacity:.3;stroke-width:1.1;stroke-linecap:round}
    .flow{fill:none;stroke:#72d6b4;stroke-width:2.4;stroke-linecap:round;stroke-linejoin:round}
    .flow-warm{fill:none;stroke:#ffbe5e;stroke-width:2.4;stroke-linecap:round;stroke-linejoin:round}
    .sim-orbit{fill:none;stroke:#ffd28a;stroke-opacity:.82;stroke-width:1.8;stroke-linecap:round;stroke-dasharray:5 4}
    .sim-line{fill:none;stroke:#72d6b4;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
    .sim-warm{fill:none;stroke:#ffd28a;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
    .sim-dot{fill:#ffd28a}
    .sim-label{fill:#f7f2e8;fill-opacity:.78;font:850 6.3px 'Aptos Display','Avenir Next',sans-serif;letter-spacing:.12em;text-transform:uppercase}
  </style>
  <text class="title" x="280" y="24" text-anchor="middle">Generalization + digital twin map</text>
  <text class="note" x="280" y="273" text-anchor="middle">simulate, run, diagnose, then tune the real workflow</text>

  <g transform="translate(116 146)">
    <circle class="target" r="76" />
    <circle class="ring" r="56" />
    <circle class="ring" r="37" />
    <circle class="core" r="18" />
    <line class="axis" x1="-84" y1="0" x2="84" y2="0" />
    <line class="axis" x1="0" y1="-84" x2="0" y2="84" />
    <circle cx="0" cy="0" r="4.6" fill="#ffd28a" filter="url(#glow)" />
  </g>

  <ellipse cx="117" cy="145" rx="19" ry="14" fill="rgba(114,214,180,.08)" stroke="#72d6b4" stroke-width="2" stroke-dasharray="4 3" />
  <g fill="#72d6b4" filter="url(#glow)">
    <circle cx="111" cy="142" r="3.8" />
    <circle cx="119" cy="146" r="3.8" />
    <circle cx="124" cy="139" r="3.8" />
    <circle cx="114" cy="152" r="3.8" />
  </g>

  <path d="M116 146 L175 97" fill="none" stroke="#ffbe5e" stroke-width="3" stroke-linecap="round" />
  <path d="M163 97 L177 96 L171 109" fill="none" stroke="#ffbe5e" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
  <ellipse cx="177" cy="97" rx="20" ry="14" fill="rgba(255,190,94,.08)" stroke="#ffbe5e" stroke-width="2" stroke-dasharray="4 3" />
  <g fill="#ffbe5e">
    <circle cx="169" cy="93" r="3.8" />
    <circle cx="177" cy="99" r="3.8" />
    <circle cx="184" cy="94" r="3.8" />
    <circle cx="181" cy="105" r="3.8" />
  </g>

  <ellipse cx="114" cy="148" rx="58" ry="48" fill="rgba(255,112,94,.035)" stroke="#ff705e" stroke-width="1.8" stroke-dasharray="6 5" />
  <g fill="none" stroke="#ff705e" stroke-width="2.3">
    <circle cx="72" cy="113" r="3.8" />
    <circle cx="158" cy="126" r="3.8" />
    <circle cx="84" cy="181" r="3.8" />
    <circle cx="143" cy="195" r="3.8" />
    <circle cx="100" cy="135" r="3.8" />
  </g>

  <rect class="card" x="218" y="75" width="128" height="132" rx="18" />
  <g aria-label="digital twin simulation symbol">
    <rect class="twin-shell" x="228" y="86" width="108" height="76" rx="14" />
    <path class="twin-grid" d="M238 105 H326 M238 124 H326 M238 143 H326 M256 94 V154 M282 94 V154 M308 94 V154" />
    <line class="twin-divider" x1="282" y1="96" x2="282" y2="152" />
    <path class="sim-orbit" d="M246 123 C251 101, 270 94, 292 97 C316 100, 329 116, 325 137 C321 154, 302 160, 281 158 C257 155, 241 143, 246 123" />
    <path class="sim-warm" d="M318 131 L326 138 L316 142" />

    <text class="sim-label" x="253" y="101" text-anchor="middle">Real</text>
    <text class="sim-label" x="313" y="101" text-anchor="middle">Sim</text>
    <path class="sim-line" d="M246 135 C253 126, 260 124, 267 131 C273 137, 279 137, 286 129" />
    <circle class="sim-dot" cx="253" cy="126" r="2.8" />
    <circle class="sim-dot" cx="279" cy="137" r="2.8" />

    <path class="sim-line" d="M298 113 L313 105 L327 113 L327 134 L313 143 L298 135 Z" />
    <path class="sim-line" d="M298 113 L313 122 L327 113 M313 122 V143" />
    <circle cx="313" cy="122" r="3.6" fill="#0d1722" stroke="#ffd28a" stroke-width="1.4" />
    <path class="sim-warm" d="M286 118 H300 M294 114 L300 118 L294 122" />
    <path class="sim-warm" d="M300 139 H286 M292 135 L286 139 L292 143" />
  </g>
  <text class="eyebrow" x="282" y="181" text-anchor="middle">Digital twin</text>
  <text class="tiny" x="282" y="195" text-anchor="middle">simulate &#8596; reality</text>

  <path class="flow" d="M178 147 C193 143, 205 139, 218 134" />
  <path class="flow" d="M346 134 C357 126, 360 121, 372 111" />
  <path class="flow-warm" d="M346 151 C358 154, 362 158, 372 164" />
  <path class="flow" d="M346 171 C357 183, 361 190, 372 202" />

  <rect class="card" x="371" y="82" width="164" height="44" rx="12" />
  <rect x="371" y="82" width="5" height="44" rx="2.5" fill="#ffd28a" />
  <text class="eyebrow" x="386" y="99">Controls</text>
  <text class="main" x="386" y="116">Bias &#8596; Variance</text>

  <rect class="card" x="371" y="144" width="164" height="44" rx="12" />
  <rect x="371" y="144" width="5" height="44" rx="2.5" fill="#ffbe5e" />
  <text class="eyebrow" x="386" y="161">Symptoms</text>
  <text class="main" x="386" y="178">Underfit &#8596; Overfit</text>

  <rect class="card" x="371" y="206" width="164" height="52" rx="12" />
  <rect x="371" y="206" width="5" height="52" rx="2.5" fill="#72d6b4" />
  <text class="eyebrow" x="386" y="223">Diagnosis</text>
  <text class="main" x="386" y="239">Train vs Test</text>
  <path d="M467 239 C478 229, 493 225, 524 222" fill="none" stroke="#72d6b4" stroke-width="2" stroke-linecap="round" />
  <path d="M467 232 C480 220, 492 216, 505 220 C517 224, 524 232, 531 241" fill="none" stroke="#ffbe5e" stroke-width="2" stroke-linecap="round" />
</svg>
""".strip()
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def quick_logo(resources_path: Path) -> None:
    """Render a lightweight banner with the AGILab logo."""
    try:
        from agi_gui.pagelib import get_base64_of_image

        img_data = get_base64_of_image(resources_path / "agilab_logo.png")
        img_src = f"data:image/png;base64,{img_data}"
        target_svg_src = _hero_target_svg_data_uri()
        current_year = datetime.now().year
        st.markdown(
            f"""
            <style>
              .agilab-hero {{
                --agilab-ink: #f7f2e8;
                --agilab-muted: rgba(247, 242, 232, 0.74);
                --agilab-line: rgba(255, 255, 255, 0.16);
                width: 100%;
                box-sizing: border-box;
                margin: 1rem 0 1.15rem;
                padding: clamp(1.15rem, 2.6vw, 2rem);
                border: 1px solid var(--agilab-line);
                border-radius: 24px;
                color: var(--agilab-ink);
                background:
                  radial-gradient(circle at 0% 0%, rgba(255, 190, 94, 0.28), transparent 34%),
                  linear-gradient(135deg, #08111f 0%, #132b33 58%, #263019 100%);
                box-shadow: 0 20px 52px rgba(7, 17, 31, 0.24);
                font-family: "Aptos Display", "Avenir Next", "Gill Sans", "Trebuchet MS", sans-serif;
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
              .agilab-hero__top {{
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 1rem;
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
              .agilab-hero__body {{
                display: grid;
                grid-template-columns: minmax(230px, 0.82fr) minmax(410px, 1.18fr);
                gap: clamp(1.1rem, 3vw, 2.2rem);
                align-items: center;
              }}
              .agilab-hero h1 {{
                margin: 0;
                max-width: 760px;
                font-size: clamp(2.05rem, 4.3vw, 4.2rem);
                line-height: 0.98;
                letter-spacing: -0.055em;
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
              .agilab-hero__visual {{
                position: relative;
                min-height: 260px;
                padding: 0.85rem;
                border: 1px solid rgba(255,255,255,0.18);
                border-radius: 22px;
                background:
                  radial-gradient(circle at 15% 10%, rgba(255, 210, 138, 0.18), transparent 34%),
                  rgba(255, 255, 255, 0.075);
                box-shadow: inset 0 1px 0 rgba(255,255,255,0.12);
              }}
              .agilab-hero__target-img {{
                width: 100%;
                height: auto;
                display: block;
              }}
              .agilab-hero__legal {{
                display: inline-flex;
                align-items: center;
                gap: 0.52rem;
                margin: 0;
                padding: 0.5rem 0.68rem;
                border: 1px solid rgba(255,255,255,0.13);
                border-radius: 999px;
                background: rgba(6, 12, 20, 0.22);
                color: rgba(247, 242, 232, 0.64);
                font-size: 0.73rem;
                line-height: 1.15;
                text-align: right;
                white-space: nowrap;
              }}
              .agilab-hero__legal-mark {{
                color: #ffd28a;
                font-weight: 850;
                letter-spacing: 0.08em;
                text-transform: uppercase;
              }}
              .agilab-hero__legal-sep {{
                color: rgba(247, 242, 232, 0.24);
              }}
              @media (max-width: 900px) {{
                .agilab-hero__body {{
                  grid-template-columns: 1fr;
                }}
                .agilab-hero__visual {{
                  min-height: unset;
                }}
              }}
              @media (max-width: 520px) {{
                .agilab-hero__brand {{
                  align-items: flex-start;
                  border-radius: 18px;
                  flex-direction: column;
                }}
                .agilab-hero__top {{
                  align-items: flex-start;
                  flex-direction: column;
                }}
                .agilab-hero__legal {{
                  align-items: flex-start;
                  border-radius: 16px;
                  flex-direction: column;
                  gap: 0.18rem;
                  text-align: left;
                  white-space: normal;
                }}
                .agilab-hero__legal-sep {{
                  display: none;
                }}
              }}
            </style>
            <section class="agilab-hero" aria-label="AGILAB introduction">
              <div class="agilab-hero__top">
                <div class="agilab-hero__brand">
                  <img src="{img_src}" alt="AGILAB logo">
                  <span>Open-source workbench</span>
                </div>
                <p class="agilab-hero__legal">
                  <span class="agilab-hero__legal-mark">BSD 3-Clause</span>
                  <span class="agilab-hero__legal-sep" aria-hidden="true">/</span>
                  <span>&copy; 2020-{current_year} Thales SIX GTS France</span>
                </p>
              </div>
              <div class="agilab-hero__body">
                <div class="agilab-hero__copy">
                  <p class="agilab-hero__eyebrow">AI/ML experimentation</p>
                  <h1>Reproducible AI workflows.</h1>
                  <div class="agilab-hero__chips" aria-label="AGILAB workflow">
                    <span class="agilab-hero__chip">Project</span>
                    <span class="agilab-hero__chip">Run</span>
                    <span class="agilab-hero__chip">Analyse</span>
                  </div>
                </div>
                <div class="agilab-hero__visual" role="img" aria-label="Digital twin assisted generalization map">
                  <img
                    class="agilab-hero__target-img"
                    src="{target_svg_src}"
                    alt="Digital twin assisted generalization map linking simulation, bias variance controls, underfit overfit symptoms, and train test diagnosis"
                  >
                </div>
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
    """Keep OpenAI setup optional and silent on the first-launch path."""
    _ = (env, env_file_path)


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
    """Render local OS, CPU, and accelerator information."""
    for label, value in system_information_lines():
        st.write(f"{label}: {value}")


def system_information_lines() -> list[tuple[str, str]]:
    """Return labelled system information lines for display surfaces."""
    os_label, cpu_name = system_information_summary()
    gpu_summary, npu_summary = accelerator_information_summary()
    return [
        ("OS", os_label),
        ("CPU", cpu_name),
        ("GPU", gpu_summary),
        ("NPU", npu_summary),
    ]


def system_information_summary() -> tuple[str, str]:
    """Return compact local OS and CPU labels for display surfaces."""
    os_label = " ".join(part for part in (platform.system(), platform.release()) if part).strip()
    cpu_name = _cpu_summary(platform.system())
    return os_label or "Unknown OS", cpu_name or "Unknown CPU"


def accelerator_information_summary() -> tuple[str, str]:
    """Return compact GPU and NPU labels for display surfaces."""
    system = platform.system()
    hardware = _mac_hardware_profile() if system == "Darwin" else {}
    gpu_summary = _gpu_summary(system)
    npu_summary = _npu_summary(system, hardware.get("Chip", ""))
    return gpu_summary, npu_summary


def _memory_summary() -> str:
    """Return compact local RAM label."""
    try:
        import psutil  # type: ignore
    except ImportError:
        psutil = None  # type: ignore[assignment]
    if psutil is not None:
        try:
            return _format_bytes(int(psutil.virtual_memory().total))
        except Exception:
            pass

    if platform.system() == "Darwin":
        value = _command_output(("sysctl", "-n", "hw.memsize"))
        if value.isdigit():
            return _format_bytes(int(value))

    meminfo = _command_output(("sh", "-c", "awk '/MemTotal/ {print int($2 * 1024)}' /proc/meminfo 2>/dev/null"))
    if meminfo.isdigit():
        return _format_bytes(int(meminfo))
    return "Unknown RAM"


def _format_bytes(byte_count: int) -> str:
    gib = byte_count / (1024**3)
    if gib >= 10:
        return f"{gib:.0f} GB"
    return f"{gib:.1f} GB"


def _local_hardware_summary() -> dict[str, str]:
    _, cpu_name = system_information_summary()
    gpu_summary, npu_summary = accelerator_information_summary()
    return {
        "CPU": cpu_name or "Unknown CPU",
        "RAM": _memory_summary(),
        "GPU": gpu_summary or "Not detected",
        "NPU": npu_summary or "Not detected",
    }


def _safe_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(value).strip()


def _active_app_settings_from_session() -> dict[str, Any]:
    settings = st.session_state.get("app_settings")
    return dict(settings) if isinstance(settings, dict) else {}


def _active_app_settings_from_file(env: Any) -> dict[str, Any]:
    settings_file = getattr(env, "app_settings_file", None)
    if not settings_file:
        return {}
    try:
        path = Path(settings_file).expanduser()
    except (TypeError, ValueError):
        return {}
    try:
        if not path.is_file():
            return {}
        with path.open("rb") as handle:
            payload = tomllib.load(handle)
    except (OSError, RuntimeError, tomllib.TOMLDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _active_app_settings(env: Any) -> dict[str, Any]:
    file_settings = _active_app_settings_from_file(env)
    if file_settings:
        return file_settings
    return _active_app_settings_from_session()


def _cluster_params_from_settings(settings: dict[str, Any]) -> dict[str, Any]:
    cluster = settings.get("cluster")
    return dict(cluster) if isinstance(cluster, dict) else {}


def _format_bool_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _cluster_mode_label(cluster_params: dict[str, Any]) -> str:
    enabled = _format_bool_flag(cluster_params.get("cluster_enabled", False))
    modes = []
    if enabled:
        modes.append("dask")
    for key in ("pool", "cython", "rapids"):
        if _format_bool_flag(cluster_params.get(key, False)):
            modes.append(key)
    if enabled:
        suffix = f" ({', '.join(modes)})" if modes else ""
        return f"enabled{suffix}"
    if modes:
        return f"local ({', '.join(modes)} available)"
    return "local"


def _env_cluster_share(env: Any) -> str:
    for name in ("AGI_CLUSTER_SHARE", "agi_share_path", "agi_share_path_abs"):
        value = _safe_text(getattr(env, name, ""))
        if value:
            return value
    envars = getattr(env, "envars", None)
    if isinstance(envars, dict):
        value = _safe_text(envars.get("AGI_CLUSTER_SHARE"))
        if value:
            return value
    return ""


def _scheduler_host(scheduler: str) -> str:
    cleaned = scheduler.strip()
    if not cleaned:
        return ""
    if "://" in cleaned:
        parsed = urlparse(cleaned)
        return parsed.hostname or cleaned
    if cleaned.startswith("[") and "]" in cleaned:
        return cleaned[1 : cleaned.index("]")]
    if cleaned.count(":") == 1:
        return cleaned.split(":", 1)[0]
    return cleaned


def _is_local_node(host: str) -> bool:
    return host.strip().lower() in {"", "local", "localhost", "127.0.0.1", "::1"}


def _scheduler_display(scheduler: str, *, cluster_enabled: bool) -> str:
    cleaned = scheduler.strip()
    if not cleaned:
        return "not configured" if cluster_enabled else "local process"
    host = cleaned
    port: int | None = None
    if "://" in cleaned:
        parsed = urlparse(cleaned)
        host = parsed.hostname or cleaned
        port = parsed.port
    else:
        target = cleaned.rsplit("@", 1)[-1]
        if target.startswith("[") and "]" in target:
            host = target[1 : target.index("]")]
            rest = target[target.index("]") + 1 :]
            if rest.startswith(":") and rest[1:].isdigit():
                port = int(rest[1:])
        elif target.count(":") == 1:
            host, raw_port = target.split(":", 1)
            if raw_port.isdigit():
                port = int(raw_port)
        else:
            host = target
    host = host.strip()
    if not host:
        return "not configured" if cluster_enabled else "local process"
    if cluster_enabled and not _is_local_node(host) and port is None:
        port = 8786
    if port is None:
        return host
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}:{port}"


def _remote_hardware_probe_command() -> str:
    return r"""
printf 'OS=%s %s\n' "$(uname -s 2>/dev/null)" "$(uname -r 2>/dev/null)"
cpu=''
if command -v lscpu >/dev/null 2>&1; then
  cpu="$(lscpu 2>/dev/null | awk -F: '/Model name/ {sub(/^[ \t]+/, "", $2); print $2; exit}')"
fi
if [ -z "$cpu" ] && [ -r /proc/cpuinfo ]; then
  cpu="$(awk -F: '/model name/ {sub(/^[ \t]+/, "", $2); print $2; exit}' /proc/cpuinfo)"
fi
if [ -z "$cpu" ] && command -v sysctl >/dev/null 2>&1; then
  cpu="$(sysctl -n machdep.cpu.brand_string 2>/dev/null)"
fi
if [ -z "$cpu" ]; then cpu="$(uname -m 2>/dev/null)"; fi
cores="$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null)"
if [ -n "$cores" ]; then cpu="$cpu; cores: $cores"; fi
printf 'CPU=%s\n' "$cpu"
ram=''
if [ -r /proc/meminfo ]; then
  ram="$(awk '/MemTotal/ {printf "%.0f GB", ($2 * 1024) / (1024 * 1024 * 1024)}' /proc/meminfo)"
fi
if [ -z "$ram" ] && command -v sysctl >/dev/null 2>&1; then
  ram_bytes="$(sysctl -n hw.memsize 2>/dev/null)"
  if [ -n "$ram_bytes" ]; then ram="$(awk -v b="$ram_bytes" 'BEGIN {printf "%.0f GB", b / (1024 * 1024 * 1024)}')"; fi
fi
printf 'RAM=%s\n' "$ram"
gpu=''
if command -v nvidia-smi >/dev/null 2>&1; then
  gpu="$(nvidia-smi --query-gpu=name,multiprocessor_count --format=csv,noheader,nounits 2>/dev/null | awk -F, '{gsub(/^[ \t]+|[ \t]+$/, "", $1); gsub(/^[ \t]+|[ \t]+$/, "", $2); if ($2 != "") print $1 " (" $2 " SMs)"; else print $1}' | paste -sd ';' -)"
fi
if [ -z "$gpu" ] && command -v system_profiler >/dev/null 2>&1; then
  gpu="$(system_profiler SPDisplaysDataType 2>/dev/null | awk -F: '/Chipset Model/ {gsub(/^[ \t]+/, "", $2); print $2; exit}')"
fi
printf 'GPU=%s\n' "$gpu"
npu=''
chip=''
if command -v system_profiler >/dev/null 2>&1; then
  chip="$(system_profiler SPHardwareDataType 2>/dev/null | awk -F: '/Chip/ {gsub(/^[ \t]+/, "", $2); print $2; exit}')"
fi
case "$chip" in
  Apple\ M*) npu='Apple Neural Engine (16 cores)' ;;
esac
printf 'NPU=%s\n' "$npu"
""".strip()


def _ssh_target(host: str, user: str) -> str:
    if "@" in host or not user:
        return host
    return f"{user}@{host}"


@lru_cache(maxsize=32)
def _remote_hardware_probe(host: str, user: str, ssh_key_path: str) -> str:
    command: list[str] = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=1",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    if ssh_key_path:
        command.extend(["-i", ssh_key_path])
    command.extend([_ssh_target(host, user), _remote_hardware_probe_command()])
    return _command_output(tuple(command))


def _parse_hardware_probe_output(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return {
        "CPU": values.get("CPU") or "Unknown CPU",
        "RAM": values.get("RAM") or "Unknown RAM",
        "GPU": values.get("GPU") or "Not detected",
        "NPU": values.get("NPU") or "Not detected",
    }


def _hardware_summary_from_mapping(payload: Any) -> dict[str, str] | None:
    if not isinstance(payload, dict):
        return None
    source = payload.get("hardware")
    if not isinstance(source, dict):
        source = payload
    values: dict[str, str] = {}
    aliases = {
        "CPU": ("CPU", "cpu"),
        "RAM": ("RAM", "ram", "memory"),
        "GPU": ("GPU", "gpu"),
        "NPU": ("NPU", "npu"),
    }
    for target_key, source_keys in aliases.items():
        for source_key in source_keys:
            raw_value = source.get(source_key)
            if raw_value not in (None, ""):
                values[target_key] = str(raw_value).strip()
                break
    if not values:
        return None
    return {
        "CPU": values.get("CPU") or "Unknown CPU",
        "RAM": values.get("RAM") or "Unknown RAM",
        "GPU": values.get("GPU") or "Not detected",
        "NPU": values.get("NPU") or "Not detected",
    }


def _node_hardware_summary(host: str, *, user: str = "", ssh_key_path: str = "") -> dict[str, str]:
    probe_host = _scheduler_host(host)
    if _is_local_node(probe_host):
        return _local_hardware_summary()
    output = _remote_hardware_probe(probe_host, user.strip(), ssh_key_path.strip())
    if not output:
        return {
            "CPU": "unreachable",
            "RAM": "unreachable",
            "GPU": "unreachable",
            "NPU": "unreachable",
        }
    return _parse_hardware_probe_output(output)


def _hardware_line(summary: dict[str, str]) -> str:
    return "; ".join(f"{key}: {summary[key]}" for key in ("CPU", "RAM", "GPU", "NPU"))


def _parse_cpu_cores(value: str) -> int | None:
    match = re.search(r"\bcores:\s*(\d+)\b", value, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"\b(\d+)\s*(?:cores?|vcpus?)\b", value, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def _parse_ram_gb(value: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(TB|GB|MB)\b", value, flags=re.IGNORECASE)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2).upper()
    if unit == "TB":
        return amount * 1024.0
    if unit == "MB":
        return amount / 1024.0
    return amount


def _format_ram_gb(value: float) -> str:
    rounded = round(value, 1)
    if rounded.is_integer():
        return f"{int(rounded)} GB"
    return f"{rounded:.1f} GB"


def _resource_unavailable(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in {
        "",
        "not configured",
        "not detected",
        "unknown cpu",
        "unknown ram",
        "unreachable",
    }


def _split_resource_descriptors(value: str) -> list[str]:
    if _resource_unavailable(value):
        return []
    prefix_match = re.match(r"^\d+\s+\w+:\s*(.+)$", value.strip())
    if prefix_match:
        value = prefix_match.group(1)
    return [part.strip() for part in value.split(";") if part.strip()]


def _format_counted_resources(counts: dict[str, int], *, empty: str = "Not detected") -> str:
    if not counts:
        return empty
    parts = []
    for label, count in sorted(counts.items()):
        parts.append(label if count == 1 else f"{count} x {label}")
    return "; ".join(parts)


def _format_unreachable_workers(count: int) -> str:
    return f"{count} worker unreachable" if count == 1 else f"{count} workers unreachable"


def _worker_issue_label(status: str) -> str:
    normalized = status.strip().lower()
    if normalized == "ssh-auth-needed":
        return "SSH auth needed"
    if normalized == "no-ssh-port":
        return "SSH port unavailable"
    if normalized == "reverse-ssh-needed":
        return "reverse SSH needed"
    if normalized == "sshfs-missing":
        return "SSHFS missing"
    if normalized == "uv-missing":
        return "uv missing"
    if normalized == "python-missing":
        return "Python missing"
    return "unreachable"


def _format_worker_issue_counts(issue_counts: dict[str, int]) -> str:
    parts = []
    for label, count in sorted(issue_counts.items()):
        if label == "unreachable":
            parts.append(_format_unreachable_workers(count))
            continue
        worker_word = "worker" if count == 1 else "workers"
        parts.append(f"{count} {worker_word} {label}")
    return " + ".join(parts)


def _append_worker_issue_suffix(value: str, issue_counts: dict[str, int]) -> str:
    if not issue_counts:
        return value
    issue_label = _format_worker_issue_counts(issue_counts)
    if value and value.lower() not in {"unknown", "not detected", "not configured"}:
        return f"{value} + {issue_label}"
    return issue_label


def _summary_unreachable(summary: dict[str, str]) -> bool:
    return all(str(summary.get(key, "")).strip().lower() == "unreachable" for key in ("CPU", "RAM", "GPU", "NPU"))


def _node_identity(host: str) -> str:
    normalized = _scheduler_host(_safe_text(host)).strip().lower()
    if "@" in normalized:
        normalized = normalized.rsplit("@", 1)[-1]
    return normalized


def _workers_items(value: Any) -> list[tuple[str, Any]]:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except (json.JSONDecodeError, TypeError):
            return [(stripped, 1)]
        return _workers_items(parsed)
    if isinstance(value, dict):
        return sorted(value.items(), key=lambda item: str(item[0]))
    if isinstance(value, (list, tuple, set)):
        return [(item, 1) for item in sorted(_safe_text(item) for item in value if _safe_text(item))]
    return []


def _hardware_inventory_from_settings(cluster_params: dict[str, Any]) -> dict[str, dict[str, str]]:
    inventory: dict[str, dict[str, str]] = {}
    for section_name in ("hardware", "worker_hardware"):
        section = cluster_params.get(section_name)
        if not isinstance(section, dict):
            continue
        for host, payload in section.items():
            identity = _node_identity(str(host))
            if not identity:
                continue
            summary = _hardware_summary_from_mapping(payload)
            if summary:
                inventory[identity] = summary
    return inventory


def _hardware_summary_has_detected_resources(summary: dict[str, str] | None) -> bool:
    if not summary:
        return False
    return any(
        not _resource_unavailable(str(summary.get(key, "")))
        for key in ("CPU", "RAM", "GPU", "NPU")
    )


def _default_lan_discovery_cache_path() -> Path:
    return Path.home() / ".agilab" / "lan_nodes.json"


def _file_content_signature(path: Path | None) -> tuple[str, str]:
    if path is None:
        return ("", "")
    try:
        resolved = path.expanduser()
    except (OSError, RuntimeError, TypeError, ValueError):
        return (str(path), "")
    try:
        payload = resolved.read_bytes()
    except OSError:
        return (str(resolved), "")
    return (str(resolved), hashlib.sha256(payload).hexdigest())


def _payload_signature(payload: Any) -> str:
    try:
        encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    except (TypeError, ValueError):
        encoded = repr(payload).encode("utf-8", errors="replace")
    return hashlib.sha256(encoded).hexdigest()


def _active_app_settings_file_path(env: Any) -> Path | None:
    settings_file = getattr(env, "app_settings_file", None)
    if not settings_file:
        return None
    try:
        return Path(settings_file).expanduser()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _clear_cluster_probe_caches() -> None:
    for cached_fn in (_remote_hardware_probe, _lan_discovery_hardware_inventory):
        cache_clear = getattr(cached_fn, "cache_clear", None)
        if callable(cache_clear):
            cache_clear()


def _cluster_sidebar_refresh_signature(env: Any, cluster_params: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _safe_text(getattr(env, "app", "")),
        _payload_signature(cluster_params),
        _file_content_signature(_active_app_settings_file_path(env)),
        _file_content_signature(_default_lan_discovery_cache_path()),
    )


def _refresh_cluster_probe_caches_if_needed(env: Any, cluster_params: dict[str, Any]) -> None:
    try:
        session_state = st.session_state
    except (AttributeError, RuntimeError):
        return
    signature = _cluster_sidebar_refresh_signature(env, cluster_params)
    app_name = _safe_text(getattr(env, "app", "")) or "default"
    state_key = f"about_cluster_probe_signature__{app_name}"
    if session_state.get(state_key) == signature:
        return
    _clear_cluster_probe_caches()
    session_state[state_key] = signature


@lru_cache(maxsize=8)
def _lan_discovery_hardware_inventory(cache_path: str = "") -> dict[str, dict[str, str]]:
    path = Path(cache_path).expanduser() if cache_path else _default_lan_discovery_cache_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    nodes = payload.get("nodes")
    if not isinstance(nodes, list):
        return {}
    inventory: dict[str, dict[str, str]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        host = _safe_text(node.get("host")) or _safe_text(node.get("ssh_target"))
        identity = _node_identity(host)
        if not identity:
            continue
        summary = _hardware_summary_from_mapping(node) or {}
        status = _safe_text(node.get("status"))
        error_values = node.get("errors")
        if status:
            summary["_status"] = status
        if isinstance(error_values, list) and error_values:
            summary["_error"] = _safe_text(error_values[0])
        if summary:
            inventory[identity] = summary
    return inventory


def _cluster_resource_totals(
    *,
    cluster_enabled: bool,
    scheduler: str,
    worker_items: list[tuple[str, Any]],
    user: str,
    ssh_key_path: str,
    hardware_inventory: dict[str, dict[str, str]] | None = None,
) -> dict[str, str]:
    nodes: list[str] = []
    seen_nodes: set[str] = set()

    def add_node(host: str) -> None:
        identity = _node_identity(host)
        if identity in seen_nodes:
            return
        seen_nodes.add(identity)
        nodes.append(host)

    if cluster_enabled:
        if scheduler:
            add_node(scheduler)
        for worker, _count in worker_items:
            worker_host = _safe_text(worker)
            if worker_host:
                add_node(worker_host)
    else:
        add_node("")

    if not nodes:
        return {
            "CPU": "not configured",
            "RAM": "not configured",
            "GPU": "not configured",
            "NPU": "not configured",
        }

    total_cores = 0
    total_ram_gb = 0.0
    gpu_counts: dict[str, int] = {}
    npu_counts: dict[str, int] = {}
    worker_issue_counts: dict[str, int] = {}
    hardware_inventory = hardware_inventory or {}

    for host in nodes:
        summary = _node_hardware_summary(host, user=user, ssh_key_path=ssh_key_path)
        if _summary_unreachable(summary):
            configured_summary = hardware_inventory.get(_node_identity(host))
            if _hardware_summary_has_detected_resources(configured_summary):
                summary = configured_summary
            else:
                status = _safe_text(configured_summary.get("_status")) if configured_summary else ""
                issue_label = _worker_issue_label(status)
                worker_issue_counts[issue_label] = worker_issue_counts.get(issue_label, 0) + 1
                continue
        cores = _parse_cpu_cores(summary.get("CPU", ""))
        if cores is not None:
            total_cores += cores
        ram_gb = _parse_ram_gb(summary.get("RAM", ""))
        if ram_gb is not None:
            total_ram_gb += ram_gb
        for label in _split_resource_descriptors(summary.get("GPU", "")):
            gpu_counts[label] = gpu_counts.get(label, 0) + 1
        for label in _split_resource_descriptors(summary.get("NPU", "")):
            npu_counts[label] = npu_counts.get(label, 0) + 1

    cpu_value = f"{total_cores} cores" if total_cores else "unknown"
    ram_value = _format_ram_gb(total_ram_gb) if total_ram_gb else "unknown"
    gpu_value = _format_counted_resources(gpu_counts)
    npu_value = _format_counted_resources(npu_counts)
    return {
        "CPU": _append_worker_issue_suffix(cpu_value, worker_issue_counts),
        "RAM": _append_worker_issue_suffix(ram_value, worker_issue_counts),
        "GPU": _append_worker_issue_suffix(gpu_value, worker_issue_counts),
        "NPU": _append_worker_issue_suffix(npu_value, worker_issue_counts),
    }


def active_app_cluster_information_lines(env: Any) -> list[tuple[str, str]]:
    """Return active-app scheduler and cluster context for sidebar display."""
    settings = _active_app_settings(env)
    cluster_params = _cluster_params_from_settings(settings)
    _refresh_cluster_probe_caches_if_needed(env, cluster_params)
    cluster_enabled = _format_bool_flag(cluster_params.get("cluster_enabled", False))

    app_name = _safe_text(getattr(env, "app", "")) or "not selected"
    scheduler = _safe_text(cluster_params.get("scheduler")) or _safe_text(getattr(env, "scheduler", ""))
    scheduler_display = _scheduler_display(scheduler, cluster_enabled=cluster_enabled)
    ssh_user = _safe_text(cluster_params.get("user")) or _safe_text(getattr(env, "user", ""))
    ssh_key_path = _safe_text(cluster_params.get("ssh_key_path")) or _safe_text(getattr(env, "ssh_key_path", ""))
    worker_items = _workers_items(cluster_params.get("workers", {}))
    hardware_inventory = {
        **_lan_discovery_hardware_inventory(),
        **_hardware_inventory_from_settings(cluster_params),
    }
    resource_totals = _cluster_resource_totals(
        cluster_enabled=cluster_enabled,
        scheduler=scheduler,
        worker_items=worker_items,
        user=ssh_user,
        ssh_key_path=ssh_key_path,
        hardware_inventory=hardware_inventory,
    )
    if cluster_enabled:
        workers_data_path = _safe_text(cluster_params.get("workers_data_path")) or _env_cluster_share(env)
        if not workers_data_path:
            workers_data_path = "not configured"
    else:
        workers_data_path = "not used"

    lines = [
        ("Active app", app_name),
        ("Scheduler", scheduler_display),
        ("Mode", _cluster_mode_label(cluster_params)),
        ("Share", workers_data_path),
        ("CPU", resource_totals["CPU"]),
        ("RAM", resource_totals["RAM"]),
        ("GPU", resource_totals["GPU"]),
        ("NPU", resource_totals["NPU"]),
    ]
    return lines


def _sidebar_system_information_html(lines: list[tuple[str, str]]) -> str:
    rows = []
    for label, value in lines:
        escaped_label = html.escape(label)
        escaped_value = html.escape(value)
        escaped_aria_label = html.escape(f"{label}: {value}", quote=True)
        rows.append(
            f"<div class='agilab-sidebar-system-row' aria-label='{escaped_aria_label}'>"
            f"<span class='agilab-sidebar-system-label'>{escaped_label}</span>"
            "<span class='agilab-sidebar-system-colon'>:</span>"
            f"<span class='agilab-sidebar-system-value'>{escaped_value}</span>"
            "</div>"
        )
    return (
        "<style>"
        ".agilab-sidebar-system {"
        "display:grid;"
        "gap:.2rem;"
        "margin:.4rem 0 .65rem 0;"
        "font-size:.78rem;"
        "line-height:1.28;"
        "}"
        ".agilab-sidebar-system-row {"
        "display:grid;"
        "grid-template-columns:max-content .45rem minmax(0,1fr);"
        "column-gap:.18rem;"
        "align-items:start;"
        "}"
        ".agilab-sidebar-system-label {"
        "color:rgba(247,242,232,.62);"
        "white-space:nowrap;"
        "}"
        ".agilab-sidebar-system-colon {"
        "color:rgba(247,242,232,.42);"
        "text-align:center;"
        "}"
        ".agilab-sidebar-system-value {"
        "color:#72d6b4;"
        "font-weight:650;"
        "overflow-wrap:anywhere;"
        "}"
        "</style>"
        "<div class='agilab-sidebar-system'>"
        f"{''.join(rows)}"
        "</div>"
    )


def render_sidebar_system_information(env: Any) -> None:
    """Render active-app scheduler and cluster context in the sidebar."""
    lines = active_app_cluster_information_lines(env)
    markdown = getattr(st.sidebar, "markdown", None)
    if callable(markdown):
        markdown(_sidebar_system_information_html(lines), unsafe_allow_html=True)
        return
    for label, value in lines:
        st.sidebar.caption(f"{label}: {value}")


@lru_cache(maxsize=8)
def _command_output(command: tuple[str, ...]) -> str:
    """Return best-effort command output for local hardware probes."""
    try:
        proc = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _parse_system_profiler_pairs(output: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for line in output.splitlines():
        match = re.match(r"\s*([^:]+):\s*(.+?)\s*$", line)
        if match:
            pairs[match.group(1).strip()] = match.group(2).strip()
    return pairs


def _mac_hardware_profile() -> dict[str, str]:
    if platform.system() != "Darwin":
        return {}
    return _parse_system_profiler_pairs(_command_output(("system_profiler", "SPHardwareDataType")))


def _cpu_summary(system: str) -> str:
    hardware = _mac_hardware_profile() if system == "Darwin" else {}
    cpu_name = hardware.get("Chip") or platform.processor() or platform.machine()
    if not cpu_name:
        return ""
    core_label = _cpu_core_label(system, hardware)
    return f"{cpu_name}; {core_label}" if core_label else cpu_name


def _cpu_core_label(system: str, hardware: dict[str, str]) -> str:
    if system == "Darwin" and hardware.get("Total Number of Cores"):
        return f"cores: {hardware['Total Number of Cores']}"

    logical = os.cpu_count()
    physical = _physical_cpu_count()
    if physical and logical and physical != logical:
        return f"cores: {physical} physical / {logical} logical"
    if logical:
        return f"cores: {logical} logical"
    return ""


def _physical_cpu_count() -> int | None:
    try:
        import psutil  # type: ignore
    except ImportError:
        return None
    try:
        count = psutil.cpu_count(logical=False)
    except Exception:
        return None
    return int(count) if count else None


def _gpu_summary(system: str) -> str:
    if system == "Darwin":
        mac_gpu = _mac_gpu_summary()
        if mac_gpu:
            return mac_gpu

    nvidia_gpu = _nvidia_gpu_summary()
    if nvidia_gpu:
        return nvidia_gpu
    return "Not detected"


def _mac_gpu_summary() -> str:
    output = _command_output(("system_profiler", "SPDisplaysDataType"))
    if not output:
        return ""

    gpus: list[str] = []
    current_model = ""
    current_cores = ""
    current_is_gpu = False

    def flush_current() -> None:
        nonlocal current_model, current_cores, current_is_gpu
        if current_model and (current_is_gpu or current_cores):
            suffix = f" ({current_cores} cores)" if current_cores else ""
            gpus.append(f"{current_model}{suffix}")
        current_model = ""
        current_cores = ""
        current_is_gpu = False

    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Chipset Model:"):
            flush_current()
            current_model = stripped.split(":", 1)[1].strip()
        elif stripped == "Type: GPU":
            current_is_gpu = True
        elif stripped.startswith("Total Number of Cores:"):
            current_cores = stripped.split(":", 1)[1].strip()
    flush_current()

    if not gpus:
        return ""
    if len(gpus) == 1:
        return gpus[0]
    return f"{len(gpus)} GPUs: " + "; ".join(gpus)


def _nvidia_gpu_summary() -> str:
    output = _command_output(
        (
            "nvidia-smi",
            "--query-gpu=name,multiprocessor_count",
            "--format=csv,noheader,nounits",
        )
    )
    if not output:
        return ""

    gpus: list[str] = []
    for line in output.splitlines():
        parts = [part.strip() for part in line.split(",") if part.strip()]
        if not parts:
            continue
        if len(parts) >= 2 and parts[1].isdigit():
            gpus.append(f"{parts[0]} ({parts[1]} SMs)")
        else:
            gpus.append(parts[0])
    if not gpus:
        return ""
    if len(gpus) == 1:
        return gpus[0]
    return f"{len(gpus)} GPUs: " + "; ".join(gpus)


def _npu_summary(system: str, chip_name: str) -> str:
    if system == "Darwin" and re.match(r"Apple M[1-4](?:\s|$)", chip_name):
        return "Apple Neural Engine (16 cores)"
    return "Not detected"


def render_footer() -> None:
    """Keep compatibility with callers; legal text now lives in the banner."""
