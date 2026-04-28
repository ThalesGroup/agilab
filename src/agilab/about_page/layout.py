"""Display-only helpers for the AGILab About page."""

from __future__ import annotations

import base64
import os
import platform
import re
import subprocess
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import streamlit as st


def _hero_target_svg_data_uri() -> str:
    """Return the banner target diagram as an image-safe SVG data URI."""
    svg = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 420 260" role="img" aria-label="Bias variance controls, underfit overfit symptoms, and train test diagnosis">
  <defs>
    <filter id="glow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="2.4" result="blur" />
      <feMerge>
        <feMergeNode in="blur" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>
    <linearGradient id="cardFill" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0" stop-color="rgba(255,255,255,.12)" />
      <stop offset="1" stop-color="rgba(255,255,255,.045)" />
    </linearGradient>
  </defs>
  <style>
    .title{fill:rgba(247,242,232,.82);font:850 14px 'Aptos Display','Avenir Next',sans-serif;letter-spacing:.1em;text-transform:uppercase}
    .eyebrow{fill:rgba(255,210,138,.86);font:850 8.8px 'Aptos Display','Avenir Next',sans-serif;letter-spacing:.13em;text-transform:uppercase}
    .main{fill:rgba(247,242,232,.9);font:850 12.5px 'Aptos Display','Avenir Next',sans-serif;letter-spacing:.04em}
    .tiny{fill:rgba(247,242,232,.62);font:700 8.6px 'Aptos Display','Avenir Next',sans-serif;letter-spacing:.05em;text-transform:uppercase}
    .note{fill:rgba(255,210,138,.9);font:850 10.5px 'Aptos Display','Avenir Next',sans-serif;letter-spacing:.08em}
    .card{fill:url(#cardFill);stroke:rgba(247,242,232,.18);stroke-width:1}
    .target{fill:rgba(255,255,255,.06);stroke:rgba(247,242,232,.28);stroke-width:1.4}
    .ring{fill:none;stroke:rgba(247,242,232,.22);stroke-width:1.1}
    .core{fill:none;stroke:rgba(255,210,138,.44);stroke-width:1.2}
    .axis{stroke:rgba(247,242,232,.16)}
    .connector{fill:none;stroke:rgba(247,242,232,.24);stroke-width:1.1;stroke-linecap:round}
  </style>
  <text class="title" x="210" y="24" text-anchor="middle">Generalization map</text>
  <text class="note" x="210" y="239" text-anchor="middle">controls drive symptoms; train/test confirms</text>

  <g transform="translate(118 127)">
    <circle class="target" r="78" />
    <circle class="ring" r="58" />
    <circle class="ring" r="38" />
    <circle class="core" r="18" />
    <line class="axis" x1="-86" y1="0" x2="86" y2="0" />
    <line class="axis" x1="0" y1="-86" x2="0" y2="86" />
    <circle cx="0" cy="0" r="4.6" fill="#ffd28a" filter="url(#glow)" />
  </g>

  <ellipse cx="119" cy="126" rx="19" ry="14" fill="rgba(114,214,180,.08)" stroke="#72d6b4" stroke-width="2" stroke-dasharray="4 3" />
  <g fill="#72d6b4" filter="url(#glow)">
    <circle cx="113" cy="123" r="3.8" />
    <circle cx="121" cy="127" r="3.8" />
    <circle cx="126" cy="120" r="3.8" />
    <circle cx="116" cy="133" r="3.8" />
  </g>

  <path d="M118 127 L178 80" fill="none" stroke="#ffbe5e" stroke-width="3" stroke-linecap="round" />
  <path d="M166 79 L180 79 L174 92" fill="none" stroke="#ffbe5e" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
  <ellipse cx="179" cy="80" rx="20" ry="14" fill="rgba(255,190,94,.08)" stroke="#ffbe5e" stroke-width="2" stroke-dasharray="4 3" />
  <g fill="#ffbe5e">
    <circle cx="171" cy="76" r="3.8" />
    <circle cx="179" cy="82" r="3.8" />
    <circle cx="186" cy="77" r="3.8" />
    <circle cx="183" cy="88" r="3.8" />
  </g>

  <ellipse cx="116" cy="129" rx="59" ry="49" fill="rgba(255,112,94,.035)" stroke="#ff705e" stroke-width="1.8" stroke-dasharray="6 5" />
  <g fill="none" stroke="#ff705e" stroke-width="2.3">
    <circle cx="73" cy="93" r="3.8" />
    <circle cx="160" cy="106" r="3.8" />
    <circle cx="85" cy="162" r="3.8" />
    <circle cx="145" cy="177" r="3.8" />
    <circle cx="101" cy="116" r="3.8" />
  </g>

  <path class="connector" d="M200 82 C218 75, 221 72, 231 68" />
  <path class="connector" d="M180 127 C204 127, 216 127, 231 127" />
  <path class="connector" d="M174 168 C205 185, 218 190, 231 190" />

  <rect class="card" x="230" y="47" width="166" height="42" rx="12" />
  <rect x="230" y="47" width="5" height="42" rx="2.5" fill="#ffd28a" />
  <text class="eyebrow" x="245" y="63">Controls</text>
  <text class="main" x="245" y="80">Bias &#8596; Variance</text>

  <rect class="card" x="230" y="106" width="166" height="42" rx="12" />
  <rect x="230" y="106" width="5" height="42" rx="2.5" fill="#ffbe5e" />
  <text class="eyebrow" x="245" y="122">Symptoms</text>
  <text class="main" x="245" y="139">Underfit &#8596; Overfit</text>

  <rect class="card" x="230" y="165" width="166" height="48" rx="12" />
  <rect x="230" y="165" width="5" height="48" rx="2.5" fill="#72d6b4" />
  <text class="eyebrow" x="245" y="181">Diagnosis</text>
  <text class="main" x="245" y="197">Train vs Test</text>
  <path d="M326 197 C337 187, 352 183, 383 180" fill="none" stroke="#72d6b4" stroke-width="2" stroke-linecap="round" />
  <path d="M326 190 C339 178, 351 174, 364 178 C376 182, 383 190, 390 199" fill="none" stroke="#ffbe5e" stroke-width="2" stroke-linecap="round" />
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
                grid-template-columns: minmax(0, 1fr) minmax(260px, 360px);
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
                min-height: 225px;
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
                margin: 1.05rem 0 0;
                color: rgba(247, 242, 232, 0.58);
                font-size: 0.78rem;
                line-height: 1.35;
                text-align: right;
              }}
              @media (max-width: 520px) {{
                .agilab-hero__body {{
                  grid-template-columns: 1fr;
                }}
                .agilab-hero__brand {{
                  align-items: flex-start;
                  border-radius: 18px;
                  flex-direction: column;
                }}
              }}
            </style>
            <section class="agilab-hero" aria-label="AGILAB introduction">
              <div class="agilab-hero__brand">
                <img src="{img_src}" alt="AGILAB logo">
                <span>Open-source workbench</span>
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
                <div class="agilab-hero__visual" role="img" aria-label="Bias versus precision target diagram">
                  <img
                    class="agilab-hero__target-img"
                    src="{target_svg_src}"
                    alt="Bias variance controls, underfit overfit symptoms, and train test diagnosis"
                  >
                </div>
              </div>
              <p class="agilab-hero__legal">
                &copy; 2020-{current_year} Thales SIX GTS. Licensed under the BSD 3-Clause License.
              </p>
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


def render_sidebar_system_information() -> None:
    """Render compact local hardware information in the sidebar."""
    for label, value in system_information_lines():
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
