#!/usr/bin/env python3
"""Exercise AGILAB public UI widgets through a real browser."""

from __future__ import annotations

import argparse
import csv
import itertools
import importlib.util
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.parse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
SRC_PACKAGE = SRC_ROOT / "agilab"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
try:
    import agilab as _agilab_package
except ModuleNotFoundError:
    _agilab_package = None
if _agilab_package is not None and str(SRC_PACKAGE) not in _agilab_package.__path__:
    _agilab_package.__path__.insert(0, str(SRC_PACKAGE))

from agilab.page_bundle_registry import (  # noqa: E402
    PageBundleSpec,
    configured_page_bundle_names,
    discover_page_bundle,
    discover_page_bundles,
    resolve_page_bundles,
)
from agi_env.app_provider_registry import aliased_app_runtime_target, app_name_aliases  # noqa: E402

logger = logging.getLogger(__name__)

WEB_ROBOT_PATH = REPO_ROOT / "tools/agilab_web_robot.py"
DEFAULT_APPS_ROOT = REPO_ROOT / "src/agilab/apps/builtin"
DEFAULT_APPS_PAGES_ROOT = REPO_ROOT / "src/agilab/apps-pages"
DEFAULT_PAGES = ("", "PROJECT", "ORCHESTRATE", "WORKFLOW", "ANALYSIS")
DEFAULT_TIMEOUT_SECONDS = 90.0
DEFAULT_WIDGET_TIMEOUT_SECONDS = 3.0
DEFAULT_PAGE_TIMEOUT_SECONDS = 300.0
DEFAULT_ACTION_TIMEOUT_SECONDS = 30.0
DEFAULT_TARGET_SECONDS = 1800.0
ACTION_BUTTON_KINDS = {"button", "form_submit_button", "download_button"}
CHOICE_BUTTON_KINDS = {"segmented_control", "pills"}
RUNTIME_ISOLATION_MODES = ("isolated", "current-home")
MISSING_SELECTED_ACTION_POLICIES = ("fail", "ignore-absent")
SAFE_ACTION_LABEL_PREFIXES = ("view", "open", "show", "select", "choose", "browse", "back", "cancel", "close", "refresh", "reload")
RISKY_ACTION_LABEL_TOKENS = {
    "add",
    "apply",
    "build",
    "clear",
    "clone",
    "create",
    "delete",
    "deploy",
    "distribute",
    "execute",
    "export",
    "generate",
    "import",
    "install",
    "kill",
    "launch",
    "remove",
    "rename",
    "reset",
    "run",
    "save",
    "start",
    "stop",
    "submit",
    "sync",
    "train",
    "update",
    "upload",
}
PUBLIC_APP_TARGETS_WITH_SEEDED_ARTIFACTS = {"flight", "meteo_forecast", "uav_queue", "uav_relay_queue"}
NO_OUTPUT_ORCHESTRATE_JOURNEY_APPS = {"mycode_project"}
ORCHESTRATE_OUTPUT_ACTION_LABELS = {
    "run -> load -> export",
    "load output",
    "export dataframe",
    "delete output",
    "confirm delete",
}
TERMINAL_IDLE_SETTLE_ACTION_LABELS = {"confirm delete"}
ORCHESTRATE_OUTPUT_SIDE_EFFECT_LABELS = {"run -> load -> export", "load output"}
ORCHESTRATE_EXPORT_SIDE_EFFECT_LABELS = {"run -> load -> export", "export dataframe"}
ORCHESTRATE_DELETE_SIDE_EFFECT_LABELS = {"confirm delete"}
ORCHESTRATE_PREVIEW_FILE_SUFFIXES = (".parquet", ".csv", ".json", ".gml")
ORCHESTRATE_PREVIEW_METADATA_FILENAMES = {"run_manifest.json", "notebook_import_view_plan.json"}
ORCHESTRATE_PREVIEW_METADATA_PREFIXES = ("._", "reduce_summary_worker_")
ORCHESTRATE_FALLBACK_OUTPUT_DIRS = ("dataframe", "results", "reports", "pipeline")
WORKFLOW_STAGE_CONTRACT_FILENAME = "lab_stages.toml"
WORKFLOW_STAGE_CONTRACT_SCHEMA = "agilab.lab_stages.v1"
WORKFLOW_RUN_ACTION_LABELS = {
    "run workflow",
    "clear stale lock and run",
    "confirm force unlock",
}
CURRENT_HOME_PREFLIGHT_ACTION_LABELS = (
    "CHECK distribute",
    "DISTRIBUTE",
    "INSTALL",
    "Run -> Load -> Export",
    "Run now",
)
CURRENT_HOME_WORKER_IMPORT_PREFLIGHT_ACTION_LABELS = (
    "CHECK distribute",
    "DISTRIBUTE",
    "Run -> Load -> Export",
    "Run now",
)
CURRENT_HOME_WORKER_IMPORT_TIMEOUT_SECONDS = 20.0
BROWSER_ISSUE_FATAL_NEEDLES = (
    "agi execution failed",
    "build failed",
    "command failed",
    "distribution build failed",
    "exception",
    "export failed",
    "failed with exit code",
    "load failed",
    "modulenotfounderror",
    "no module named",
    "non-zero exit status",
    "runtimeerror",
    "streamlitapiexception",
    "traceback",
    "typeerror",
    "uncaught",
    "valueerror",
    "worker failed",
)
BROWSER_ISSUE_IGNORE_NEEDLES = (
    "favicon",
    "failed to load resource",
    "net::err_aborted",
    "websocket",
)
PAGE_EXPECTED_TEXT = {
    "": ("AGILAB", "Start here"),
    "PROJECT": ("PROJECT", "Active app", "Project"),
    "ORCHESTRATE": ("ORCHESTRATE", "INSTALL", "EXECUTE"),
    "WORKFLOW": ("WORKFLOW", "Workflow", "Run"),
    "ANALYSIS": ("ANALYSIS", "Choose pages", "View:"),
}
PAGE_MIN_WIDGETS = {"": 5, "PROJECT": 5, "ORCHESTRATE": 5, "WORKFLOW": 3, "ANALYSIS": 3}

WIDGET_COLLECTOR_JS = r"""
() => {
  for (const el of document.querySelectorAll("[data-agilab-widget-id]")) {
    el.removeAttribute("data-agilab-widget-id");
  }
  window.__agilabWidgetRobotRunId = (window.__agilabWidgetRobotRunId || 0) + 1;
  const runId = window.__agilabWidgetRobotRunId;
  const specs = [
    ["button", "[data-testid='stButton'] button"],
    ["form_submit_button", "[data-testid='stFormSubmitButton'] button"],
    ["download_button", "[data-testid='stDownloadButton'] button"],
    ["segmented_control", "button[data-testid^='stBaseButton-segmented_control']"],
    ["pills", "button[data-testid^='stBaseButton-pills']"],
    ["checkbox", "[data-testid='stCheckbox'] input"],
    ["toggle", "[data-testid='stToggle'] input, [role='switch']"],
    ["radio", "[data-testid='stRadio'] input"],
    ["selectbox", "[data-testid='stSelectbox']"],
    ["multiselect", "[data-testid='stMultiSelect']"],
    ["text_input", "[data-testid='stTextInput'] input"],
    ["text_area", "[data-testid='stTextArea'] textarea"],
    ["number_input", "[data-testid='stNumberInput'] input"],
    ["slider", "[data-testid='stSlider'] [role='slider'], [role='slider']"],
    ["file_uploader", "[data-testid='stFileUploader']"],
    ["data_editor", "[data-testid='stDataFrame'], [data-testid='stDataEditor']"],
    ["tab", "[role='tab']"],
    ["expander", "[data-testid='stExpander'] summary, details summary"],
  ];
  const visible = (el) => {
    if (el.closest("details:not([open])") && !el.closest("summary")) return false;
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
  };
  const labelFor = (el) => {
    const direct = el.getAttribute("aria-label") || el.getAttribute("title") || el.getAttribute("placeholder");
    if (direct && direct.trim()) return direct.trim();
    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
      const label = document.getElementById(labelledBy);
      if (label && label.innerText.trim()) return label.innerText.trim().replace(/\s+/g, " ").slice(0, 160);
    }
    const container = el.closest("[data-testid]");
    const text = (container || el).innerText || el.value || el.textContent || "";
    return text.trim().replace(/\s+/g, " ").slice(0, 160);
  };
  const testIdFor = (el) => {
    const container = el.closest("[data-testid]");
    return container ? container.getAttribute("data-testid") : "";
  };
  const scopeFor = (el) => {
    return el.closest("[data-testid='stSidebar']") ? "sidebar" : "main";
  };
  const pathFor = (el) => {
    const parts = [];
    let current = el;
    while (current && current.nodeType === Node.ELEMENT_NODE && parts.length < 6) {
      const parent = current.parentElement;
      const tag = current.tagName.toLowerCase();
      if (!parent) {
        parts.push(tag);
        break;
      }
      const index = Array.from(parent.children).filter((child) => child.tagName === current.tagName).indexOf(current) + 1;
      parts.push(`${tag}:nth-of-type(${index})`);
      current = parent;
    }
    return parts.reverse().join(">");
  };
  const seen = new Set();
  const widgets = [];
  let nextId = 0;
  for (const [kind, selector] of specs) {
    for (const el of document.querySelectorAll(selector)) {
      if (!visible(el) || seen.has(el)) continue;
      seen.add(el);
      const id = `agilab-widget-${runId}-${nextId++}`;
      el.setAttribute("data-agilab-widget-id", id);
      widgets.push({
        id,
        kind,
        label: labelFor(el),
        disabled: Boolean(el.disabled || el.getAttribute("aria-disabled") === "true"),
        role: el.getAttribute("role") || "",
        tag: el.tagName.toLowerCase(),
        type: el.getAttribute("type") || "",
        checked: Boolean(el.checked || el.getAttribute("aria-checked") === "true"),
        name: el.getAttribute("name") || "",
        value: el.getAttribute("value") || "",
        testid: testIdFor(el),
        path: pathFor(el),
        scope: scopeFor(el),
      });
    }
  }
  return widgets;
}
"""

OPEN_EXPANDERS_JS = r"""
() => {
  let changed = 0;
  for (const details of document.querySelectorAll("details")) {
    if (!details.open) {
      const summary = details.querySelector(":scope > summary") || details.querySelector("summary");
      if (summary) {
        summary.click();
      } else {
        details.open = true;
      }
      changed += 1;
    }
  }
  return changed;
}
"""

CLOSE_EXPANDERS_JS = r"""
() => {
  let changed = 0;
  for (const details of document.querySelectorAll("details")) {
    if (details.open) {
      const summary = details.querySelector(":scope > summary") || details.querySelector("summary");
      if (summary) {
        summary.click();
      } else {
        details.open = false;
      }
      changed += 1;
    }
  }
  return changed;
}
"""

CLOSE_EXPANDERS_EXCEPT_WIDGET_JS = r"""
(widgetId) => {
  const target = document.querySelector(`[data-agilab-widget-id="${widgetId}"]`);
  if (!target) return 0;
  let changed = 0;
  for (const details of document.querySelectorAll("details")) {
    if (details.contains(target)) {
      if (!details.open) {
        const summary = details.querySelector(":scope > summary") || details.querySelector("summary");
        if (summary) {
          summary.click();
        } else {
          details.open = true;
        }
        changed += 1;
      }
      continue;
    }
    if (details.open) {
      const summary = details.querySelector(":scope > summary") || details.querySelector("summary");
      if (summary) {
        summary.click();
      } else {
        details.open = false;
      }
      changed += 1;
    }
  }
  return changed;
}
"""

SCROLL_METRICS_JS = r"""
() => {
  const doc = document.documentElement;
  const body = document.body || doc;
  return {
    y: window.scrollY || doc.scrollTop || body.scrollTop || 0,
    height: window.innerHeight || doc.clientHeight || 1000,
    scrollHeight: Math.max(body.scrollHeight || 0, doc.scrollHeight || 0),
  };
}
"""

SCROLL_WIDGET_TO_CENTER_JS = r"""
(widgetId) => {
  const target = document.querySelector(`[data-agilab-widget-id="${widgetId}"]`);
  if (!target) return false;
  target.scrollIntoView({block: "center", inline: "center"});
  return true;
}
"""

VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS = r"""
() => {
  const visible = (el) => {
    if (el.closest("details:not([open])") && !el.closest("summary")) return false;
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
  };
  const clean = (value) => String(value || "").trim().replace(/\s+/g, " ");
  const issues = [];
  const push = (kind, el, fallback) => {
    const detail = clean(el.innerText || el.textContent || fallback).slice(0, 500);
    issues.push({kind, detail: detail || fallback});
  };
  for (const el of document.querySelectorAll("[data-testid='stException']")) {
    if (visible(el)) {
      push("exception", el, "Streamlit exception rendered");
    }
  }
  const errorNeedles = [
    "agi execution failed",
    "build failed",
    "command failed",
    "distribution build failed",
    "export failed",
    "failed with exit code",
    "load failed",
    "modulenotfounderror",
    "no module named",
    "non-zero exit status",
    "runtimeerror",
    "streamlitapi",
    "traceback",
    "typeerror",
    "uncaught",
    "valueerror",
  ];
  const selectors = [
    "[data-testid='stAlert']",
    "[data-testid='stAlertContainer']",
    "[data-testid='stStatus']",
    "[data-testid='stStatusWidget']",
    "[data-testid='stToast']",
    "[data-testid='stNotification']",
    "[role='alert']",
    "[aria-live='assertive']",
  ].join(", ");
  for (const el of document.querySelectorAll(selectors)) {
    if (!visible(el)) continue;
    const text = clean(el.innerText || el.textContent || "");
    const metadata = clean([
      el.getAttribute("aria-label"),
      el.getAttribute("role"),
      el.getAttribute("class"),
      el.getAttribute("data-testid"),
    ].join(" ")).toLowerCase();
    const combined = `${metadata} ${text.toLowerCase()}`;
    if (errorNeedles.some((needle) => combined.includes(needle))) {
      push("error", el, "Streamlit error alert rendered");
    }
  }
  return issues;
}
"""

VISIBLE_STREAMLIT_FEEDBACK_COLLECTOR_JS = r"""
() => {
  const visible = (el) => {
    if (el.closest("details:not([open])") && !el.closest("summary")) return false;
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
  };
  const clean = (value) => String(value || "").trim().replace(/\s+/g, " ");
  const errorNeedles = [
    "agi execution failed",
    "build failed",
    "command failed",
    "distribution build failed",
    "export failed",
    "failed with exit code",
    "load failed",
    "modulenotfounderror",
    "no module named",
    "non-zero exit status",
    "runtimeerror",
    "streamlitapi",
    "traceback",
    "typeerror",
    "uncaught",
    "valueerror",
  ];
  const fatalTextNeedles = [
    "agi execution failed",
    "build failed",
    "command failed",
    "distribution build failed",
    "export failed",
    "failed with exit code",
    "load failed",
    "modulenotfounderror",
    "no module named",
    "non-zero exit status",
    "runtimeerror",
    "streamlitapiexception",
    "traceback",
    "typeerror",
    "uncaught exception",
    "valueerror",
  ];
  const feedback = [];
  const push = (kind, el, fallback) => {
    const detail = clean(el.innerText || el.textContent || fallback).slice(0, 500);
    feedback.push({kind, detail: detail || fallback});
  };
  for (const el of document.querySelectorAll("[data-testid='stException']")) {
    if (visible(el)) {
      push("exception", el, "Streamlit exception rendered");
    }
  }
  const semanticSelectors = [
    "[data-testid='stAlert']",
    "[data-testid='stAlertContainer']",
    "[data-testid='stStatus']",
    "[data-testid='stStatusWidget']",
    "[data-testid='stToast']",
    "[data-testid='stNotification']",
    "[role='alert']",
    "[aria-live='assertive']",
  ].join(", ");
  for (const el of document.querySelectorAll(semanticSelectors)) {
    if (!visible(el)) continue;
    const text = clean(el.innerText || el.textContent || "");
    const metadata = clean([
      el.getAttribute("aria-label"),
      el.getAttribute("role"),
      el.getAttribute("class"),
      el.getAttribute("data-testid"),
    ].join(" ")).toLowerCase();
    const combined = `${metadata} ${text.toLowerCase()}`;
    if (errorNeedles.some((needle) => combined.includes(needle))) {
      push("error", el, "Streamlit error alert rendered");
    } else if (combined.includes("success") || combined.includes("successfully")) {
      push("success", el, "Streamlit success alert rendered");
    } else if (combined.includes("warning")) {
      push("warning", el, "Streamlit warning alert rendered");
    } else {
      push("info", el, "Streamlit alert rendered");
    }
  }
  const renderedTextSelectors = [
    "[data-testid='stCodeBlock']",
    "[data-testid='stMarkdownContainer']",
    "pre",
    "code",
  ].join(", ");
  for (const el of document.querySelectorAll(renderedTextSelectors)) {
    if (!visible(el)) continue;
    const text = clean(el.innerText || el.textContent || "");
    const lower = text.toLowerCase();
    if (fatalTextNeedles.some((needle) => lower.includes(needle))) {
      push("error", el, "fatal diagnostic text rendered");
    }
  }
  return feedback;
}
"""

ACTION_LOG_FEEDBACK_COLLECTOR_JS = r"""
() => {
  const clean = (value) => String(value || "").trim().replace(/\s+/g, " ");
  const errorNeedles = [
    "agi execution failed",
    "build failed",
    "command failed",
    "distribution build failed",
    "export failed",
    "failed with exit code",
    "load failed",
    "modulenotfounderror",
    "no module named",
    "non-zero exit status",
    "runtimeerror",
    "streamlitapi",
    "traceback",
    "typeerror",
    "uncaught",
    "valueerror",
  ];
  const logTitleNeedles = [
    "details",
    "diagnostic",
    "orchestration log",
    "execution log",
    "install log",
    "output",
    "result",
    "run log",
    "service log",
  ];
  const feedback = [];
  const push = (kind, el, fallback) => {
    const detail = clean(el.innerText || el.textContent || fallback).slice(0, 500);
    feedback.push({kind, detail: detail || fallback});
  };
  const hasFailure = (text) => {
    const value = clean(text).toLowerCase();
    return value && errorNeedles.some((needle) => value.includes(needle));
  };
  for (const details of document.querySelectorAll("details")) {
    const summary = details.querySelector(":scope > summary") || details.querySelector("summary");
    const title = clean(summary ? (summary.innerText || summary.textContent || "") : "").toLowerCase();
    if (!logTitleNeedles.some((needle) => title.includes(needle))) continue;
    for (const el of details.querySelectorAll("[data-testid='stException'], [data-testid='stAlert'], [data-testid='stAlertContainer'], [data-testid='stStatus'], [data-testid='stStatusWidget'], [data-testid='stCodeBlock'], [data-testid='stMarkdownContainer'], [role='alert'], pre, code")) {
      if (hasFailure(el.innerText || el.textContent || "")) {
        push("error", el, "action log failure rendered");
      }
    }
    if (feedback.length === 0 && hasFailure(details.innerText || details.textContent || "")) {
      push("error", details, "action log failure rendered");
    }
  }
  return feedback;
}
"""


@dataclass(frozen=True)
class AppsPageRoute:
    name: str
    path: Path


@dataclass(frozen=True)
class WidgetProbe:
    app: str
    page: str
    kind: str
    label: str
    status: str
    detail: str
    url: str
    scope: str = "main"


@dataclass(frozen=True)
class PageSweep:
    app: str
    page: str
    success: bool
    duration_seconds: float
    widget_count: int
    interacted_count: int
    probed_count: int
    skipped_count: int
    failed_count: int
    url: str
    failures: list[WidgetProbe]
    skips: list[WidgetProbe]
    main_widget_count: int = 0
    sidebar_widget_count: int = 0
    status: str = "passed"
    combination_space_count: int = 0
    combination_count: int = 0
    combination_failed_count: int = 0
    combination_skipped_count: int = 0


@dataclass(frozen=True)
class WidgetSweepSummary:
    success: bool
    total_duration_seconds: float
    target_seconds: float
    within_target: bool
    app_count: int
    page_count: int
    widget_count: int
    interacted_count: int
    probed_count: int
    skipped_count: int
    failed_count: int
    pages: list[PageSweep]
    main_widget_count: int = 0
    sidebar_widget_count: int = 0
    combination_space_count: int = 0
    combination_count: int = 0
    combination_failed_count: int = 0
    combination_skipped_count: int = 0


@dataclass(frozen=True)
class SeededRuntime:
    env: dict[str, str]
    home_root: Path
    export_root: Path
    share_root: Path
    cluster_share_root: Path


@dataclass(frozen=True)
class ArtifactFileSnapshot:
    files: dict[Path, tuple[int, int]]


@dataclass(frozen=True)
class OrchestrateArtifactContext:
    app_name: str
    active_app_query: str
    home_root: Path
    export_root: Path
    share_root: Path
    cluster_share_root: Path


@dataclass(frozen=True)
class WorkflowArtifactContext:
    app_name: str
    active_app_query: str
    home_root: Path
    export_root: Path


class PageWatchdogTimeout(TimeoutError):
    """Raised when one page sweep exceeds the whole-page watchdog."""


PageResultCallback = Callable[[PageSweep], None]


class ProgressReporter:
    def __init__(self, path: Path | None, *, stderr: bool = True) -> None:
        self.path = path
        self.stderr = stderr
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: str, **payload: Any) -> dict[str, Any]:
        record = {"ts": datetime.now(UTC).isoformat(), "event": event, **payload}
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
        if self.stderr:
            self._emit_stderr(record)
        return record

    def _emit_stderr(self, record: dict[str, Any]) -> None:
        event = str(record.get("event", "progress"))
        app = str(record.get("app", ""))
        page = str(record.get("page", ""))
        label = f"{app}/{page}".strip("/")
        if event == "page_start":
            print(f"[widget-robot] start {label}", file=sys.stderr)
        elif event == "page_done":
            print(
                f"[widget-robot] done {label} status={record.get('status')} "
                f"duration={float(record.get('duration_seconds', 0.0)):.2f}s",
                file=sys.stderr,
            )
        elif event == "page_resume":
            print(f"[widget-robot] resume {label} status={record.get('status')}", file=sys.stderr)
        elif event == "run_start":
            print(f"[widget-robot] run start apps={record.get('app_count')} pages={record.get('page_count')}", file=sys.stderr)
        elif event == "run_done":
            print(f"[widget-robot] run done status={record.get('status')} duration={float(record.get('duration_seconds', 0.0)):.2f}s", file=sys.stderr)


def page_result_key(app: str, page: str) -> str:
    return f"{app}::{page}"


def _streamlit_health_failure_detail(health: Any, server: Any, *, base_url: str) -> str:
    detail = str(getattr(health, "detail", "") or "streamlit server did not become healthy")
    process = getattr(server, "process", None)
    returncode = process.poll() if process is not None else None
    output_tail_fn = getattr(server, "output_tail", None)
    output_tail = ""
    if callable(output_tail_fn):
        output_tail = str(output_tail_fn() or "").strip()
    if returncode is None and process is not None:
        detail = f"{detail}; process still running; url={base_url}"
    elif returncode is not None:
        detail = f"{detail}; process exited with {returncode}; url={base_url}"
    if output_tail:
        detail = f"{detail}; output tail: {output_tail}"
    return detail


def _widget_probe_from_dict(data: dict[str, Any]) -> WidgetProbe:
    return WidgetProbe(
        app=str(data.get("app", "")),
        page=str(data.get("page", "")),
        kind=str(data.get("kind", "")),
        label=str(data.get("label", "")),
        status=str(data.get("status", "")),
        detail=str(data.get("detail", "")),
        url=str(data.get("url", "")),
        scope=str(data.get("scope", "main")),
    )


def page_sweep_from_dict(data: dict[str, Any]) -> PageSweep:
    return PageSweep(
        app=str(data.get("app", "")),
        page=str(data.get("page", "")),
        success=bool(data.get("success", False)),
        duration_seconds=float(data.get("duration_seconds", 0.0)),
        widget_count=int(data.get("widget_count", 0)),
        interacted_count=int(data.get("interacted_count", 0)),
        probed_count=int(data.get("probed_count", 0)),
        skipped_count=int(data.get("skipped_count", 0)),
        failed_count=int(data.get("failed_count", 0)),
        url=str(data.get("url", "")),
        failures=[_widget_probe_from_dict(item) for item in data.get("failures", [])],
        skips=[_widget_probe_from_dict(item) for item in data.get("skips", [])],
        main_widget_count=int(data.get("main_widget_count", 0)),
        sidebar_widget_count=int(data.get("sidebar_widget_count", 0)),
        status=str(data.get("status", "passed")),
        combination_space_count=int(data.get("combination_space_count", 0)),
        combination_count=int(data.get("combination_count", 0)),
        combination_failed_count=int(data.get("combination_failed_count", 0)),
        combination_skipped_count=int(data.get("combination_skipped_count", 0)),
    )


def load_completed_page_results(progress_log: Path) -> dict[str, PageSweep]:
    if not progress_log.exists():
        return {}
    completed: dict[str, PageSweep] = {}
    for line in progress_log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("event") != "page_done" or not isinstance(record.get("result"), dict):
            continue
        page = page_sweep_from_dict(record["result"])
        if page.status == "passed" and page.success:
            completed[page_result_key(page.app, page.page)] = page
    return completed


def write_summary_json(path: Path, pages: Sequence[PageSweep], *, app_count: int, target_seconds: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    summary = summarize(pages, app_count=app_count, target_seconds=target_seconds)
    tmp_path.write_text(json.dumps(asdict(summary), indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _emit_page_result(page: PageSweep, *, progress: ProgressReporter | None, on_page_result: PageResultCallback | None) -> None:
    if progress is not None:
        progress.emit(
            "page_done",
            app=page.app,
            page=page.page,
            status=page.status,
            success=page.success,
            duration_seconds=page.duration_seconds,
            result=asdict(page),
        )
    if on_page_result is not None:
        on_page_result(page)


def _resume_page_if_available(
    *,
    app_name: str,
    page_name: str,
    resume_page_results: dict[str, PageSweep] | None,
    progress: ProgressReporter | None,
    on_page_result: PageResultCallback | None,
) -> PageSweep | None:
    if not resume_page_results:
        return None
    page = resume_page_results.get(page_result_key(app_name, page_name))
    if page is None:
        return None
    if progress is not None:
        progress.emit("page_resume", app=page.app, page=page.page, status=page.status)
    if on_page_result is not None:
        on_page_result(page)
    return page


def _enforce_page_deadline(page_deadline: float | None, detail: str) -> None:
    if page_deadline is not None and time.perf_counter() > page_deadline:
        raise PageWatchdogTimeout(detail)


@dataclass(frozen=True)
class WidgetChoice:
    control_id: str
    kind: str
    label: str
    value: str
    widget: dict[str, Any]
    checked: bool | None = None
    option_index: int | None = None
    default: bool = False


@dataclass(frozen=True)
class WidgetControl:
    control_id: str
    kind: str
    label: str
    choices: tuple[WidgetChoice, ...]


@dataclass(frozen=True)
class WidgetCombinationPlan:
    controls: tuple[WidgetControl, ...]
    total_count: int
    combinations: tuple[tuple[WidgetChoice, ...], ...]
    truncated: bool = False


def _load_web_robot() -> Any:
    if not WEB_ROBOT_PATH.exists():
        raise RuntimeError(f"Could not load {WEB_ROBOT_PATH}")
    spec = importlib.util.spec_from_file_location("agilab_web_robot_for_widget_sweep", WEB_ROBOT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {WEB_ROBOT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Could not load {WEB_ROBOT_PATH}") from exc
    return module


def public_builtin_apps(apps_root: Path = DEFAULT_APPS_ROOT) -> list[Path]:
    return sorted(path.resolve() for path in apps_root.glob("*_project") if path.is_dir())


def _apps_page_entrypoint(project_dir: Path) -> Path | None:
    bundle = discover_page_bundle(project_dir.parent, project_dir.name)
    return bundle.script_path if bundle is not None else None


def public_apps_pages(pages_root: Path = DEFAULT_APPS_PAGES_ROOT) -> list[AppsPageRoute]:
    registry = discover_page_bundles(pages_root, require_pyproject=True)
    return [_apps_page_route(bundle) for bundle in registry]


def parse_csv(value: str) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for item in value.split(","):
        cleaned = item.strip()
        if not cleaned:
            continue
        variants = set(app_name_aliases(cleaned)) or {cleaned}
        if any(variant in seen for variant in variants):
            continue
        items.append(cleaned)
        seen.update(variants)
    return items


def _wait_for_timeout(page: Any, timeout_ms: float) -> None:
    wait = getattr(page, "wait_for_timeout", None)
    if callable(wait):
        wait(timeout_ms)


def resolve_apps(apps: str, *, apps_root: Path = DEFAULT_APPS_ROOT) -> list[Path | str]:
    if apps == "all":
        return public_builtin_apps(apps_root)
    resolved: list[Path | str] = []
    for item in parse_csv(apps):
        candidate = Path(item).expanduser()
        if candidate.exists():
            resolved.append(candidate.resolve())
        elif (apps_root / item).exists():
            resolved.append((apps_root / item).resolve())
        elif not item.endswith("_project") and (apps_root / f"{item}_project").exists():
            resolved.append((apps_root / f"{item}_project").resolve())
        else:
            resolved.append(item)
    return resolved


def resolve_pages(pages: str) -> list[str]:
    if pages == "none":
        return []
    if pages == "all":
        return list(DEFAULT_PAGES)
    return ["" if item.upper() == "HOME" else item for item in parse_csv(pages)]


def resolve_apps_pages(apps_pages: str, *, pages_root: Path = DEFAULT_APPS_PAGES_ROOT) -> list[AppsPageRoute]:
    if apps_pages == "configured":
        raise ValueError("'configured' apps-pages are resolved per app")
    if apps_pages == "none":
        return []
    if apps_pages == "all":
        return public_apps_pages(pages_root)
    bundles = resolve_page_bundles(parse_csv(apps_pages), pages_root=pages_root, require_pyproject=True)
    return [_apps_page_route(bundle) for bundle in bundles]


def configured_apps_pages_for_app(app: Path | str, *, pages_root: Path = DEFAULT_APPS_PAGES_ROOT) -> list[AppsPageRoute]:
    app_path = Path(app)
    settings_path = app_path / "src" / "app_settings.toml"
    if not settings_path.exists():
        return []
    try:
        settings = tomllib.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    registry = discover_page_bundles(pages_root, require_pyproject=True)
    return [_apps_page_route(bundle) for bundle in registry.select(configured_page_bundle_names(settings))]


def _apps_page_route(bundle: PageBundleSpec) -> AppsPageRoute:
    return AppsPageRoute(bundle.name, bundle.script_path)


def page_label(page: str) -> str:
    return page or "HOME"


def active_app_slug(active_app: str) -> str:
    decoded = urllib.parse.unquote(str(active_app)).rstrip("/")
    return Path(decoded).name if "/" in decoded else decoded


def active_app_runtime_target_name(active_app: str) -> str:
    return aliased_app_runtime_target(active_app_slug(active_app))


def normalize_remote_url(url: str) -> str:
    """Map public HF Space pages to the Streamlit runtime URL."""
    candidate = url.strip()
    if not urllib.parse.urlsplit(candidate).scheme:
        candidate = f"https://{candidate}"
    parsed = urllib.parse.urlsplit(candidate)
    path_parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
    if parsed.netloc == "huggingface.co" and len(path_parts) >= 3 and path_parts[0] == "spaces":
        owner = path_parts[1].lower().replace("_", "-")
        space = path_parts[2].lower().replace("_", "-")
        return urllib.parse.urlunsplit(("https", f"{owner}-{space}.hf.space", "/", parsed.query, parsed.fragment))
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, parsed.fragment))


def app_target_name(app_name: str) -> str:
    if app_name.endswith("_project"):
        return app_name[: -len("_project")]
    if app_name.endswith("_worker"):
        return app_name[: -len("_worker")]
    return app_name


def routed_active_app_slug(url: str) -> str | None:
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query, keep_blank_values=True))
    active_app = query.get("active_app")
    return active_app_slug(active_app) if active_app else None


def active_app_aliases(active_app: str) -> set[str]:
    slug = active_app_slug(active_app)
    return set(app_name_aliases(slug))


def active_app_route_matches(url: str, expected_active_app: str) -> bool:
    return routed_active_app_slug(url) in active_app_aliases(expected_active_app)


def remote_apps_page_path(route: AppsPageRoute, *, remote_app_root: str = "/app") -> str:
    try:
        relative_path = route.path.resolve().relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError(f"Cannot map apps-page outside repository to remote runtime: {route.path}") from exc
    return str(PurePosixPath(remote_app_root) / PurePosixPath(*relative_path.parts))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    columns = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _seed_track_dataframe(path: Path, *, node_prefix: str = "robot") -> None:
    rows: list[dict[str, Any]] = []
    for node_index, (lat0, lon0, alt0) in enumerate([(48.8566, 2.3522, 1100.0), (48.8584, 2.2945, 1200.0)], start=1):
        for step in range(4):
            rows.append(
                {
                    "flight_id": f"{node_prefix}_{node_index}",
                    "node_id": f"{node_prefix}_{node_index}",
                    "time_s": step,
                    "latitude": lat0 + step * 0.01,
                    "longitude": lon0 + step * 0.01,
                    "altitude": alt0 + step * 15.0,
                    "alt_m": alt0 + step * 15.0,
                    "role": "relay" if node_index == 2 else "source",
                }
            )
    _write_csv(path, rows)


def _seed_flight_artifacts(export_root: Path, share_root: Path) -> None:
    for base in (share_root, export_root):
        _seed_track_dataframe(base / "flight" / "dataframe" / "00_robot_flight.csv", node_prefix="flight")


def _queue_run_rows(policy: str, *, delivered_offset: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    queue_rows: list[dict[str, Any]] = []
    for time_s in range(5):
        queue_rows.extend(
            [
                {"time_s": time_s, "relay": "relay_a", "queue_depth_pkts": max(0, 4 - time_s + delivered_offset)},
                {"time_s": time_s, "relay": "relay_b", "queue_depth_pkts": max(0, 2 + time_s - delivered_offset)},
            ]
        )
    packet_rows = [
        {
            "packet_id": f"pkt_{idx}",
            "origin_kind": "source",
            "relay": "relay_a" if idx % 2 == 0 else "relay_b",
            "status": "delivered" if idx < 5 + delivered_offset else "dropped",
            "e2e_delay_ms": 18.0 + idx * 2.5,
            "queue_wait_ms": 4.0 + idx,
        }
        for idx in range(8)
    ]
    node_specs = [
        ("uav_source", "source", 48.8566, 2.3522, 1200.0),
        ("relay_a", "relay", 48.8666, 2.3722, 1300.0),
        ("relay_b", "relay", 48.8466, 2.3322, 1280.0),
        ("ground_sink", "sink", 48.8500, 2.3000, 40.0),
    ]
    position_rows = [
        {
            "time_s": time_s,
            "node": node,
            "node_id": node,
            "role": role,
            "latitude": lat0 + time_s * 0.003,
            "longitude": lon0 + time_s * 0.004,
            "alt_m": alt0,
            "y_m": time_s * (120 if node == "relay_a" else 90),
        }
        for time_s in range(5)
        for node, role, lat0, lon0, alt0 in node_specs
    ]
    routing_rows = [
        {
            "relay": relay,
            "routing_policy": policy,
            "packets_generated": 8,
            "packets_delivered": delivered,
            "packets_dropped": 8 - delivered,
        }
        for relay, delivered in (("relay_a", 5 + delivered_offset), ("relay_b", 4 + delivered_offset))
    ]
    return queue_rows, packet_rows, position_rows, routing_rows


def _write_queue_pipeline(run_root: Path, *, scenario: str) -> None:
    pipeline_dir = run_root / "pipeline"
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    (pipeline_dir / "topology.gml").write_text(
        """graph [
  directed 1
  node [ id 0 label "uav_source" role "source" latitude 48.8566 longitude 2.3522 alt_m 1200.0 ]
  node [ id 1 label "relay_a" role "relay" latitude 48.8666 longitude 2.3722 alt_m 1300.0 ]
  node [ id 2 label "relay_b" role "relay" latitude 48.8466 longitude 2.3322 alt_m 1280.0 ]
  node [ id 3 label "ground_sink" role "sink" latitude 48.8500 longitude 2.3000 alt_m 40.0 ]
  edge [ source 0 target 1 bearer "ivdl" weight 1.0 ]
  edge [ source 1 target 3 bearer "satcom" weight 1.2 ]
  edge [ source 0 target 2 bearer "ivdl" weight 1.1 ]
  edge [ source 2 target 3 bearer "satcom" weight 1.3 ]
]
""",
        encoding="utf-8",
    )
    _write_csv(
        pipeline_dir / "allocations_steps.csv",
        [
            {"time_index": 0, "source": "uav_source", "destination": "ground_sink", "path": '["uav_source", "relay_a", "ground_sink"]', "bearers": '["ivdl", "satcom"]'},
            {"time_index": 1, "source": "uav_source", "destination": "ground_sink", "path": '["uav_source", "relay_b", "ground_sink"]', "bearers": '["ivdl", "satcom"]'},
        ],
    )
    _write_json(pipeline_dir / "demands.json", [{"source": "uav_source", "destination": "ground_sink", "packet_rate_pps": 14.0}])
    trajectory_files: list[str] = []
    for node in ("uav_source", "relay_a", "relay_b", "ground_sink"):
        file_name = f"{node}_trajectory.csv"
        trajectory_files.append(file_name)
        _write_csv(
            pipeline_dir / file_name,
            [
                {
                    "time_s": step,
                    "node_id": node,
                    "latitude": 48.84 + step * 0.005,
                    "longitude": 2.30 + step * 0.006,
                    "alt_m": 40.0 if node == "ground_sink" else 1200.0 + step * 10.0,
                }
                for step in range(5)
            ],
        )
    _write_json(pipeline_dir / "_trajectory_summary.json", {"scenario": scenario, "planned_trajectories": len(trajectory_files), "trajectory_files": trajectory_files})


def _seed_queue_artifacts(export_root: Path, target: str) -> None:
    _seed_track_dataframe(export_root / "00_robot_tracks.csv", node_prefix=target)
    analysis_root = export_root / target / "queue_analysis"
    for stem, policy, delivered_offset in [
        ("robot_shortest_path_seed2026", "shortest_path", 0),
        ("robot_queue_aware_seed2026", "queue_aware", 1),
    ]:
        run_root = analysis_root / stem
        queue_rows, packet_rows, position_rows, routing_rows = _queue_run_rows(policy, delivered_offset=delivered_offset)
        _write_json(
            run_root / f"{stem}_summary_metrics.json",
            {
                "artifact_stem": stem,
                "scenario": "uav_queue_hotspot",
                "routing_policy": policy,
                "bond_mode": "single",
                "source_rate_pps": 14.0,
                "random_seed": 2026,
                "bottleneck_relay": "relay_a",
                "packets_generated": 8,
                "pdr": 0.72 + delivered_offset * 0.08,
                "mean_e2e_delay_ms": 30.0 - delivered_offset * 4.0,
                "mean_queue_wait_ms": 9.0 - delivered_offset * 2.0,
                "max_queue_depth_pkts": 6 - delivered_offset,
                "notes": "Seeded by the AGILAB widget robot for browser UI coverage.",
            },
        )
        _write_csv(run_root / f"{stem}_queue_timeseries.csv", queue_rows)
        _write_csv(run_root / f"{stem}_packet_events.csv", packet_rows)
        _write_csv(run_root / f"{stem}_node_positions.csv", position_rows)
        _write_csv(run_root / f"{stem}_routing_summary.csv", routing_rows)
        _write_queue_pipeline(run_root, scenario="uav_queue_hotspot")


def _seed_forecast_artifacts(export_root: Path) -> None:
    target_root = export_root / "meteo_forecast" / "forecast_analysis"
    for name, mae, rmse, mape, notes in [
        ("baseline", 3.4, 4.2, 7.5, "Baseline notebook export"),
        ("candidate", 2.9, 3.8, 6.4, "Candidate notebook export"),
    ]:
        run_root = target_root / name
        _write_json(
            run_root / "forecast_metrics.json",
            {
                "scenario": "paris_temperature_forecast",
                "station": "Paris-Montsouris",
                "target": "tmax_c",
                "model_name": "robot_random_forest",
                "horizon_days": 7,
                "mae": mae,
                "rmse": rmse,
                "mape": mape,
                "notes": notes,
            },
        )
        _write_csv(run_root / "forecast_predictions.csv", [{"date": f"2026-04-{day:02d}", "y_true": 17.0 + day * 0.2, "y_pred": 16.8 + day * 0.25} for day in range(1, 8)])


def seed_public_demo_artifacts(app_name: str, *, export_root: Path, share_root: Path) -> None:
    target = active_app_runtime_target_name(app_name)
    if target not in PUBLIC_APP_TARGETS_WITH_SEEDED_ARTIFACTS:
        return
    export_root.mkdir(parents=True, exist_ok=True)
    share_root.mkdir(parents=True, exist_ok=True)
    if target == "flight":
        _seed_flight_artifacts(export_root, share_root)
    elif target in {"uav_queue", "uav_relay_queue"}:
        _seed_queue_artifacts(export_root, target)
    elif target == "meteo_forecast":
        _seed_forecast_artifacts(export_root)


def build_seeded_server_env(
    web_robot: Any,
    *,
    app_name: str,
    runtime_root: Path,
    seed_demo_artifacts: bool,
    runtime_isolation: str = "isolated",
) -> SeededRuntime:
    env = web_robot.build_server_env()
    if runtime_isolation == "current-home":
        home_root = Path.home()
        export_root = Path(env.get("AGI_EXPORT_DIR") or home_root / "export")
        share_root = Path(env.get("AGI_LOCAL_SHARE") or home_root / "localshare")
        cluster_share_root = Path(env.get("AGI_CLUSTER_SHARE") or home_root / "clustershare")
        env["HOME"] = str(home_root)
    else:
        home_root = runtime_root / "home"
        export_root = runtime_root / "export"
        share_root = runtime_root / "localshare"
        cluster_share_root = runtime_root / "clustershare"
        for path in (home_root, export_root, share_root, cluster_share_root):
            path.mkdir(parents=True, exist_ok=True)
        env.update(
            {
                "HOME": str(home_root),
                "AGI_EXPORT_DIR": str(export_root),
                "AGI_LOCAL_SHARE": str(share_root),
                "AGI_CLUSTER_SHARE": str(cluster_share_root),
            }
        )
    env.update(
        {
            "AGI_CLUSTER_ENABLED": "0",
            "IS_SOURCE_ENV": "1",
        }
    )
    if seed_demo_artifacts:
        seed_public_demo_artifacts(app_name, export_root=export_root, share_root=share_root)
    return SeededRuntime(env, home_root, export_root, share_root, cluster_share_root)


def wait_for_page_ready(page: Any, *, timeout_ms: float) -> None:
    deadline = time.perf_counter() + timeout_ms / 1000.0
    while time.perf_counter() < deadline:
        try:
            text = page.locator("body").inner_text(timeout=1000).lower()
            spinner_count = page.locator("[data-testid='stSpinner']").count()
        except Exception:
            text = ""
            spinner_count = 0
        if "initializing environment" not in text and spinner_count == 0:
            page.wait_for_timeout(250)
            return
        page.wait_for_timeout(250)


def wait_for_widgets_ready(page: Any, *, page_name: str, timeout_ms: float) -> int:
    minimum = PAGE_MIN_WIDGETS.get(page_name, 1)
    deadline = time.perf_counter() + timeout_ms / 1000.0
    last_count = -1
    stable_seen = 0
    while time.perf_counter() < deadline:
        try:
            page.evaluate(OPEN_EXPANDERS_JS)
            count = len(page.evaluate(WIDGET_COLLECTOR_JS))
        except Exception:
            count = 0
        if count >= minimum and count == last_count:
            stable_seen += 1
            if stable_seen >= 2:
                return count
        else:
            stable_seen = 0
        last_count = count
        page.wait_for_timeout(500)
    return max(last_count, 0)


def _normalized_label(label: str) -> str:
    normalized = (
        label.replace("keyboard_arrow_right", "")
        .replace("keyboard_arrow_down", "")
        .replace("\u2192", "->")
        .replace("\u27f6", "->")
        .replace("\u21d2", "->")
        .replace("\u279c", "->")
        .strip()
        .lower()
    )
    return " ".join(normalized.split())


def _action_label_tokens(label: str) -> set[str]:
    cleaned = "".join(character if character.isalnum() else " " for character in _normalized_label(label))
    return {token for token in cleaned.split() if token}


def _action_label_has_safe_prefix(label: str) -> bool:
    normalized = _normalized_label(label).replace("_", " ").replace("-", " ")
    return any(normalized == prefix or normalized.startswith(f"{prefix} ") for prefix in SAFE_ACTION_LABEL_PREFIXES)


def safe_action_click_reason(widget: dict[str, Any]) -> str | None:
    kind = str(widget.get("kind", ""))
    label = str(widget.get("label", ""))
    if kind == "download_button":
        return "download buttons are read-only browser actions"
    tokens = _action_label_tokens(label)
    risky_tokens = tokens & RISKY_ACTION_LABEL_TOKENS
    if risky_tokens:
        return None
    if _action_label_has_safe_prefix(label):
        return "label matches guarded safe navigation/action prefix"
    if _normalized_label(label).startswith("view_"):
        return "label matches configured analysis view launcher"
    return None


def widget_scope(widget: dict[str, Any] | WidgetProbe) -> str:
    scope = getattr(widget, "scope", "") if isinstance(widget, WidgetProbe) else str(widget.get("scope", ""))
    return "sidebar" if scope == "sidebar" else "main"


def _widget_fingerprint(widget: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (widget_scope(widget), str(widget.get("kind", "")), _normalized_label(str(widget.get("label", ""))), str(widget.get("testid", "")), str(widget.get("path", "")))


def _same_widget(widget: dict[str, Any], candidate: dict[str, Any]) -> bool:
    if widget_scope(widget) != widget_scope(candidate):
        return False
    if str(widget.get("kind", "")) != str(candidate.get("kind", "")):
        return False
    label = _normalized_label(str(widget.get("label", "")))
    candidate_label = _normalized_label(str(candidate.get("label", "")))
    if label and candidate_label and (label == candidate_label or label in candidate_label or candidate_label in label):
        return True
    return bool(widget.get("testid") and widget.get("testid") == candidate.get("testid") and widget.get("path") == candidate.get("path"))


def _label_matches(widget: dict[str, Any], selected_labels: Sequence[str]) -> bool:
    label = _normalized_label(str(widget.get("label", "")))
    return any(
        selected and (selected == label or selected in label)
        for selected in (_normalized_label(item) for item in selected_labels)
    )


def _action_label_matches(widget: dict[str, Any], selected_labels: Sequence[str]) -> bool:
    return _label_matches(widget, selected_labels)


def _control_id_for_widget(widget: dict[str, Any], *, suffix: str = "") -> str:
    parts = [
        widget_scope(widget),
        str(widget.get("kind", "")),
        _normalized_label(str(widget.get("label", ""))) or str(widget.get("name", "")),
        str(widget.get("testid", "")),
        str(widget.get("path", "")),
        suffix,
    ]
    return ":".join(part for part in parts if part)


def _choice_label(widget: dict[str, Any], index: int) -> str:
    label = str(widget.get("label", "")).strip()
    value = str(widget.get("value", "")).strip()
    if label and value and value not in label:
        return f"{label}: {value}"
    if label:
        return label
    if value:
        return value
    return f"option {index + 1}"


def _choice_description(choice: WidgetChoice) -> str:
    if choice.kind in {"checkbox", "toggle"}:
        return f"{choice.label}={'on' if choice.checked else 'off'}"
    if choice.kind == "selectbox":
        return f"{choice.label}={choice.value}"
    return f"{choice.label}={choice.value or choice.kind}"


def _combination_description(combination: Sequence[WidgetChoice]) -> str:
    return ", ".join(_choice_description(choice) for choice in combination)


def _binary_widget_control(widget: dict[str, Any]) -> WidgetControl | None:
    kind = str(widget.get("kind", ""))
    if kind not in {"checkbox", "toggle"} or widget.get("disabled"):
        return None
    checked = bool(widget.get("checked"))
    control_id = _control_id_for_widget(widget)
    label = str(widget.get("label", "")) or control_id
    choices = (
        WidgetChoice(control_id, kind, label, "off", dict(widget), checked=False, default=not checked),
        WidgetChoice(control_id, kind, label, "on", dict(widget), checked=True, default=checked),
    )
    return WidgetControl(control_id, kind, label, choices)


def _radio_group_key(widget: dict[str, Any]) -> tuple[str, str, str]:
    name = str(widget.get("name", "")).strip()
    if name:
        return (widget_scope(widget), "name", name)
    return (widget_scope(widget), "label", _normalized_label(str(widget.get("label", ""))))


def collect_static_widget_combination_controls(widgets: Sequence[dict[str, Any]]) -> list[WidgetControl]:
    controls: list[WidgetControl] = []
    radio_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for widget in widgets:
        kind = str(widget.get("kind", ""))
        if kind in {"checkbox", "toggle"}:
            control = _binary_widget_control(widget)
            if control is not None:
                controls.append(control)
        elif kind == "radio" and not widget.get("disabled"):
            radio_groups.setdefault(_radio_group_key(widget), []).append(widget)

    for key, group in radio_groups.items():
        if len(group) < 2:
            continue
        checked_present = any(bool(widget.get("checked")) for widget in group)
        control_id = ":".join(("main" if key[0] != "sidebar" else "sidebar", "radio", key[1], key[2]))
        label = str(group[0].get("label", "")) or key[2] or control_id
        choices = tuple(
            WidgetChoice(
                control_id,
                "radio",
                label,
                str(widget.get("value", "")) or _choice_label(widget, index),
                dict(widget),
                checked=True,
                default=bool(widget.get("checked")) or (not checked_present and index == 0),
            )
            for index, widget in enumerate(group)
        )
        controls.append(WidgetControl(control_id, "radio", label, choices))
    return controls


def build_widget_combination_plan(controls: Sequence[WidgetControl], *, max_combinations: int) -> WidgetCombinationPlan:
    if max_combinations <= 0:
        raise ValueError("max_combinations must be greater than 0")
    valid_controls = tuple(control for control in controls if control.choices)
    if not valid_controls:
        return WidgetCombinationPlan((), 0, ())
    total_count = 1
    for control in valid_controls:
        total_count *= len(control.choices)
    combinations = tuple(tuple(combo) for combo in itertools.islice(itertools.product(*(control.choices for control in valid_controls)), max_combinations))
    return WidgetCombinationPlan(valid_controls, total_count, combinations, truncated=total_count > max_combinations)


def _option_locator(page: Any) -> Any:
    return page.locator("[role='option']")


def _selectbox_option_labels(
    page: Any,
    widget: dict[str, Any],
    *,
    timeout_ms: float,
    max_options_per_widget: int,
) -> tuple[list[str], str | None]:
    locator = _widget_locator(page, widget)
    try:
        locator.scroll_into_view_if_needed(timeout=timeout_ms)
        _click_with_force_fallback(locator, timeout_ms=timeout_ms)
        page.wait_for_timeout(150)
        options = _option_locator(page)
        count = options.count()
        if count <= 0:
            page.keyboard.press("Escape")
            return [], "no selectbox options found after opening"
        labels: list[str] = []
        for index in range(min(count, max_options_per_widget)):
            text = options.nth(index).inner_text(timeout=timeout_ms).strip()
            labels.append(text or f"option {index + 1}")
        page.keyboard.press("Escape")
        if count > max_options_per_widget:
            return labels, f"selectbox has {count} options; capped at --max-options-per-widget {max_options_per_widget}"
        return labels, None
    except Exception as exc:
        try:
            page.keyboard.press("Escape")
        except Exception:
            logger.debug("Unable to close selectbox options after enumeration failure", exc_info=True)
        return [], _short_detail(f"could not enumerate selectbox options: {exc}")


def _selectbox_widget_control(
    page: Any,
    widget: dict[str, Any],
    *,
    app_name: str,
    page_name: str,
    timeout_ms: float,
    max_options_per_widget: int,
) -> tuple[WidgetControl | None, WidgetProbe | None]:
    if widget.get("disabled"):
        return None, None
    if is_project_switching_widget(widget):
        return None, None
    labels, issue = _selectbox_option_labels(page, widget, timeout_ms=timeout_ms, max_options_per_widget=max_options_per_widget)
    issue_probe = None
    if issue is not None:
        status = "skipped" if labels else "failed"
        issue_probe = WidgetProbe(app_name, page_label(page_name), "selectbox_options", str(widget.get("label", "")), status, issue, page.url, widget_scope(widget))
    if not labels:
        return None, issue_probe
    control_id = _control_id_for_widget(widget)
    label = str(widget.get("label", "")) or control_id
    choices = tuple(
        WidgetChoice(
            control_id,
            "selectbox",
            label,
            option_label,
            dict(widget),
            option_index=index,
            default=index == 0,
        )
        for index, option_label in enumerate(labels)
    )
    return WidgetControl(control_id, "selectbox", label, choices), issue_probe


def is_project_switching_widget(widget: dict[str, Any]) -> bool:
    """Return whether a widget changes the globally active AGILAB project."""
    label = _normalized_label(str(widget.get("label", "")))
    return widget_scope(widget) == "sidebar" and label.startswith("project ")


def collect_widget_combination_controls(
    page: Any,
    widgets: Sequence[dict[str, Any]],
    *,
    app_name: str,
    page_name: str,
    timeout_ms: float,
    max_options_per_widget: int,
) -> tuple[list[WidgetControl], list[WidgetProbe]]:
    del page, app_name, page_name, timeout_ms, max_options_per_widget
    # Keep exhaustive combinations on stable controls only. AGILAB pages use
    # many dependent selectboxes whose option lists legitimately change after
    # another widget is selected; putting those in a Cartesian product produces
    # stale-option false positives instead of useful UI regressions.
    controls = collect_static_widget_combination_controls(widgets)
    return controls, []


def _short_detail(detail: str, *, limit: int = 500) -> str:
    return detail if len(detail) <= limit else detail[: limit - 3] + "..."


def _parse_config_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", ""}:
            return False
    return None


def _strip_config_value(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def _load_dotenv_map(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            stripped = raw.strip()
            if not stripped or "=" not in stripped:
                continue
            key, value = stripped.lstrip("#").strip().split("=", 1)
            key = key.strip()
            if key:
                values[key] = _strip_config_value(value)
    except OSError:
        pass
    return values


def _read_cluster_enabled_setting(path: Path) -> bool | None:
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return None
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    cluster = data.get("cluster")
    if isinstance(cluster, dict) and "cluster_enabled" in cluster:
        return _parse_config_bool(cluster.get("cluster_enabled"))
    return None


def _source_app_settings_path(active_app_query: Path | str) -> Path | None:
    try:
        app_path = Path(str(active_app_query)).expanduser()
    except (TypeError, ValueError):
        return None
    if not app_path.exists():
        return None
    candidates = [app_path / "src" / "app_settings.toml", app_path / "app_settings.toml"]
    if app_path.name == "src":
        candidates.insert(0, app_path / "app_settings.toml")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _current_home_cluster_enabled(
    *,
    app_name: str,
    active_app_query: Path | str,
    home_root: Path,
    server_env: dict[str, str],
    env_values: dict[str, str],
) -> bool:
    settings_candidates = [
        home_root / ".agilab" / "apps" / app_name / "app_settings.toml",
        _source_app_settings_path(active_app_query),
    ]
    for settings_path in settings_candidates:
        if settings_path is None:
            continue
        parsed = _read_cluster_enabled_setting(settings_path)
        if parsed is not None:
            return parsed
    parsed = _parse_config_bool(env_values.get("AGI_CLUSTER_ENABLED"))
    if parsed is None:
        parsed = _parse_config_bool(server_env.get("AGI_CLUSTER_ENABLED"))
    return bool(parsed) if parsed is not None else False


def _home_relative_path(value: str, *, home_root: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = home_root / path
    return path


def _is_writable_directory(path: Path) -> bool:
    if not path.is_dir():
        return False
    probe = path / ".agilab_widget_robot_mount_test"
    try:
        os.listdir(path)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _same_configured_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(os.path.normpath(str(right)))


def _current_home_preflight_action_requested(click_action_labels: Sequence[str]) -> bool:
    selected = [_normalized_label(label) for label in click_action_labels if _normalized_label(label)]
    required = [_normalized_label(label) for label in CURRENT_HOME_PREFLIGHT_ACTION_LABELS]
    return any(
        expected == label or expected in label or label in expected
        for label in selected
        for expected in required
    )


def _current_home_worker_import_preflight_requested(click_action_labels: Sequence[str]) -> bool:
    selected = [_normalized_label(label) for label in click_action_labels if _normalized_label(label)]
    required = [_normalized_label(label) for label in CURRENT_HOME_WORKER_IMPORT_PREFLIGHT_ACTION_LABELS]
    return any(
        expected == label or expected in label or label in expected
        for label in selected
        for expected in required
    )


def _worker_python_import_command(worker_root: Path, worker_package: str) -> list[str]:
    uv_bin = shutil.which("uv") or "uv"
    probe = (
        "import importlib, sys\n"
        "module = sys.argv[1]\n"
        "importlib.import_module(module)\n"
        "print(f'import-ok:{module}')\n"
    )
    return [
        uv_bin,
        "--quiet",
        "run",
        "--no-sync",
        "--project",
        str(worker_root),
        "python",
        "-c",
        probe,
        worker_package,
    ]


def _current_home_worker_import_issue(
    *,
    app_name: str,
    home_root: Path,
) -> str | None:
    target = active_app_runtime_target_name(app_name)
    worker_package = f"{target}_worker"
    worker_root = home_root / "wenv" / worker_package
    if not worker_root.is_dir():
        return (
            f"installed worker project is missing: {worker_root}. "
            f"Run INSTALL for {app_name} before running backend ORCHESTRATE actions."
        )

    command = _worker_python_import_command(worker_root, worker_package)
    try:
        result = subprocess.run(
            command,
            cwd=worker_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=CURRENT_HOME_WORKER_IMPORT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        return f"unable to run worker import probe because `uv` was not found: {exc}"
    except subprocess.TimeoutExpired as exc:
        return (
            f"worker import probe timed out after {CURRENT_HOME_WORKER_IMPORT_TIMEOUT_SECONDS:.1f}s "
            f"for {worker_package}: {exc}"
        )

    if result.returncode == 0:
        return None

    detail = "\n".join(
        part.strip()
        for part in (result.stderr, result.stdout)
        if part and part.strip()
    )
    if not detail:
        detail = f"exit code {result.returncode}"
    return (
        f"installed worker project failed import probe: {worker_root}. "
        f"Module `{worker_package}` could not be imported with the current worker environment. "
        f"{_short_detail(detail, limit=900)}"
    )


def current_home_action_preflight_blocker(
    *,
    app_name: str,
    active_app_query: Path | str,
    page_name: str,
    action_button_policy: str,
    click_action_labels: Sequence[str],
    runtime_isolation: str,
    server_env: dict[str, str] | None,
    home_root: Path | None,
) -> str | None:
    if runtime_isolation != "current-home":
        return None
    if page_label(page_name) != "ORCHESTRATE":
        return None
    if action_button_policy != "click-selected" or not _current_home_preflight_action_requested(click_action_labels):
        return None
    home = home_root or Path.home()
    env = dict(server_env or {})
    env_file = home / ".agilab" / ".env"
    env_values = _load_dotenv_map(env_file)
    cluster_enabled = _current_home_cluster_enabled(
        app_name=app_name,
        active_app_query=active_app_query,
        home_root=home,
        server_env=env,
        env_values=env_values,
    )

    if cluster_enabled:
        cluster_share = _strip_config_value(env_values.get("AGI_CLUSTER_SHARE") or env.get("AGI_CLUSTER_SHARE") or str(home / "clustershare"))
        local_share = _strip_config_value(env_values.get("AGI_LOCAL_SHARE") or env.get("AGI_LOCAL_SHARE") or str(home / "localshare"))
        cluster_path = _home_relative_path(cluster_share, home_root=home)
        local_path = _home_relative_path(local_share, home_root=home)
        if _same_configured_path(cluster_path, local_path):
            return (
                "environment_blocked: current-home ORCHESTRATE selected actions were not clicked because "
                f"cluster mode is enabled for {app_name} but AGI_CLUSTER_SHARE and AGI_LOCAL_SHARE both resolve "
                f"to {cluster_path}. Set AGI_CLUSTER_SHARE to a distinct mounted shared path, or disable "
                f"cluster mode in {home / '.agilab' / 'apps' / app_name / 'app_settings.toml'}."
            )
        if not _is_writable_directory(cluster_path):
            return (
                "environment_blocked: current-home ORCHESTRATE selected actions were not clicked because "
                f"cluster mode is enabled for {app_name} but AGI_CLUSTER_SHARE={str(cluster_path)!r} is not a "
                f"writable directory. Mount/create that path or disable cluster mode in "
                f"{home / '.agilab' / 'apps' / app_name / 'app_settings.toml'} before rerunning the UI robot. "
                f"env={env_file}"
            )
    if _current_home_worker_import_preflight_requested(click_action_labels):
        worker_issue = _current_home_worker_import_issue(app_name=app_name, home_root=home)
        if worker_issue is not None:
            return (
                "environment_blocked: current-home ORCHESTRATE selected actions were not clicked because "
                f"the installed worker environment for {app_name} is not ready. {worker_issue} "
                "Run INSTALL, then rerun the UI robot before manual RUN / LOAD / EXPORT validation."
            )
    return None


def _artifact_env_path(
    key: str,
    *,
    home_root: Path,
    server_env: dict[str, str] | None,
    env_values: dict[str, str],
    default: Path,
) -> Path:
    raw = _strip_config_value(env_values.get(key) or (server_env or {}).get(key) or str(default))
    return _home_relative_path(raw, home_root=home_root)


def build_orchestrate_artifact_context(
    *,
    app_name: str,
    active_app_query: Path | str,
    home_root: Path | None,
    server_env: dict[str, str] | None,
) -> OrchestrateArtifactContext:
    home = home_root or Path.home()
    env_values = _load_dotenv_map(home / ".agilab" / ".env")
    return OrchestrateArtifactContext(
        app_name=app_name,
        active_app_query=str(active_app_query),
        home_root=home,
        export_root=_artifact_env_path("AGI_EXPORT_DIR", home_root=home, server_env=server_env, env_values=env_values, default=home / "export"),
        share_root=_artifact_env_path("AGI_LOCAL_SHARE", home_root=home, server_env=server_env, env_values=env_values, default=home / "localshare"),
        cluster_share_root=_artifact_env_path("AGI_CLUSTER_SHARE", home_root=home, server_env=server_env, env_values=env_values, default=home / "clustershare"),
    )


def build_workflow_artifact_context(
    *,
    app_name: str,
    active_app_query: Path | str,
    home_root: Path | None,
    server_env: dict[str, str] | None,
) -> WorkflowArtifactContext:
    home = home_root or Path.home()
    env_values = _load_dotenv_map(home / ".agilab" / ".env")
    raw_export_root = _strip_config_value(
        (server_env or {}).get("AGI_EXPORT_DIR")
        or env_values.get("AGI_EXPORT_DIR")
        or str(home / "export")
    )
    return WorkflowArtifactContext(
        app_name=app_name,
        active_app_query=str(active_app_query),
        home_root=home,
        export_root=_home_relative_path(raw_export_root, home_root=home),
    )


def _load_app_settings_args_for_artifact_context(context: OrchestrateArtifactContext) -> dict[str, Any]:
    candidates = [
        context.home_root / ".agilab" / "apps" / context.app_name / "app_settings.toml",
        _source_app_settings_path(context.active_app_query),
    ]
    for settings_path in candidates:
        if settings_path is None or not settings_path.is_file():
            continue
        try:
            payload = tomllib.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        args = payload.get("args")
        return dict(args) if isinstance(args, dict) else {}
    return {}


def _artifact_path_from_configured_value(raw_path: Any, *, roots: Sequence[Path]) -> list[Path]:
    if not raw_path:
        return []
    path = Path(str(raw_path)).expanduser()
    if path.is_absolute():
        return [path]
    return [root / path for root in roots]


def _unique_paths(paths: Sequence[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = os.path.normcase(os.path.normpath(str(path)))
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _orchestrate_output_roots(context: OrchestrateArtifactContext) -> list[Path]:
    target = active_app_runtime_target_name(context.app_name)
    share_roots = [context.share_root, context.cluster_share_root]
    args = _load_app_settings_args_for_artifact_context(context)
    candidates: list[Path] = []
    candidates.extend(_artifact_path_from_configured_value(args.get("data_out"), roots=share_roots))
    for root in [*share_roots, context.export_root]:
        for dirname in ORCHESTRATE_FALLBACK_OUTPUT_DIRS:
            candidates.append(root / target / dirname)
    return _unique_paths(candidates)


def _orchestrate_export_roots(context: OrchestrateArtifactContext) -> list[Path]:
    target = active_app_runtime_target_name(context.app_name)
    return _unique_paths([context.export_root / target])


def _is_orchestrate_preview_file(path: Path) -> bool:
    name = path.name
    if name in ORCHESTRATE_PREVIEW_METADATA_FILENAMES:
        return False
    if any(name.startswith(prefix) for prefix in ORCHESTRATE_PREVIEW_METADATA_PREFIXES):
        return False
    return path.suffix.lower() in ORCHESTRATE_PREVIEW_FILE_SUFFIXES


def _snapshot_artifact_files(roots: Sequence[Path], *, include_trash: bool = False) -> ArtifactFileSnapshot:
    files: dict[Path, tuple[int, int]] = {}
    for root in roots:
        if root.is_file():
            candidates = [root]
        elif root.is_dir():
            candidates = []
            for suffix in ORCHESTRATE_PREVIEW_FILE_SUFFIXES:
                candidates.extend(root.rglob(f"*{suffix}"))
        else:
            continue
        for candidate in sorted(candidates, key=lambda path: str(path)):
            if not include_trash and ".agilab-trash" in candidate.parts:
                continue
            if not _is_orchestrate_preview_file(candidate):
                continue
            try:
                stat = candidate.stat()
            except (FileNotFoundError, OSError):
                continue
            if stat.st_size <= 0:
                continue
            files[candidate] = (stat.st_mtime_ns, stat.st_size)
    return ArtifactFileSnapshot(files=files)


def _changed_artifact_files(before: ArtifactFileSnapshot, after: ArtifactFileSnapshot) -> set[Path]:
    return {
        path
        for path, metadata in after.files.items()
        if before.files.get(path) != metadata
    }


def _deleted_artifact_files(before: ArtifactFileSnapshot, after: ArtifactFileSnapshot) -> set[Path]:
    return {path for path in before.files if path not in after.files}


def _artifact_probe(
    context: Any,
    *,
    display: str,
    label: str,
    status: str,
    detail: str,
    url: str,
) -> WidgetProbe:
    return WidgetProbe(
        context.app_name,
        display,
        "artifact_side_effect",
        label,
        status,
        _short_detail(detail),
        url,
    )


def _snapshot_specific_files(paths: Sequence[Path], *, require_non_empty: bool = False) -> ArtifactFileSnapshot:
    files: dict[Path, tuple[int, int]] = {}
    for path in paths:
        try:
            raw_candidate = path.expanduser()
        except (TypeError, ValueError):
            continue
        candidates = [raw_candidate]
        try:
            resolved_candidate = raw_candidate.resolve(strict=False)
        except (OSError, RuntimeError):
            resolved_candidate = raw_candidate
        if resolved_candidate != raw_candidate:
            candidates.append(resolved_candidate)
        for candidate in candidates:
            try:
                stat = candidate.stat()
            except (FileNotFoundError, OSError):
                continue
            if not candidate.is_file():
                continue
            if require_non_empty and stat.st_size <= 0:
                continue
            files[candidate] = (stat.st_mtime_ns, stat.st_size)
    return ArtifactFileSnapshot(files=files)


def _workflow_source_stage_contract_path(context: WorkflowArtifactContext) -> Path | None:
    active_app_path = Path(context.active_app_query).expanduser()
    candidates = [
        active_app_path / WORKFLOW_STAGE_CONTRACT_FILENAME,
        DEFAULT_APPS_ROOT / context.app_name / WORKFLOW_STAGE_CONTRACT_FILENAME,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _workflow_export_stage_contract_paths(context: WorkflowArtifactContext, *, url: str = "") -> list[Path]:
    target = active_app_runtime_target_name(context.app_name)
    candidates = [
        context.export_root / target / WORKFLOW_STAGE_CONTRACT_FILENAME,
        context.export_root / active_app_slug(context.app_name) / WORKFLOW_STAGE_CONTRACT_FILENAME,
    ]
    try:
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query, keep_blank_values=True))
    except (AttributeError, TypeError, ValueError):
        query = {}
    index_page = str(query.get("index_page") or "").strip()
    if index_page and Path(index_page).name == WORKFLOW_STAGE_CONTRACT_FILENAME:
        candidate = Path(index_page)
        if not candidate.is_absolute():
            candidate = context.export_root / candidate
        candidates.insert(0, candidate)
    return _unique_paths(candidates)


def _workflow_run_log_roots(context: WorkflowArtifactContext) -> list[Path]:
    target = active_app_runtime_target_name(context.app_name)
    return _unique_paths(
        [
            context.home_root / "log" / "execute" / target,
            context.home_root / "log" / "execute" / context.app_name,
        ]
    )


def _snapshot_workflow_run_logs(context: WorkflowArtifactContext) -> ArtifactFileSnapshot:
    paths: list[Path] = []
    for root in _workflow_run_log_roots(context):
        if root.is_file():
            paths.append(root)
        elif root.is_dir():
            paths.extend(sorted(root.rglob("*.log"), key=lambda path: str(path)))
    return _snapshot_specific_files(paths)


def _workflow_stage_contract_is_versioned(path: Path) -> tuple[bool, str]:
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        return False, f"stage contract is not readable TOML: {exc}"
    meta = payload.get("__meta__")
    if not isinstance(meta, dict):
        return False, "stage contract is missing __meta__ table"
    if meta.get("schema") != WORKFLOW_STAGE_CONTRACT_SCHEMA:
        return False, f"stage contract schema is {meta.get('schema')!r}, expected {WORKFLOW_STAGE_CONTRACT_SCHEMA!r}"
    return True, "stage contract is versioned"


def validate_workflow_page_artifacts(
    *,
    context: WorkflowArtifactContext,
    display: str,
    url: str,
) -> list[WidgetProbe]:
    source = _workflow_source_stage_contract_path(context)
    if source is None:
        return []

    target_candidates = _workflow_export_stage_contract_paths(context, url=url)
    snapshot = _snapshot_specific_files(target_candidates, require_non_empty=True)
    candidate_realpaths = {os.path.realpath(str(candidate)) for candidate in target_candidates}
    target = next((path for path in snapshot.files if os.path.realpath(str(path)) in candidate_realpaths), None)
    if target is None:
        checked = ", ".join(str(path) for path in target_candidates)
        return [
            _artifact_probe(
                context,
                display=display,
                label=WORKFLOW_STAGE_CONTRACT_FILENAME,
                status="failed",
                detail=f"source workflow stages exist at {source}, but exported stage contract was not restored; checked {checked}",
                url=url,
            )
        ]

    ok, detail = _workflow_stage_contract_is_versioned(target)
    if not ok:
        return [
            _artifact_probe(
                context,
                display=display,
                label=WORKFLOW_STAGE_CONTRACT_FILENAME,
                status="failed",
                detail=f"{detail}: {target}",
                url=url,
            )
        ]

    return [
        _artifact_probe(
            context,
            display=display,
            label=WORKFLOW_STAGE_CONTRACT_FILENAME,
            status="interacted",
            detail=f"workflow stage contract restored and versioned at {target}",
            url=url,
        )
    ]


def validate_workflow_action_artifacts(
    *,
    context: WorkflowArtifactContext,
    display: str,
    selected_label: str,
    before_logs: ArtifactFileSnapshot,
    url: str,
) -> list[WidgetProbe]:
    selected = _normalized_label(selected_label)
    if selected not in WORKFLOW_RUN_ACTION_LABELS:
        return []

    after_logs = _snapshot_workflow_run_logs(context)
    changed = _changed_artifact_files(before_logs, after_logs)
    if not changed:
        roots = ", ".join(str(path) for path in _workflow_run_log_roots(context))
        return [
            _artifact_probe(
                context,
                display=display,
                label=selected_label,
                status="failed",
                detail=f"workflow run completed without creating or modifying a run log; checked {roots}",
                url=url,
            )
        ]
    return [
        _artifact_probe(
            context,
            display=display,
            label=selected_label,
            status="interacted",
            detail=f"workflow run log side effect verified ({len(changed)} changed file(s))",
            url=url,
        )
    ]


def validate_orchestrate_action_artifacts(
    *,
    context: OrchestrateArtifactContext,
    display: str,
    selected_label: str,
    before_output: ArtifactFileSnapshot,
    before_export: ArtifactFileSnapshot,
    before_trash: ArtifactFileSnapshot,
    url: str,
) -> list[WidgetProbe]:
    selected = _normalized_label(selected_label)
    if (
        context.app_name in NO_OUTPUT_ORCHESTRATE_JOURNEY_APPS
        and selected in ORCHESTRATE_OUTPUT_ACTION_LABELS
    ):
        return []

    probes: list[WidgetProbe] = []
    output_roots = _orchestrate_output_roots(context)
    export_roots = _orchestrate_export_roots(context)

    if selected in ORCHESTRATE_OUTPUT_SIDE_EFFECT_LABELS:
        after_output = _snapshot_artifact_files(output_roots)
        if not after_output.files:
            roots = ", ".join(str(path) for path in output_roots[:4])
            probes.append(
                _artifact_probe(
                    context,
                    display=display,
                    label=selected_label,
                    status="failed",
                    detail=f"no loadable output artifact found after action; checked {roots}",
                    url=url,
                )
            )
        elif selected == "run -> load -> export" and not _changed_artifact_files(before_output, after_output):
            probes.append(
                _artifact_probe(
                    context,
                    display=display,
                    label=selected_label,
                    status="failed",
                    detail="output artifacts existed, but none were created or modified by Run -> Load -> Export",
                    url=url,
                )
            )
        else:
            probes.append(
                _artifact_probe(
                    context,
                    display=display,
                    label=selected_label,
                    status="interacted",
                    detail=f"output artifact side effect verified ({len(after_output.files)} file(s))",
                    url=url,
                )
            )

    if selected in ORCHESTRATE_EXPORT_SIDE_EFFECT_LABELS:
        after_export = _snapshot_artifact_files(export_roots)
        changed = _changed_artifact_files(before_export, after_export)
        if not after_export.files:
            roots = ", ".join(str(path) for path in export_roots[:4])
            probes.append(
                _artifact_probe(
                    context,
                    display=display,
                    label=selected_label,
                    status="failed",
                    detail=f"export artifact was not found after action; checked {roots}",
                    url=url,
                )
            )
        elif selected == "run -> load -> export" and not changed:
            probes.append(
                _artifact_probe(
                    context,
                    display=display,
                    label=selected_label,
                    status="failed",
                    detail="export artifact existed, but was not created or modified by Run -> Load -> Export",
                    url=url,
                )
            )
        else:
            detail = (
                f"export artifact side effect verified ({len(changed)} changed file(s))"
                if changed
                else f"export artifact availability verified ({len(after_export.files)} file(s))"
            )
            probes.append(
                _artifact_probe(
                    context,
                    display=display,
                    label=selected_label,
                    status="interacted",
                    detail=detail,
                    url=url,
                )
            )

    if selected in ORCHESTRATE_DELETE_SIDE_EFFECT_LABELS:
        after_output = _snapshot_artifact_files(output_roots)
        after_trash = _snapshot_artifact_files(output_roots, include_trash=True)
        deleted = _deleted_artifact_files(before_output, after_output)
        trashed = _changed_artifact_files(before_trash, after_trash)
        if not deleted and not trashed:
            probes.append(
                _artifact_probe(
                    context,
                    display=display,
                    label=selected_label,
                    status="failed",
                    detail="confirm delete completed, but no output file disappeared and no .agilab-trash backup changed",
                    url=url,
                )
            )
        else:
            detail = (
                f"delete side effect verified ({len(deleted)} removed file(s), "
                f"{len(trashed)} trash file(s) changed)"
            )
            probes.append(
                _artifact_probe(
                    context,
                    display=display,
                    label=selected_label,
                    status="interacted",
                    detail=detail,
                    url=url,
                )
            )
    return probes


def _callable_or_value(obj: Any, name: str, default: str = "") -> str:
    value = getattr(obj, name, default)
    try:
        if callable(value):
            value = value()
    except Exception:
        return default
    return str(value or default)


def _browser_issue_is_relevant(kind: str, detail: str) -> bool:
    lower = f"{kind} {detail}".lower()
    if any(needle in lower for needle in BROWSER_ISSUE_IGNORE_NEEDLES):
        return False
    if kind == "pageerror":
        return True
    return any(needle in lower for needle in BROWSER_ISSUE_FATAL_NEEDLES)


def _record_browser_issue(issues: list[dict[str, str]], *, kind: str, detail: str) -> None:
    cleaned = _short_detail(" ".join(str(detail or "").split()))
    if not cleaned or not _browser_issue_is_relevant(kind, cleaned):
        return
    signature = (kind, cleaned)
    if any((item.get("kind"), item.get("detail")) == signature for item in issues):
        return
    issues.append({"kind": kind, "detail": cleaned})


def _attach_browser_issue_capture(page: Any) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []

    def _on_console(message: Any) -> None:
        msg_type = _callable_or_value(message, "type", "log").lower()
        if msg_type not in {"error", "warning"}:
            return
        _record_browser_issue(
            issues,
            kind=f"console.{msg_type}",
            detail=_callable_or_value(message, "text", ""),
        )

    def _on_page_error(error: Any) -> None:
        _record_browser_issue(issues, kind="pageerror", detail=str(error))

    try:
        page.on("console", _on_console)
    except Exception:
        logger.debug("Unable to attach console issue capture", exc_info=True)
    try:
        page.on("pageerror", _on_page_error)
    except Exception:
        logger.debug("Unable to attach pageerror issue capture", exc_info=True)
    return issues


def _append_browser_issue_probes(
    probes: list[WidgetProbe],
    *,
    app_name: str,
    display: str,
    url: str,
    browser_issues: Sequence[dict[str, str]] | None,
    start_index: int,
) -> bool:
    if not browser_issues:
        return False
    appended = False
    seen: set[tuple[str, str]] = set()
    for issue in list(browser_issues)[start_index:]:
        kind = str(issue.get("kind") or "browser")
        detail = str(issue.get("detail") or "browser issue")
        signature = (kind, detail)
        if signature in seen:
            continue
        seen.add(signature)
        if not _browser_issue_is_relevant(kind, detail):
            continue
        probes.append(
            WidgetProbe(
                app_name,
                display,
                "browser_error",
                kind,
                "failed",
                _short_detail(detail),
                url,
            )
        )
        appended = True
    return appended


def _widget_locator(page: Any, widget: dict[str, Any], *, force_refresh: bool = False) -> Any:
    locator = page.locator(f"[data-agilab-widget-id='{widget['id']}']").first
    if not force_refresh:
        try:
            if locator.count() > 0:
                return locator
        except Exception:
            return locator
    refreshed = page.evaluate(WIDGET_COLLECTOR_JS)
    for candidate in refreshed:
        if _widget_fingerprint(candidate) == _widget_fingerprint(widget) or _same_widget(widget, candidate):
            widget["id"] = candidate["id"]
            return page.locator(f"[data-agilab-widget-id='{widget['id']}']").first
    return locator


def _button_locator_by_label(page: Any, label: str) -> Any | None:
    if not hasattr(page, "get_by_role"):
        return None
    try:
        locator = page.get_by_role("button", name=re.compile(re.escape(label), re.IGNORECASE))
    except TypeError:
        try:
            locator = page.get_by_role("button", name=label)
        except Exception:
            logger.debug("Unable to locate button by exact label %r", label, exc_info=True)
            return None
    except Exception:
        logger.debug("Unable to locate button by regex label %r", label, exc_info=True)
        return None
    try:
        count = locator.count()
    except Exception:
        logger.debug("Unable to count button candidates for label %r", label, exc_info=True)
        return getattr(locator, "first", locator)
    if count <= 0:
        return None
    for index in range(min(count, 20)):
        try:
            candidate = locator.nth(index)
            if candidate.is_visible(timeout=500):
                return candidate
        except Exception:
            logger.debug("Unable to inspect button candidate %s for label %r", index, label, exc_info=True)
            continue
    return locator.first
    return None


def _page_scroll_positions(page: Any) -> list[int]:
    try:
        metrics = page.evaluate(SCROLL_METRICS_JS)
    except Exception:
        return [0]
    if not isinstance(metrics, dict):
        return [0]
    height = max(int(float(metrics.get("height") or 1000)), 1)
    scroll_height = max(int(float(metrics.get("scrollHeight") or height)), height)
    if scroll_height <= height:
        return [0]
    step = max(int(height * 0.8), 400)
    positions = list(range(0, max(scroll_height - height, 0) + 1, step))
    positions.append(max(scroll_height - height, 0))
    return sorted(set(positions))


def _scroll_to(page: Any, y: int) -> None:
    try:
        page.evaluate("targetY => window.scrollTo(0, targetY)", y)
    except TypeError:
        page.evaluate(f"() => window.scrollTo(0, {int(y)})")
    except Exception:
        logger.debug("Unable to scroll page to %s", y, exc_info=True)
        return


def _visible_streamlit_issue_detail(page: Any) -> str | None:
    try:
        issues = page.evaluate(VISIBLE_STREAMLIT_ISSUE_COLLECTOR_JS)
    except Exception:
        logger.debug("Unable to evaluate visible Streamlit issue collector", exc_info=True)
        return None
    if not isinstance(issues, list) or not issues:
        return None
    first = issues[0] if isinstance(issues[0], dict) else {}
    kind = str(first.get("kind") or "issue")
    detail = str(first.get("detail") or "visible Streamlit issue rendered")
    suffix = f" (+{len(issues) - 1} more)" if len(issues) > 1 else ""
    return _short_detail(f"{kind}: {detail}{suffix}")


def _visible_streamlit_feedback(page: Any, *, include_action_logs: bool = True) -> list[dict[str, str]]:
    feedback_items: list[Any] = []
    scripts = [VISIBLE_STREAMLIT_FEEDBACK_COLLECTOR_JS]
    if include_action_logs:
        scripts.append(ACTION_LOG_FEEDBACK_COLLECTOR_JS)
    for script in scripts:
        try:
            feedback = page.evaluate(script)
        except Exception:
            logger.debug("Unable to evaluate visible Streamlit feedback collector", exc_info=True)
            continue
        if isinstance(feedback, list):
            feedback_items.extend(feedback)
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in feedback_items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "info")
        detail = str(item.get("detail") or "visible Streamlit alert rendered")
        signature = (kind, detail)
        if signature in seen:
            continue
        seen.add(signature)
        normalized.append({"kind": kind, "detail": detail})
    return normalized


def _visible_streamlit_feedback_signatures(page: Any) -> set[tuple[str, str]]:
    return {(item["kind"], item["detail"]) for item in _visible_streamlit_feedback(page)}


def _new_visible_streamlit_feedback(
    page: Any,
    baseline_feedback: set[tuple[str, str]],
) -> dict[str, str] | None:
    candidates: list[dict[str, str]] = []
    for item in _visible_streamlit_feedback(page):
        if (item["kind"], item["detail"]) not in baseline_feedback:
            candidates.append(item)
    if not candidates:
        return None
    for kind in ("error", "exception", "success", "warning", "info"):
        for item in candidates:
            if item["kind"] == kind:
                return item
    return candidates[0]


def _visible_exception_detail(page: Any) -> str | None:
    """Backward-compatible alias for older tests and call sites."""
    try:
        exceptions = page.locator("[data-testid='stException']")
        if exceptions.count() > 0 and exceptions.first.is_visible(timeout=500):
            return _short_detail(exceptions.first.inner_text(timeout=500) or "Streamlit exception rendered")
    except Exception:
        logger.debug("Unable to inspect rendered Streamlit exception", exc_info=True)
    return _visible_streamlit_issue_detail(page)


def _append_visible_streamlit_issue_probe(
    probes: list[WidgetProbe],
    *,
    page: Any,
    app_name: str,
    display: str,
) -> bool:
    issue = _visible_streamlit_issue_detail(page)
    if not issue:
        return False
    probes.append(
        WidgetProbe(
            app_name,
            display,
            "visible_error",
            "",
            "failed",
            f"visible Streamlit error message: {issue}",
            getattr(page, "url", ""),
        )
    )
    return True


def _append_missing_selected_action_probes(
    probes: list[WidgetProbe],
    *,
    app_name: str,
    display: str,
    url: str,
    click_action_labels: Sequence[str],
    missing_selected_action_policy: str = "fail",
) -> None:
    for selected_label in click_action_labels:
        selected = _normalized_label(selected_label)
        if not selected:
            continue
        matching_probes = [
            probe
            for probe in probes
            if probe.kind in ACTION_BUTTON_KINDS and selected in _normalized_label(probe.label)
        ]
        if any(probe.status in {"interacted", "failed"} for probe in matching_probes):
            continue
        if not matching_probes and missing_selected_action_policy == "ignore-absent":
            continue
        detail = "selected action button was not found in the swept page"
        if matching_probes:
            states = ", ".join(f"{probe.status}: {probe.detail}" for probe in matching_probes[:3])
            detail = f"selected action button was found but not fired ({states})"
        probes.append(
            WidgetProbe(
                app_name,
                display,
                "selected_action",
                selected_label,
                "failed",
                detail,
                url,
            )
        )


def _preselect_matching_widgets(
    page: Any,
    *,
    app_name: str,
    display: str,
    widgets: Sequence[dict[str, Any]],
    timeout_ms: float,
    preselect_labels: Sequence[str],
) -> list[WidgetProbe]:
    if not preselect_labels:
        return []
    probes: list[WidgetProbe] = []
    for widget in widgets:
        kind = str(widget.get("kind", ""))
        if kind not in CHOICE_BUTTON_KINDS and kind != "radio":
            continue
        if not _label_matches(widget, preselect_labels):
            continue
        try:
            locator = _widget_locator(page, widget)
            locator.scroll_into_view_if_needed(timeout=timeout_ms)
            if locator.is_visible(timeout=timeout_ms) and locator.is_enabled(timeout=timeout_ms):
                _click_with_force_fallback(locator, timeout_ms=timeout_ms)
                _wait_for_timeout(page, 500)
                probes.append(
                    WidgetProbe(
                        app_name,
                        display,
                        kind,
                        str(widget.get("label", "")),
                        "interacted",
                        "preselected before selected action",
                        page.url,
                        widget_scope(widget),
                    )
                )
        except Exception as exc:
            probes.append(
                WidgetProbe(
                    app_name,
                    display,
                    kind,
                    str(widget.get("label", "")),
                    "skipped",
                    _short_detail(f"preselection skipped: {exc}"),
                    page.url,
                    widget_scope(widget),
                )
            )
    return probes


def _close_all_expanders(page: Any) -> None:
    try:
        page.evaluate(CLOSE_EXPANDERS_JS)
        _wait_for_timeout(page, 150)
    except Exception:
        logger.debug("Unable to close Streamlit expanders", exc_info=True)


def _open_all_expanders(page: Any) -> None:
    try:
        page.evaluate(OPEN_EXPANDERS_JS)
        _wait_for_timeout(page, 250)
    except Exception:
        logger.debug("Unable to open Streamlit expanders", exc_info=True)


def _selected_action_matches(
    widgets: Sequence[dict[str, Any]],
    selected_label: str,
    *,
    require_enabled: bool = False,
) -> list[dict[str, Any]]:
    selected = _normalized_label(selected_label)
    if not selected:
        return []
    return [
        widget
        for widget in widgets
        if str(widget.get("kind", "")) in ACTION_BUTTON_KINDS
        and selected in _normalized_label(str(widget.get("label", "")))
        and (not require_enabled or not bool(widget.get("disabled", False)))
    ]


def _probe_selected_actions_first(
    page: Any,
    *,
    app_name: str,
    display: str,
    widget_timeout_ms: float,
    click_action_labels: Sequence[str],
    preselect_labels: Sequence[str],
    missing_selected_action_policy: str,
    action_timeout_ms: float,
    upload_file: Path,
    orchestrate_artifact_context: OrchestrateArtifactContext | None = None,
    workflow_artifact_context: WorkflowArtifactContext | None = None,
) -> list[WidgetProbe]:
    def refresh_widgets() -> list[dict[str, Any]]:
        wait_for_page_ready(page, timeout_ms=widget_timeout_ms)
        wait_for_widgets_ready(page, page_name=display, timeout_ms=widget_timeout_ms)
        _wait_for_timeout(page, 1000)
        wait_for_page_ready(page, timeout_ms=widget_timeout_ms)
        _close_all_expanders(page)
        return page.evaluate(WIDGET_COLLECTOR_JS)

    probes: list[WidgetProbe] = []
    _close_all_expanders(page)
    widgets = page.evaluate(WIDGET_COLLECTOR_JS)
    if preselect_labels and not any(
        str(widget.get("kind", "")) in CHOICE_BUTTON_KINDS | {"radio"} and _label_matches(widget, preselect_labels)
        for widget in widgets
    ):
        _open_all_expanders(page)
        widgets = page.evaluate(WIDGET_COLLECTOR_JS)
    probes.extend(
        _preselect_matching_widgets(
            page,
            app_name=app_name,
            display=display,
            widgets=widgets,
            timeout_ms=widget_timeout_ms,
            preselect_labels=preselect_labels,
        )
    )
    if probes:
        widgets = refresh_widgets()

    for index, selected_label in enumerate(click_action_labels):
        if not _normalized_label(selected_label):
            continue
        matches = _selected_action_matches(widgets, selected_label)
        if not matches:
            _open_all_expanders(page)
            wait_for_page_ready(page, timeout_ms=widget_timeout_ms)
            expanded_widgets = page.evaluate(WIDGET_COLLECTOR_JS)
            matches = _selected_action_matches(expanded_widgets, selected_label)
        if not matches:
            if missing_selected_action_policy == "fail":
                probes.append(
                    WidgetProbe(
                        app_name,
                        display,
                        "selected_action",
                        selected_label,
                        "failed",
                        "selected action button was not found in the swept page",
                        page.url,
                    )
                )
            continue
        widget = matches[0]
        selected_normalized = _normalized_label(selected_label)
        future_already_ready = any(
            _selected_action_matches(widgets, candidate, require_enabled=True)
            for candidate in click_action_labels[index + 1 :]
            if _normalized_label(candidate)
        )
        next_settle_labels = [
            candidate
            for candidate in click_action_labels[index + 1 :]
            if _normalized_label(candidate)
            and not _selected_action_matches(widgets, candidate, require_enabled=True)
        ]
        allow_idle_settle = selected_normalized in TERMINAL_IDLE_SETTLE_ACTION_LABELS or (
            future_already_ready and selected_normalized in {"export dataframe", "load output"}
        )
        if orchestrate_artifact_context is not None:
            output_roots = _orchestrate_output_roots(orchestrate_artifact_context)
            export_roots = _orchestrate_export_roots(orchestrate_artifact_context)
            before_output = _snapshot_artifact_files(output_roots)
            before_export = _snapshot_artifact_files(export_roots)
            before_trash = _snapshot_artifact_files(output_roots, include_trash=True)
        else:
            before_output = ArtifactFileSnapshot(files={})
            before_export = ArtifactFileSnapshot(files={})
            before_trash = ArtifactFileSnapshot(files={})
        before_workflow_logs = (
            _snapshot_workflow_run_logs(workflow_artifact_context)
            if workflow_artifact_context is not None
            else ArtifactFileSnapshot(files={})
        )
        status, detail = _probe_widget(
            page,
            widget,
            timeout_ms=widget_timeout_ms,
            interaction_mode="full",
            action_button_policy="click-selected",
            click_action_labels=[selected_label],
            preselect_labels=(),
            action_timeout_ms=action_timeout_ms,
            upload_file=upload_file,
            restore_view=None,
            settle_action_labels=next_settle_labels[:1],
            allow_idle_settle=allow_idle_settle,
        )
        if (
            app_name in NO_OUTPUT_ORCHESTRATE_JOURNEY_APPS
            and selected_normalized in ORCHESTRATE_OUTPUT_ACTION_LABELS
            and (status == "skipped" or (status == "probed" and "disabled state" in detail))
        ):
            status = "probed"
            detail = "output action not required for this placeholder app; no concrete output is expected"
        elif (
            workflow_artifact_context is not None
            and selected_normalized in WORKFLOW_RUN_ACTION_LABELS
            and _workflow_source_stage_contract_path(workflow_artifact_context) is None
            and (status == "skipped" or (status == "probed" and "disabled state" in detail))
        ):
            status = "probed"
            detail = "workflow run action not required; this app does not declare lab_stages.toml"
        elif status == "skipped" or (status == "probed" and "disabled state" in detail):
            status = "failed"
            detail = f"selected action button was found but not fired ({detail})"
        probes.append(
            WidgetProbe(
                app_name,
                display,
                str(widget.get("kind", "")),
                str(widget.get("label", "")),
                status,
                detail,
                page.url,
                widget_scope(widget),
            )
        )
        if status != "failed" and orchestrate_artifact_context is not None:
            artifact_probes = validate_orchestrate_action_artifacts(
                context=orchestrate_artifact_context,
                display=display,
                selected_label=selected_label,
                before_output=before_output,
                before_export=before_export,
                before_trash=before_trash,
                url=page.url,
            )
            probes.extend(artifact_probes)
            if any(probe.status == "failed" for probe in artifact_probes):
                break
        if status != "failed" and workflow_artifact_context is not None:
            artifact_probes = validate_workflow_action_artifacts(
                context=workflow_artifact_context,
                display=display,
                selected_label=selected_label,
                before_logs=before_workflow_logs,
                url=page.url,
            )
            probes.extend(artifact_probes)
            if any(probe.status == "failed" for probe in artifact_probes):
                break
        if status == "failed":
            break
        if (
            app_name in NO_OUTPUT_ORCHESTRATE_JOURNEY_APPS
            and selected_normalized in ORCHESTRATE_OUTPUT_ACTION_LABELS
            and "output action not required" in detail
        ):
            break
        if (
            workflow_artifact_context is not None
            and selected_normalized in WORKFLOW_RUN_ACTION_LABELS
            and "workflow run action not required" in detail
        ):
            break
        else:
            widgets = refresh_widgets()
    return probes


def _fill_and_restore(locator: Any, value: str, *, timeout_ms: float) -> None:
    original = locator.input_value(timeout=timeout_ms)
    locator.fill(f"{original} robot" if original else value, timeout=timeout_ms)
    locator.fill(original, timeout=timeout_ms)


def _click_with_force_fallback(locator: Any, *, timeout_ms: float) -> None:
    try:
        locator.click(timeout=timeout_ms)
    except Exception:
        locator.click(timeout=timeout_ms, force=True)


def _robot_upload_fixture_for_widget(upload_file: Path, widget: dict[str, Any]) -> Path:
    label = str(widget.get("label") or "").lower()
    if "ipynb" in label or "notebook" in label:
        notebook_path = upload_file.with_suffix(".ipynb")
        if not notebook_path.exists():
            notebook_path.write_text(
                json.dumps(
                    {
                        "cells": [],
                        "metadata": {},
                        "nbformat": 4,
                        "nbformat_minor": 5,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
        return notebook_path
    if "json" in label:
        json_path = upload_file.with_suffix(".json")
        if not json_path.exists():
            json_path.write_text("{}\n", encoding="utf-8")
        return json_path
    if "csv" in label:
        csv_path = upload_file.with_suffix(".csv")
        if not csv_path.exists():
            csv_path.write_text("value\nagilab-widget-robot\n", encoding="utf-8")
        return csv_path
    return upload_file


def _close_expanders_except_widget(page: Any, widget: dict[str, Any]) -> None:
    try:
        page.evaluate(CLOSE_EXPANDERS_EXCEPT_WIDGET_JS, str(widget.get("id") or ""))
        _wait_for_timeout(page, 150)
    except Exception:
        logger.debug("Unable to close non-target expanders for widget %s", widget.get("id"), exc_info=True)


def _scroll_widget_to_center(page: Any, widget: dict[str, Any]) -> None:
    try:
        page.evaluate(SCROLL_WIDGET_TO_CENTER_JS, str(widget.get("id") or ""))
        _wait_for_timeout(page, 100)
    except Exception:
        logger.debug("Unable to center widget %s", widget.get("id"), exc_info=True)


def _visible_spinner_count(page: Any) -> int:
    try:
        return int(page.locator("[data-testid='stSpinner']").count())
    except Exception:
        return 0


def _wait_for_action_outcome(
    page: Any,
    *,
    timeout_ms: float,
    require_feedback: bool = False,
    baseline_feedback: set[tuple[str, str]] | None = None,
    settle_action_labels: Sequence[str] = (),
    allow_idle_settle: bool = False,
) -> tuple[str | None, bool]:
    start = time.perf_counter()
    timeout_seconds = timeout_ms / 1000.0
    deadline = start + timeout_seconds
    min_observation_deadline = start + min(5.0, timeout_seconds)
    busy_seen = False
    soft_feedback_seen = False
    idle_seen = 0
    baseline_feedback = set(baseline_feedback or ())
    while True:
        try:
            page.evaluate(OPEN_EXPANDERS_JS)
        except Exception:
            logger.debug("Unable to keep expanders open while waiting for action outcome", exc_info=True)
        issue = _visible_streamlit_issue_detail(page)
        if issue:
            return issue, True
        if require_feedback:
            feedback = _new_visible_streamlit_feedback(page, baseline_feedback)
            if feedback is not None:
                kind = feedback["kind"]
                detail = feedback["detail"]
                if kind in {"error", "exception"}:
                    return _short_detail(f"{kind}: {detail}"), True
                if kind == "success":
                    return None, True
                soft_feedback_seen = True
        if _visible_spinner_count(page) > 0:
            busy_seen = True
            idle_seen = 0
        elif settle_action_labels:
            try:
                widgets = page.evaluate(WIDGET_COLLECTOR_JS)
            except Exception:
                widgets = []
            settle_ready = any(
                _selected_action_matches(widgets, label, require_enabled=True)
                for label in settle_action_labels
            )
            if settle_ready and (
                busy_seen
                or soft_feedback_seen
                or allow_idle_settle
                or time.perf_counter() >= min_observation_deadline
            ):
                return None, True
            if require_feedback and soft_feedback_seen and allow_idle_settle:
                idle_seen += 1
                if time.perf_counter() >= min_observation_deadline:
                    return None, True
            elif require_feedback and allow_idle_settle and time.perf_counter() >= min_observation_deadline:
                return None, True
        elif busy_seen and not require_feedback:
            idle_seen += 1
            if idle_seen >= 3:
                return None, True
        elif require_feedback and soft_feedback_seen and allow_idle_settle:
            idle_seen += 1
            if time.perf_counter() >= min_observation_deadline:
                return None, True
        elif require_feedback and allow_idle_settle and time.perf_counter() >= min_observation_deadline:
            return None, True
        elif not require_feedback and time.perf_counter() >= min_observation_deadline:
            return None, True
        now = time.perf_counter()
        if now >= deadline:
            if require_feedback and allow_idle_settle and (
                soft_feedback_seen or now >= min_observation_deadline
            ):
                return None, True
            return None, False
        _wait_for_timeout(page, min(250, max(10, (deadline - now) * 1000.0)))


def _locator_checked(locator: Any, *, timeout_ms: float) -> bool | None:
    try:
        return bool(locator.is_checked(timeout=timeout_ms))
    except Exception:
        logger.debug("Unable to read locator checked state directly", exc_info=True)
    try:
        aria_checked = locator.get_attribute("aria-checked", timeout=timeout_ms)
    except Exception:
        logger.debug("Unable to read locator aria-checked state", exc_info=True)
        return None
    if aria_checked == "true":
        return True
    if aria_checked == "false":
        return False
    return None


def _apply_widget_choice(page: Any, choice: WidgetChoice, *, timeout_ms: float) -> None:
    locator = _widget_locator(page, dict(choice.widget))
    locator.scroll_into_view_if_needed(timeout=timeout_ms)
    if not locator.is_visible(timeout=timeout_ms):
        raise RuntimeError(f"{choice.kind} {choice.label!r} is not visible")
    if not locator.is_enabled(timeout=timeout_ms):
        raise RuntimeError(f"{choice.kind} {choice.label!r} is not enabled")
    if choice.kind in {"checkbox", "toggle"}:
        current = _locator_checked(locator, timeout_ms=timeout_ms)
        if current is None or current != choice.checked:
            _click_with_force_fallback(locator, timeout_ms=timeout_ms)
            page.wait_for_timeout(150)
        return
    if choice.kind == "radio":
        current = _locator_checked(locator, timeout_ms=timeout_ms)
        if current is not True:
            _click_with_force_fallback(locator, timeout_ms=timeout_ms)
            page.wait_for_timeout(150)
        return
    if choice.kind == "selectbox":
        if choice.option_index is None:
            raise RuntimeError(f"selectbox {choice.label!r} has no option index")
        _click_with_force_fallback(locator, timeout_ms=timeout_ms)
        page.wait_for_timeout(150)
        options = _option_locator(page)
        if options.count() <= choice.option_index:
            raise RuntimeError(f"selectbox {choice.label!r} option {choice.option_index + 1} is not available")
        options.nth(choice.option_index).click(timeout=timeout_ms)
        page.wait_for_timeout(250)
        return
    raise RuntimeError(f"unsupported combination widget kind: {choice.kind}")


def _combination_probe(
    *,
    app_name: str,
    page_name: str,
    kind: str,
    label: str,
    status: str,
    detail: str,
    url: str,
) -> WidgetProbe:
    return WidgetProbe(app_name, page_label(page_name), kind, label, status, _short_detail(detail), url)


def _consume_action_click_budget(action_click_budget: list[int] | None) -> bool:
    if action_click_budget is None:
        return True
    if not action_click_budget or action_click_budget[0] <= 0:
        return False
    action_click_budget[0] -= 1
    return True


def _probe_action_button_trial(locator: Any, *, timeout_ms: float, detail: str) -> tuple[str, str]:
    try:
        locator.click(timeout=timeout_ms, trial=True)
        return "probed", detail
    except Exception as exc:
        return "probed", _short_detail(f"{detail}; trial click layout-intercepted: {exc}")


def _probe_widget(
    page: Any,
    widget: dict[str, Any],
    *,
    timeout_ms: float,
    interaction_mode: str,
    action_button_policy: str,
    click_action_labels: Sequence[str] = (),
    preselect_labels: Sequence[str] = (),
    action_timeout_ms: float = DEFAULT_ACTION_TIMEOUT_SECONDS * 1000.0,
    upload_file: Path,
    restore_view: Any | None,
    settle_action_labels: Sequence[str] = (),
    allow_idle_settle: bool = False,
    action_click_budget: list[int] | None = None,
) -> tuple[str, str]:
    if widget.get("disabled"):
        return "probed", "disabled state verified"
    locator = _widget_locator(page, widget)
    kind = str(widget.get("kind", ""))
    is_selected_action = (
        kind in ACTION_BUTTON_KINDS
        and action_button_policy == "click-selected"
        and _action_label_matches(widget, click_action_labels)
    )
    try:
        locator.scroll_into_view_if_needed(timeout=timeout_ms)
        if not locator.is_visible(timeout=timeout_ms):
            if is_selected_action:
                _open_all_expanders(page)
                locator = _widget_locator(page, widget, force_refresh=True)
                locator.scroll_into_view_if_needed(timeout=timeout_ms)
                _scroll_widget_to_center(page, widget)
                locator = _widget_locator(page, widget)
                if not locator.is_visible(timeout=timeout_ms):
                    role_locator = _button_locator_by_label(page, str(widget.get("label", "")))
                    if role_locator is not None:
                        role_locator.scroll_into_view_if_needed(timeout=timeout_ms)
                        if role_locator.is_visible(timeout=timeout_ms):
                            locator = role_locator
                if not locator.is_visible(timeout=timeout_ms):
                    return "skipped", "not visible after collection"
            else:
                if preselect_labels:
                    return "probed", "widget became hidden after compact-choice preselection; refreshed view was swept"
                if kind == "expander":
                    return "probed", "expander header became hidden after collection; expanded content was still swept"
                if kind == "data_editor":
                    return "probed", "data editor became hidden after collection; visible table content was still detected"
                return "skipped", "not visible after collection"
        if not locator.is_visible(timeout=timeout_ms):
            if preselect_labels:
                return "probed", "widget became hidden after compact-choice preselection; refreshed view was swept"
            if kind == "expander":
                return "probed", "expander header became hidden after collection; expanded content was still swept"
            if kind == "data_editor":
                return "probed", "data editor became hidden after collection; visible table content was still detected"
            return "skipped", "not visible after collection"
        if not locator.is_enabled(timeout=timeout_ms):
            return "skipped", "not enabled"
        locator.bounding_box(timeout=timeout_ms)
        if interaction_mode == "actionability":
            if kind in ACTION_BUTTON_KINDS:
                try:
                    locator.click(timeout=timeout_ms, trial=True)
                except Exception:
                    logger.debug("Actionability trial click failed for %s", widget.get("label"), exc_info=True)
            return "probed", f"visible/enabled ok ({kind})"
        if kind in ACTION_BUTTON_KINDS:
            safe_click_reason = safe_action_click_reason(widget)
            should_click = action_button_policy == "click" or (
                action_button_policy == "click-selected" and _action_label_matches(widget, click_action_labels)
            ) or (
                action_button_policy == "safe-click" and safe_click_reason is not None
            )
            if should_click:
                if not _consume_action_click_budget(action_click_budget):
                    return _probe_action_button_trial(
                        locator,
                        timeout_ms=timeout_ms,
                        detail="action button browser-clickable; callback not fired because action click budget is exhausted",
                    )
                require_feedback = action_button_policy == "click-selected"
                _close_expanders_except_widget(page, widget)
                if require_feedback:
                    _open_all_expanders(page)
                locator = _widget_locator(page, widget, force_refresh=require_feedback)
                locator.scroll_into_view_if_needed(timeout=timeout_ms)
                _scroll_widget_to_center(page, widget)
                locator = _widget_locator(page, widget, force_refresh=require_feedback)
                if require_feedback:
                    role_locator = _button_locator_by_label(page, str(widget.get("label", "")))
                    if role_locator is not None and role_locator.is_visible(timeout=timeout_ms):
                        locator = role_locator
                baseline_feedback = _visible_streamlit_feedback_signatures(page) if require_feedback else set()
                if require_feedback:
                    click_timeout_ms = max(timeout_ms, min(action_timeout_ms, 10000.0))
                    try:
                        locator.click(timeout=click_timeout_ms)
                    except Exception:
                        role_locator = _button_locator_by_label(page, str(widget.get("label", "")))
                        if role_locator is None:
                            raise
                        role_locator.scroll_into_view_if_needed(timeout=timeout_ms)
                        role_locator.click(timeout=click_timeout_ms)
                else:
                    _click_with_force_fallback(locator, timeout_ms=timeout_ms)
                error, settled = _wait_for_action_outcome(
                    page,
                    timeout_ms=action_timeout_ms,
                    require_feedback=require_feedback,
                    baseline_feedback=baseline_feedback,
                    settle_action_labels=settle_action_labels,
                    allow_idle_settle=allow_idle_settle,
                )
                if error:
                    return "failed", f"button click rendered Streamlit error: {error}"
                if not settled:
                    return "skipped", f"clicked action button but UI did not settle within {action_timeout_ms / 1000.0:.1f}s"
                if action_button_policy == "safe-click":
                    return "interacted", f"clicked guarded safe action button: {safe_click_reason}"
                return "interacted", "clicked action button"
            if action_button_policy == "safe-click":
                return _probe_action_button_trial(
                    locator,
                    timeout_ms=timeout_ms,
                    detail="action button browser-clickable; callback not fired by guarded safe-click policy",
                )
            if action_button_policy == "click-selected":
                return _probe_action_button_trial(
                    locator,
                    timeout_ms=timeout_ms,
                    detail="action button browser-clickable; callback not selected for firing",
                )
            return _probe_action_button_trial(
                locator,
                timeout_ms=timeout_ms,
                detail="action button browser-clickable; callback not fired by default",
            )
        if kind in CHOICE_BUTTON_KINDS:
            if _label_matches(widget, preselect_labels):
                _click_with_force_fallback(locator, timeout_ms=timeout_ms)
                _wait_for_timeout(page, 500)
                return "interacted", "selected compact choice"
            locator.click(timeout=timeout_ms, trial=True)
            return "probed", "compact choice browser-clickable; callback not selected for firing"
        if kind in {"checkbox", "toggle"}:
            was_checked = locator.is_checked(timeout=timeout_ms) if kind == "checkbox" else None
            _click_with_force_fallback(locator, timeout_ms=timeout_ms)
            _wait_for_timeout(page, 250)
            if was_checked is not None:
                locator = _widget_locator(page, widget)
                if locator.is_checked(timeout=timeout_ms) != was_checked:
                    _click_with_force_fallback(locator, timeout_ms=timeout_ms)
            return "interacted", f"clicked and restored {kind}"
        if kind == "radio":
            if preselect_labels and not _label_matches(widget, preselect_labels):
                locator.click(timeout=timeout_ms, trial=True)
                return "probed", "radio option browser-clickable; callback not selected for firing"
            _click_with_force_fallback(locator, timeout_ms=timeout_ms)
            _wait_for_timeout(page, 250)
            if restore_view is not None:
                restore_view()
            return "interacted", "clicked radio option and restored page"
        if kind == "text_input":
            _fill_and_restore(locator, "agilab-widget-robot", timeout_ms=timeout_ms)
            return "interacted", "filled and restored text input"
        if kind == "text_area":
            _fill_and_restore(locator, "agilab widget robot", timeout_ms=timeout_ms)
            return "interacted", "filled and restored text area"
        if kind == "number_input":
            locator.focus(timeout=timeout_ms)
            locator.press("ArrowUp", timeout=timeout_ms)
            locator.press("ArrowDown", timeout=timeout_ms)
            return "interacted", "exercised number input keyboard controls"
        if kind == "slider":
            locator.focus(timeout=timeout_ms)
            locator.press("ArrowRight", timeout=timeout_ms)
            locator.press("ArrowLeft", timeout=timeout_ms)
            return "interacted", "exercised slider keyboard controls"
        if kind in {"selectbox", "multiselect"}:
            _click_with_force_fallback(locator, timeout_ms=timeout_ms)
            _wait_for_timeout(page, 150)
            page.keyboard.press("Escape")
            return "interacted", f"opened and closed {kind}"
        if kind == "file_uploader":
            fixture = _robot_upload_fixture_for_widget(upload_file, widget)
            locator.locator("input[type='file']").first.set_input_files(str(fixture), timeout=timeout_ms)
            _wait_for_timeout(page, 250)
            return "interacted", f"uploaded temporary robot fixture ({fixture.suffix})"
        if kind == "data_editor":
            _click_with_force_fallback(locator, timeout_ms=timeout_ms)
            return "interacted", "focused data editor/dataframe region"
        if kind in {"tab", "expander"}:
            _click_with_force_fallback(locator, timeout_ms=timeout_ms)
            _wait_for_timeout(page, 250)
            return "interacted", f"clicked {kind}"
        locator.click(timeout=timeout_ms, trial=True)
        return "probed", f"unknown widget kind actionability verified ({kind})"
    except Exception as exc:
        return "skipped", _short_detail(f"volatile after collection: {exc}")


def _collect_and_probe_current_view(
    page: Any,
    *,
    app_name: str,
    page_name: str,
    widget_timeout_ms: float,
    interaction_mode: str,
    action_button_policy: str,
    click_action_labels: Sequence[str] = (),
    preselect_labels: Sequence[str] = (),
    action_timeout_ms: float = DEFAULT_ACTION_TIMEOUT_SECONDS * 1000.0,
    upload_file: Path,
    restore_view: Any | None,
    known: set[tuple[str, str, str, str, str]],
    page_deadline: float | None = None,
    discovery_passes: int = 1,
    action_click_budget: list[int] | None = None,
) -> list[WidgetProbe]:
    probes: list[WidgetProbe] = []
    for _ in range(max(1, discovery_passes)):
        _enforce_page_deadline(page_deadline, "page watchdog expired before widget discovery")
        page.evaluate(OPEN_EXPANDERS_JS)
        widgets = page.evaluate(WIDGET_COLLECTOR_JS)
        discovered_count = 0
        for widget in widgets:
            _enforce_page_deadline(page_deadline, "page watchdog expired while probing widgets")
            fingerprint = _widget_fingerprint(widget)
            if fingerprint in known:
                continue
            known.add(fingerprint)
            discovered_count += 1
            status, detail = _probe_widget(
                page,
                widget,
                timeout_ms=widget_timeout_ms,
                interaction_mode=interaction_mode,
                action_button_policy=action_button_policy,
                click_action_labels=click_action_labels,
                preselect_labels=preselect_labels,
                action_timeout_ms=action_timeout_ms,
                upload_file=upload_file,
                restore_view=restore_view,
                action_click_budget=action_click_budget,
            )
            if status == "skipped" and "volatile after collection" in detail and restore_view is not None:
                try:
                    _enforce_page_deadline(page_deadline, "page watchdog expired before restore retry")
                    restore_view()
                    status, detail = _probe_widget(
                        page,
                        widget,
                        timeout_ms=widget_timeout_ms,
                        interaction_mode=interaction_mode,
                        action_button_policy=action_button_policy,
                        click_action_labels=click_action_labels,
                        preselect_labels=preselect_labels,
                        action_timeout_ms=action_timeout_ms,
                        upload_file=upload_file,
                        restore_view=restore_view,
                        action_click_budget=action_click_budget,
                    )
                except Exception as exc:
                    status, detail = "skipped", _short_detail(f"restore retry failed: {exc}")
            error = _visible_streamlit_issue_detail(page)
            if error and status != "failed":
                status, detail = "failed", f"interaction rendered Streamlit error: {error}"
            probes.append(
                WidgetProbe(
                    app_name,
                    page_label(page_name),
                    str(widget.get("kind", "")),
                    str(widget.get("label", "")),
                    status,
                    detail,
                    page.url,
                    widget_scope(widget),
                )
            )
        if discovered_count == 0:
            break
    return probes


def _exercise_widget_combinations(
    page: Any,
    *,
    app_name: str,
    page_name: str,
    widget_timeout_ms: float,
    interaction_mode: str,
    action_button_policy: str,
    upload_file: Path,
    restore_view: Any,
    known: set[tuple[str, str, str, str, str]],
    max_combinations: int,
    max_options_per_widget: int,
    discovery_passes: int,
    action_click_budget: list[int] | None,
) -> tuple[int, int, int, int, list[WidgetProbe]]:
    probes: list[WidgetProbe] = []
    try:
        restore_view()
        page.evaluate(OPEN_EXPANDERS_JS)
        widgets = page.evaluate(WIDGET_COLLECTOR_JS)
        controls, setup_probes = collect_widget_combination_controls(
            page,
            widgets,
            app_name=app_name,
            page_name=page_name,
            timeout_ms=widget_timeout_ms,
            max_options_per_widget=max_options_per_widget,
        )
        probes.extend(setup_probes)
        plan = build_widget_combination_plan(controls, max_combinations=max_combinations)
    except Exception as exc:
        return (
            0,
            0,
            1,
            0,
            [
                _combination_probe(
                    app_name=app_name,
                    page_name=page_name,
                    kind="combination_setup",
                    label="widget state model",
                    status="failed",
                    detail=f"could not build widget combination plan: {exc}",
                    url=page.url,
                )
            ],
        )

    setup_failed = sum(1 for probe in probes if probe.status == "failed")
    setup_skipped = sum(1 for probe in probes if probe.status == "skipped")
    if plan.total_count == 0:
        return 0, 0, setup_failed, setup_skipped, probes

    failed_count = setup_failed
    skipped_count = setup_skipped
    if plan.truncated:
        failed_count += 1
        probes.append(
            _combination_probe(
                app_name=app_name,
                page_name=page_name,
                kind="combination_space",
                label="finite widget state grid",
                status="failed",
                detail=f"combination space {plan.total_count} exceeds --max-combinations {max_combinations}; first {len(plan.combinations)} combinations were attempted",
                url=page.url,
            )
        )

    executed_count = 0
    for index, combination in enumerate(plan.combinations, start=1):
        detail = _combination_description(combination)
        try:
            restore_view()
            for choice in combination:
                _apply_widget_choice(page, choice, timeout_ms=widget_timeout_ms)
            page.wait_for_timeout(250)
            error = _visible_exception_detail(page)
            if error:
                failed_count += 1
                probes.append(
                    _combination_probe(
                        app_name=app_name,
                        page_name=page_name,
                        kind="combination",
                        label=f"combination #{index}",
                        status="failed",
                        detail=f"{detail} rendered Streamlit exception: {error}",
                        url=page.url,
                    )
                )
                executed_count += 1
                continue
            probes.extend(
                _collect_and_probe_current_view(
                    page,
                    app_name=app_name,
                    page_name=page_name,
                    widget_timeout_ms=widget_timeout_ms,
                    interaction_mode=interaction_mode,
                    action_button_policy=action_button_policy,
                    upload_file=upload_file,
                    restore_view=restore_view,
                    known=known,
                    discovery_passes=discovery_passes,
                    action_click_budget=action_click_budget,
                )
            )
            executed_count += 1
        except Exception as exc:
            failed_count += 1
            probes.append(
                _combination_probe(
                    app_name=app_name,
                    page_name=page_name,
                    kind="combination",
                    label=f"combination #{index}",
                    status="failed",
                    detail=f"{detail}: {exc}",
                    url=page.url,
                )
            )
    return plan.total_count, executed_count, failed_count, skipped_count, probes


def sweep_page(
    page: Any,
    *,
    web_robot: Any,
    base_url: str,
    active_app_query: str,
    app_name: str,
    page_name: str,
    display_page: str | None = None,
    current_page: Path | str | None = None,
    expected_text: Sequence[str] | None = None,
    check_active_app_route: bool = True,
    timeout: float,
    widget_timeout: float,
    interaction_mode: str,
    action_button_policy: str,
    click_action_labels: Sequence[str] = (),
    preselect_labels: Sequence[str] = (),
    missing_selected_action_policy: str = "fail",
    action_timeout: float = DEFAULT_ACTION_TIMEOUT_SECONDS,
    upload_file: Path,
    combination_mode: str = "exhaustive",
    max_combinations: int = 512,
    max_options_per_widget: int = 8,
    discovery_passes: int = 2,
    max_action_clicks_per_page: int = 25,
    screenshot_dir: Path | None = None,
    page_timeout: float | None = DEFAULT_PAGE_TIMEOUT_SECONDS,
    browser_issues: list[dict[str, str]] | None = None,
    runtime_isolation: str = "isolated",
    server_env: dict[str, str] | None = None,
    home_root: Path | None = None,
    assert_orchestrate_artifacts: bool = False,
    assert_workflow_artifacts: bool = False,
) -> PageSweep:
    started = time.perf_counter()
    timeout_ms = timeout * 1000.0
    widget_timeout_ms = widget_timeout * 1000.0
    action_timeout_ms = action_timeout * 1000.0
    page_deadline = None if page_timeout is None or page_timeout <= 0 else started + page_timeout
    target_url = web_robot.build_url(base_url, active_app=active_app_query) if not page_name else web_robot.build_page_url(base_url, page_name, active_app=active_app_query, current_page=str(current_page) if current_page else None)
    display = display_page or page_label(page_name)
    expect_any = tuple(expected_text) if expected_text is not None else (("View:",) if current_page else PAGE_EXPECTED_TEXT.get(page_name, (page_label(page_name),)))
    probes: list[WidgetProbe] = []
    browser_issue_start_index = len(browser_issues or [])
    page_status = "passed"
    combination_space_count = 0
    combination_count = 0
    combination_failed_count = 0
    combination_skipped_count = 0
    action_click_budget = [max_action_clicks_per_page]

    def restore_view() -> None:
        _enforce_page_deadline(page_deadline, "page watchdog expired before navigation")
        page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
        _enforce_page_deadline(page_deadline, "page watchdog expired before health check")
        health = web_robot.assert_page_healthy(page, label=f"{app_name}:{display}:restore", expect_any=expect_any, timeout_ms=timeout_ms, screenshot_dir=screenshot_dir)
        if not health.success:
            raise RuntimeError(health.detail)
        page.wait_for_timeout(1000)
        _enforce_page_deadline(page_deadline, "page watchdog expired before readiness wait")
        wait_for_page_ready(page, timeout_ms=timeout_ms)
        _enforce_page_deadline(page_deadline, "page watchdog expired before widget readiness wait")
        wait_for_widgets_ready(page, page_name=page_name, timeout_ms=timeout_ms)
        _enforce_page_deadline(page_deadline, "page watchdog expired before expander open")
        page.evaluate(OPEN_EXPANDERS_JS)

    try:
        restore_view()
        _enforce_page_deadline(page_deadline, "page watchdog expired before active-app check")
        if _append_visible_streamlit_issue_probe(probes, page=page, app_name=app_name, display=display):
            page_status = "failed"
        elif check_active_app_route and not active_app_route_matches(page.url, active_app_query):
            detail = f"active_app routed to {routed_active_app_slug(page.url)!r}, expected {sorted(active_app_aliases(active_app_query))!r}"
            probes.append(WidgetProbe(app_name, display, "active_app", "", "failed", detail, page.url))
        else:
            selected_actions_first = action_button_policy == "click-selected" and bool(click_action_labels)
            preflight_detail = current_home_action_preflight_blocker(
                app_name=app_name,
                active_app_query=active_app_query,
                page_name=page_name,
                action_button_policy=action_button_policy,
                click_action_labels=click_action_labels,
                runtime_isolation=runtime_isolation,
                server_env=server_env,
                home_root=home_root,
            )
            if preflight_detail:
                page_status = "environment_blocked"
                probes.append(WidgetProbe(app_name, display, "environment_preflight", "", "failed", preflight_detail, page.url))
            workflow_artifact_context = None
            if assert_workflow_artifacts and page_label(page_name) == "WORKFLOW" and not preflight_detail:
                workflow_artifact_context = build_workflow_artifact_context(
                    app_name=app_name,
                    active_app_query=active_app_query,
                    home_root=home_root,
                    server_env=server_env,
                )
                probes.extend(
                    validate_workflow_page_artifacts(
                        context=workflow_artifact_context,
                        display=display,
                        url=page.url,
                    )
                )
            if selected_actions_first and not preflight_detail:
                orchestrate_artifact_context = None
                if assert_orchestrate_artifacts and page_label(page_name) == "ORCHESTRATE":
                    orchestrate_artifact_context = build_orchestrate_artifact_context(
                        app_name=app_name,
                        active_app_query=active_app_query,
                        home_root=home_root,
                        server_env=server_env,
                    )
                probes.extend(
                    _probe_selected_actions_first(
                        page,
                        app_name=app_name,
                        display=display,
                        widget_timeout_ms=widget_timeout_ms,
                        click_action_labels=click_action_labels,
                        preselect_labels=preselect_labels,
                        missing_selected_action_policy=missing_selected_action_policy,
                        action_timeout_ms=action_timeout_ms,
                        upload_file=upload_file,
                        orchestrate_artifact_context=orchestrate_artifact_context,
                        workflow_artifact_context=workflow_artifact_context,
                    )
                )
                if not any(probe.status == "failed" for probe in probes):
                    restore_view()
            if not any(probe.status == "failed" for probe in probes):
                sweep_action_button_policy = "trial" if selected_actions_first else action_button_policy
                known: set[tuple[str, str, str, str, str]] = set()
                for scroll_y in _page_scroll_positions(page):
                    _enforce_page_deadline(page_deadline, "page watchdog expired while sweeping scroll positions")
                    _scroll_to(page, scroll_y)
                    _wait_for_timeout(page, 100)
                    probes.extend(
                        _collect_and_probe_current_view(
                            page,
                            app_name=app_name,
                            page_name=display,
                            widget_timeout_ms=widget_timeout_ms,
                            interaction_mode=interaction_mode,
                            action_button_policy=sweep_action_button_policy,
                            click_action_labels=click_action_labels,
                            preselect_labels=preselect_labels,
                            action_timeout_ms=action_timeout_ms,
                            upload_file=upload_file,
                            restore_view=restore_view,
                            known=known,
                            page_deadline=page_deadline,
                            discovery_passes=discovery_passes,
                            action_click_budget=action_click_budget,
                        )
                    )
                if combination_mode == "exhaustive":
                    space, count, combo_failed, combo_skipped, combo_probes = _exercise_widget_combinations(
                        page,
                        app_name=app_name,
                        page_name=display,
                        widget_timeout_ms=widget_timeout_ms,
                        interaction_mode=interaction_mode,
                        action_button_policy=sweep_action_button_policy,
                        upload_file=upload_file,
                        restore_view=restore_view,
                        known=known,
                        max_combinations=max_combinations,
                        max_options_per_widget=max_options_per_widget,
                        discovery_passes=discovery_passes,
                        action_click_budget=action_click_budget,
                    )
                    combination_space_count += space
                    combination_count += count
                    combination_failed_count += combo_failed
                    combination_skipped_count += combo_skipped
                    probes.extend(combo_probes)
                _enforce_page_deadline(page_deadline, "page watchdog expired before tab sweep")
                tab_count = page.locator("[role='tab']").count()
                for index in range(tab_count):
                    _enforce_page_deadline(page_deadline, "page watchdog expired while sweeping tabs")
                    tab = page.locator("[role='tab']").nth(index)
                    try:
                        if tab.is_visible(timeout=widget_timeout_ms) and tab.is_enabled(timeout=widget_timeout_ms):
                            _click_with_force_fallback(tab, timeout_ms=widget_timeout_ms)
                            page.wait_for_timeout(250)
                            for scroll_y in _page_scroll_positions(page):
                                _enforce_page_deadline(page_deadline, "page watchdog expired while sweeping tab scroll positions")
                                _scroll_to(page, scroll_y)
                                _wait_for_timeout(page, 100)
                                probes.extend(
                                    _collect_and_probe_current_view(
                                        page,
                                        app_name=app_name,
                                        page_name=display,
                                        widget_timeout_ms=widget_timeout_ms,
                                        interaction_mode=interaction_mode,
                                        action_button_policy=sweep_action_button_policy,
                                        click_action_labels=click_action_labels,
                                        preselect_labels=preselect_labels,
                                        action_timeout_ms=action_timeout_ms,
                                        upload_file=upload_file,
                                        restore_view=restore_view,
                                        known=known,
                                        page_deadline=page_deadline,
                                        discovery_passes=discovery_passes,
                                        action_click_budget=action_click_budget,
                                    )
                                )
                            if combination_mode == "exhaustive":
                                def restore_tab_view(tab_index: int = index) -> None:
                                    restore_view()
                                    active_tab = page.locator("[role='tab']").nth(tab_index)
                                    if active_tab.is_visible(timeout=widget_timeout_ms) and active_tab.is_enabled(timeout=widget_timeout_ms):
                                        _click_with_force_fallback(active_tab, timeout_ms=widget_timeout_ms)
                                        page.wait_for_timeout(250)
                                    page.evaluate(OPEN_EXPANDERS_JS)

                                space, count, combo_failed, combo_skipped, combo_probes = _exercise_widget_combinations(
                                    page,
                                    app_name=app_name,
                                    page_name=display,
                                    widget_timeout_ms=widget_timeout_ms,
                                    interaction_mode=interaction_mode,
                                    action_button_policy=sweep_action_button_policy,
                                    upload_file=upload_file,
                                    restore_view=restore_tab_view,
                                    known=known,
                                    max_combinations=max_combinations,
                                    max_options_per_widget=max_options_per_widget,
                                    discovery_passes=discovery_passes,
                                    action_click_budget=action_click_budget,
                                )
                                combination_space_count += space
                                combination_count += count
                                combination_failed_count += combo_failed
                                combination_skipped_count += combo_skipped
                                probes.extend(combo_probes)
                    except Exception as exc:
                        probes.append(WidgetProbe(app_name, display, "tab", f"tab #{index + 1}", "failed", _short_detail(str(exc)), page.url))
                if action_button_policy == "click-selected" and not selected_actions_first:
                    _append_missing_selected_action_probes(
                        probes,
                        app_name=app_name,
                        display=display,
                        url=getattr(page, "url", target_url),
                        click_action_labels=click_action_labels,
                        missing_selected_action_policy=missing_selected_action_policy,
                    )
    except PageWatchdogTimeout as exc:
        page_status = "timed_out"
        probes.append(WidgetProbe(app_name, display, "page_watchdog", "", "failed", _short_detail(str(exc)), getattr(page, "url", target_url)))
    except Exception as exc:
        page_status = "failed"
        probes.append(WidgetProbe(app_name, display, "page", "", "failed", str(exc), target_url))

    if _append_browser_issue_probes(
        probes,
        app_name=app_name,
        display=display,
        url=getattr(page, "url", target_url),
        browser_issues=browser_issues,
        start_index=browser_issue_start_index,
    ):
        page_status = "failed"

    failed = [probe for probe in probes if probe.status == "failed"]
    skipped = [probe for probe in probes if probe.status == "skipped"]
    probed = [probe for probe in probes if probe.status == "probed"]
    interacted = [probe for probe in probes if probe.status == "interacted"]
    main_widgets = [probe for probe in probes if widget_scope(probe) == "main"]
    sidebar_widgets = [probe for probe in probes if widget_scope(probe) == "sidebar"]
    if page_status == "passed":
        if failed:
            page_status = "failed"
        elif skipped:
            page_status = "skipped"
    return PageSweep(
        app=app_name,
        page=display,
        success=page_status == "passed",
        duration_seconds=time.perf_counter() - started,
        widget_count=len(probes),
        main_widget_count=len(main_widgets),
        sidebar_widget_count=len(sidebar_widgets),
        interacted_count=len(interacted),
        probed_count=len(probed),
        skipped_count=len(skipped),
        failed_count=len(failed),
        url=getattr(page, "url", target_url),
        failures=failed[:20],
        skips=skipped[:20],
        status=page_status,
        combination_space_count=combination_space_count,
        combination_count=combination_count,
        combination_failed_count=combination_failed_count,
        combination_skipped_count=combination_skipped_count,
    )


def _project_root_for(path: Path) -> Path:
    for candidate in [path.parent, *path.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return path.parent


def sweep_direct_apps_page(
    *,
    web_robot: Any,
    app_name: str,
    active_app: Path | str,
    route: AppsPageRoute,
    timeout: float,
    widget_timeout: float,
    interaction_mode: str,
    action_button_policy: str,
    click_action_labels: Sequence[str] = (),
    preselect_labels: Sequence[str] = (),
    missing_selected_action_policy: str = "fail",
    action_timeout: float = DEFAULT_ACTION_TIMEOUT_SECONDS,
    combination_mode: str = "exhaustive",
    max_combinations: int = 512,
    max_options_per_widget: int = 8,
    discovery_passes: int = 2,
    max_action_clicks_per_page: int = 25,
    browser_name: str,
    headless: bool,
    screenshot_dir: Path | None,
    server_env: dict[str, str],
    page_timeout: float | None = DEFAULT_PAGE_TIMEOUT_SECONDS,
    progress: ProgressReporter | None = None,
    resume_page_results: dict[str, PageSweep] | None = None,
    on_page_result: PageResultCallback | None = None,
) -> PageSweep:
    display = f"APPS_PAGE:{route.name}"
    resumed = _resume_page_if_available(
        app_name=app_name,
        page_name=display,
        resume_page_results=resume_page_results,
        progress=progress,
        on_page_result=on_page_result,
    )
    if resumed is not None:
        return resumed
    if progress is not None:
        progress.emit("page_start", app=app_name, page=display)
    port = web_robot._free_port()
    base_url = f"http://127.0.0.1:{port}"
    command = [
        "uv",
        "--preview-features",
        "extra-build-dependencies",
        "run",
        "--project",
        str(_project_root_for(route.path)),
        "streamlit",
        "run",
        str(route.path),
        "--server.address",
        "127.0.0.1",
        "--server.port",
        str(port),
        "--server.headless",
        "true",
        "--server.runOnSave",
        "false",
        "--browser.gatherUsageStats",
        "false",
        "--",
        "--active-app",
        str(active_app),
    ]
    with web_robot.StreamlitServer(command, env=server_env, url=base_url) as server:
        health = web_robot.wait_for_streamlit_health(base_url, timeout=timeout)
        if not health.success:
            detail = _streamlit_health_failure_detail(health, server, base_url=base_url)
            result = PageSweep(
                app_name,
                display,
                False,
                health.duration_seconds,
                1,
                0,
                0,
                0,
                1,
                health.url or base_url,
                [WidgetProbe(app_name, display, "streamlit", "", "failed", detail, health.url or base_url)],
                [],
                status="failed",
            )
            _emit_page_result(result, progress=progress, on_page_result=on_page_result)
            return result
        _, _, sync_playwright = web_robot._load_playwright()
        with sync_playwright() as playwright:
            browser = getattr(playwright, browser_name).launch(headless=headless)
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            try:
                page = context.new_page()
                browser_issues = _attach_browser_issue_capture(page)
                with tempfile.TemporaryDirectory(prefix="agilab-widget-robot-") as tmp_dir:
                    upload_file = Path(tmp_dir) / "upload-fixture.txt"
                    upload_file.write_text("agilab widget robot fixture\n", encoding="utf-8")
                    result = sweep_page(
                        page,
                        web_robot=web_robot,
                        base_url=base_url,
                        active_app_query=str(active_app),
                        app_name=app_name,
                        page_name="",
                        display_page=display,
                        expected_text=(),
                        check_active_app_route=False,
                        timeout=timeout,
                        widget_timeout=widget_timeout,
                        interaction_mode=interaction_mode,
                        action_button_policy=action_button_policy,
                        click_action_labels=click_action_labels,
                        preselect_labels=preselect_labels,
                        missing_selected_action_policy=missing_selected_action_policy,
                        action_timeout=action_timeout,
                        combination_mode=combination_mode,
                        max_combinations=max_combinations,
                        max_options_per_widget=max_options_per_widget,
                        discovery_passes=discovery_passes,
                        max_action_clicks_per_page=max_action_clicks_per_page,
                        upload_file=upload_file,
                        screenshot_dir=screenshot_dir,
                        page_timeout=page_timeout,
                        browser_issues=browser_issues,
                    )
                    _emit_page_result(result, progress=progress, on_page_result=on_page_result)
                    return result
            finally:
                context.close()
                browser.close()


def sweep_app(
    *,
    app: Path | str,
    pages: Sequence[str],
    apps_pages: Sequence[AppsPageRoute],
    timeout: float,
    widget_timeout: float,
    interaction_mode: str,
    action_button_policy: str,
    click_action_labels: Sequence[str] = (),
    preselect_labels: Sequence[str] = (),
    missing_selected_action_policy: str = "fail",
    action_timeout: float = DEFAULT_ACTION_TIMEOUT_SECONDS,
    combination_mode: str = "exhaustive",
    max_combinations: int = 512,
    max_options_per_widget: int = 8,
    discovery_passes: int = 2,
    max_action_clicks_per_page: int = 25,
    browser_name: str,
    headless: bool,
    screenshot_dir: Path | None,
    seed_demo_artifacts: bool,
    runtime_isolation: str,
    assert_orchestrate_artifacts: bool = False,
    assert_workflow_artifacts: bool = False,
    page_timeout: float | None = DEFAULT_PAGE_TIMEOUT_SECONDS,
    progress: ProgressReporter | None = None,
    resume_page_results: dict[str, PageSweep] | None = None,
    on_page_result: PageResultCallback | None = None,
) -> list[PageSweep]:
    web_robot = _load_web_robot()
    app_name = active_app_slug(str(app))
    port = web_robot._free_port()
    base_url = f"http://127.0.0.1:{port}"
    local_active_app = web_robot.resolve_local_active_app(str(app), str(web_robot.DEFAULT_APPS_PATH))
    command = web_robot.build_streamlit_command(active_app=local_active_app, apps_path=web_robot.DEFAULT_APPS_PATH, port=port)
    results: list[PageSweep] = []
    with tempfile.TemporaryDirectory(prefix="agilab-widget-robot-runtime-") as runtime_dir:
        seeded_runtime = build_seeded_server_env(
            web_robot,
            app_name=app_name,
            runtime_root=Path(runtime_dir),
            seed_demo_artifacts=seed_demo_artifacts,
            runtime_isolation=runtime_isolation,
        )
        with web_robot.StreamlitServer(command, env=seeded_runtime.env, url=base_url) as server:
            health = web_robot.wait_for_streamlit_health(base_url, timeout=timeout)
            if not health.success:
                detail = _streamlit_health_failure_detail(health, server, base_url=base_url)
                result = PageSweep(
                    app_name,
                    "SERVER",
                    False,
                    health.duration_seconds,
                    1,
                    0,
                    0,
                    0,
                    1,
                    health.url or base_url,
                    [WidgetProbe(app_name, "SERVER", "streamlit", "", "failed", detail, health.url or base_url)],
                    [],
                    status="failed",
                )
                _emit_page_result(result, progress=progress, on_page_result=on_page_result)
                return [result]
            _, _, sync_playwright = web_robot._load_playwright()
            with sync_playwright() as playwright:
                browser = getattr(playwright, browser_name).launch(headless=headless)
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                try:
                    page = context.new_page()
                    browser_issues = _attach_browser_issue_capture(page)
                    with tempfile.TemporaryDirectory(prefix="agilab-widget-robot-") as tmp_dir:
                        upload_file = Path(tmp_dir) / "upload-fixture.txt"
                        upload_file.write_text("agilab widget robot fixture\n", encoding="utf-8")
                        for page_name in pages:
                            display = page_label(page_name)
                            resumed = _resume_page_if_available(
                                app_name=app_name,
                                page_name=display,
                                resume_page_results=resume_page_results,
                                progress=progress,
                                on_page_result=on_page_result,
                            )
                            if resumed is not None:
                                results.append(resumed)
                                continue
                            if progress is not None:
                                progress.emit("page_start", app=app_name, page=display)
                            result = sweep_page(
                                page,
                                web_robot=web_robot,
                                base_url=base_url,
                                active_app_query=str(local_active_app),
                                app_name=app_name,
                                page_name=page_name,
                                timeout=timeout,
                                widget_timeout=widget_timeout,
                                interaction_mode=interaction_mode,
                                action_button_policy=action_button_policy,
                                click_action_labels=click_action_labels,
                                preselect_labels=preselect_labels,
                                missing_selected_action_policy=missing_selected_action_policy,
                                action_timeout=action_timeout,
                                combination_mode=combination_mode,
                                max_combinations=max_combinations,
                                max_options_per_widget=max_options_per_widget,
                                discovery_passes=discovery_passes,
                                max_action_clicks_per_page=max_action_clicks_per_page,
                                upload_file=upload_file,
                                screenshot_dir=screenshot_dir,
                                page_timeout=page_timeout,
                                browser_issues=browser_issues,
                                runtime_isolation=runtime_isolation,
                                server_env=seeded_runtime.env,
                                home_root=seeded_runtime.home_root,
                                assert_orchestrate_artifacts=assert_orchestrate_artifacts,
                                assert_workflow_artifacts=assert_workflow_artifacts,
                            )
                            results.append(result)
                            _emit_page_result(result, progress=progress, on_page_result=on_page_result)
                finally:
                    context.close()
                    browser.close()
        for route in apps_pages:
            results.append(
                sweep_direct_apps_page(
                    web_robot=web_robot,
                    app_name=app_name,
                    active_app=local_active_app,
                    route=route,
                    timeout=timeout,
                    widget_timeout=widget_timeout,
                    interaction_mode=interaction_mode,
                    action_button_policy=action_button_policy,
                    click_action_labels=click_action_labels,
                    preselect_labels=preselect_labels,
                    missing_selected_action_policy=missing_selected_action_policy,
                    action_timeout=action_timeout,
                    combination_mode=combination_mode,
                    max_combinations=max_combinations,
                    max_options_per_widget=max_options_per_widget,
                    discovery_passes=discovery_passes,
                    max_action_clicks_per_page=max_action_clicks_per_page,
                    browser_name=browser_name,
                    headless=headless,
                    screenshot_dir=screenshot_dir,
                    server_env=seeded_runtime.env,
                    page_timeout=page_timeout,
                    progress=progress,
                    resume_page_results=resume_page_results,
                    on_page_result=on_page_result,
                )
            )
    return results


def sweep_remote_app(
    *,
    app: Path | str,
    base_url: str,
    active_app_query: str,
    pages: Sequence[str],
    apps_pages: Sequence[AppsPageRoute],
    remote_app_root: str,
    timeout: float,
    widget_timeout: float,
    interaction_mode: str,
    action_button_policy: str,
    click_action_labels: Sequence[str] = (),
    preselect_labels: Sequence[str] = (),
    missing_selected_action_policy: str = "fail",
    action_timeout: float = DEFAULT_ACTION_TIMEOUT_SECONDS,
    combination_mode: str = "exhaustive",
    max_combinations: int = 512,
    max_options_per_widget: int = 8,
    discovery_passes: int = 2,
    max_action_clicks_per_page: int = 25,
    browser_name: str,
    headless: bool,
    screenshot_dir: Path | None,
    page_timeout: float | None = DEFAULT_PAGE_TIMEOUT_SECONDS,
    progress: ProgressReporter | None = None,
    resume_page_results: dict[str, PageSweep] | None = None,
    on_page_result: PageResultCallback | None = None,
) -> list[PageSweep]:
    web_robot = _load_web_robot()
    app_name = active_app_slug(str(app))
    base_url = normalize_remote_url(base_url)
    health = web_robot.wait_for_streamlit_health(base_url, timeout=timeout)
    if not health.success:
        result = PageSweep(
            app_name,
            "REMOTE_SERVER",
            False,
            health.duration_seconds,
            1,
            0,
            0,
            0,
            1,
            health.url or base_url,
            [WidgetProbe(app_name, "REMOTE_SERVER", "streamlit", "", "failed", health.detail, health.url or base_url)],
            [],
            status="failed",
        )
        _emit_page_result(result, progress=progress, on_page_result=on_page_result)
        return [result]

    _, _, sync_playwright = web_robot._load_playwright()
    results: list[PageSweep] = []
    with sync_playwright() as playwright:
        browser = getattr(playwright, browser_name).launch(headless=headless)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        try:
            page = context.new_page()
            browser_issues = _attach_browser_issue_capture(page)
            with tempfile.TemporaryDirectory(prefix="agilab-widget-robot-") as tmp_dir:
                upload_file = Path(tmp_dir) / "upload-fixture.txt"
                upload_file.write_text("agilab widget robot fixture\n", encoding="utf-8")
                for page_name in pages:
                    display = page_label(page_name)
                    resumed = _resume_page_if_available(
                        app_name=app_name,
                        page_name=display,
                        resume_page_results=resume_page_results,
                        progress=progress,
                        on_page_result=on_page_result,
                    )
                    if resumed is not None:
                        results.append(resumed)
                        continue
                    if progress is not None:
                        progress.emit("page_start", app=app_name, page=display)
                    result = sweep_page(
                        page,
                        web_robot=web_robot,
                        base_url=base_url,
                        active_app_query=active_app_query,
                        app_name=app_name,
                        page_name=page_name,
                        timeout=timeout,
                        widget_timeout=widget_timeout,
                        interaction_mode=interaction_mode,
                        action_button_policy=action_button_policy,
                        click_action_labels=click_action_labels,
                        preselect_labels=preselect_labels,
                        missing_selected_action_policy=missing_selected_action_policy,
                        action_timeout=action_timeout,
                        combination_mode=combination_mode,
                        max_combinations=max_combinations,
                        max_options_per_widget=max_options_per_widget,
                        discovery_passes=discovery_passes,
                        max_action_clicks_per_page=max_action_clicks_per_page,
                        upload_file=upload_file,
                        screenshot_dir=screenshot_dir,
                        page_timeout=page_timeout,
                        browser_issues=browser_issues,
                    )
                    results.append(result)
                    _emit_page_result(result, progress=progress, on_page_result=on_page_result)
                for route in apps_pages:
                    display = f"REMOTE_APPS_PAGE:{route.name}"
                    resumed = _resume_page_if_available(
                        app_name=app_name,
                        page_name=display,
                        resume_page_results=resume_page_results,
                        progress=progress,
                        on_page_result=on_page_result,
                    )
                    if resumed is not None:
                        results.append(resumed)
                        continue
                    if progress is not None:
                        progress.emit("page_start", app=app_name, page=display)
                    result = sweep_page(
                        page,
                        web_robot=web_robot,
                        base_url=base_url,
                        active_app_query=active_app_query,
                        app_name=app_name,
                        page_name="ANALYSIS",
                        display_page=display,
                        current_page=remote_apps_page_path(route, remote_app_root=remote_app_root),
                        expected_text=(),
                        check_active_app_route=False,
                        timeout=timeout,
                        widget_timeout=widget_timeout,
                        interaction_mode=interaction_mode,
                        action_button_policy=action_button_policy,
                        click_action_labels=click_action_labels,
                        preselect_labels=preselect_labels,
                        missing_selected_action_policy=missing_selected_action_policy,
                        action_timeout=action_timeout,
                        combination_mode=combination_mode,
                        max_combinations=max_combinations,
                        max_options_per_widget=max_options_per_widget,
                        discovery_passes=discovery_passes,
                        max_action_clicks_per_page=max_action_clicks_per_page,
                        upload_file=upload_file,
                        screenshot_dir=screenshot_dir,
                        page_timeout=page_timeout,
                        browser_issues=browser_issues,
                    )
                    results.append(result)
                    _emit_page_result(result, progress=progress, on_page_result=on_page_result)
        finally:
            context.close()
            browser.close()
    return results


def summarize(pages: Sequence[PageSweep], *, app_count: int, target_seconds: float) -> WidgetSweepSummary:
    total = sum(page.duration_seconds for page in pages)
    failed_count = sum(page.failed_count for page in pages)
    skipped_count = sum(page.skipped_count for page in pages)
    success = bool(pages) and failed_count == 0 and skipped_count == 0 and all(page.success and page.status == "passed" for page in pages)
    return WidgetSweepSummary(
        success=success,
        total_duration_seconds=total,
        target_seconds=target_seconds,
        within_target=success and total <= target_seconds,
        app_count=app_count,
        page_count=len(pages),
        widget_count=sum(page.widget_count for page in pages),
        main_widget_count=sum(page.main_widget_count for page in pages),
        sidebar_widget_count=sum(page.sidebar_widget_count for page in pages),
        interacted_count=sum(page.interacted_count for page in pages),
        probed_count=sum(page.probed_count for page in pages),
        skipped_count=skipped_count,
        failed_count=failed_count,
        pages=list(pages),
        combination_space_count=sum(page.combination_space_count for page in pages),
        combination_count=sum(page.combination_count for page in pages),
        combination_failed_count=sum(page.combination_failed_count for page in pages),
        combination_skipped_count=sum(page.combination_skipped_count for page in pages),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Exercise visible widgets across AGILAB public built-in apps through a real browser.")
    parser.add_argument("--url", help="Existing AGILAB URL to test. Hugging Face Space pages are normalized to their hf.space runtime URL.")
    parser.add_argument("--active-app", help="Override active_app query used with --url. Defaults to each selected app name.")
    parser.add_argument("--remote-app-root", default="/app", help="Remote checkout root used for current_page paths when --url is set.")
    parser.add_argument("--apps", default="all", help="Comma-separated built-in app names/paths, or 'all'.")
    parser.add_argument("--pages", default="all", help="Comma-separated page routes, or 'all'. HOME maps to the root page.")
    parser.add_argument("--apps-pages", default="configured", help="Apps-pages to test: 'configured' per app, 'all', 'none', or comma-separated names/paths. Default: configured.")
    parser.add_argument("--browser", choices=("chromium", "firefox", "webkit"), default="chromium")
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--widget-timeout", type=float, default=DEFAULT_WIDGET_TIMEOUT_SECONDS)
    parser.add_argument("--page-timeout", type=float, default=DEFAULT_PAGE_TIMEOUT_SECONDS, help="Whole-page watchdog timeout in seconds. Use 0 to disable.")
    parser.add_argument("--interaction-mode", choices=("actionability", "full"), default="full")
    parser.add_argument(
        "--action-button-policy",
        choices=("trial", "safe-click", "click", "click-selected"),
        default="safe-click",
        help=(
            "Action button behavior: trial probes layout only, safe-click fires guarded read-only/navigation "
            "callbacks, click fires every visible action callback, and click-selected fires only labels named "
            "by --click-action-labels."
        ),
    )
    parser.add_argument("--click-action-labels", default="", help="Comma-separated action button labels to fire when --action-button-policy=click-selected.")
    parser.add_argument("--preselect-labels", default="", help="Comma-separated compact choice/radio labels to select before action probing, for example 'Run now'.")
    parser.add_argument(
        "--missing-selected-action-policy",
        choices=MISSING_SELECTED_ACTION_POLICIES,
        default="fail",
        help="How to treat selected action labels that are absent on an otherwise healthy page.",
    )
    parser.add_argument("--action-timeout", type=float, default=DEFAULT_ACTION_TIMEOUT_SECONDS, help="Seconds to wait for a clicked action button to settle or render an error.")
    parser.add_argument(
        "--runtime-isolation",
        choices=RUNTIME_ISOLATION_MODES,
        default="isolated",
        help="Use isolated temporary HOME/share roots, or current-home for opt-in runs against an already installed local worker environment.",
    )
    parser.add_argument(
        "--assert-orchestrate-artifacts",
        action="store_true",
        help=(
            "For local ORCHESTRATE selected-action journeys, assert filesystem side effects "
            "for run/load/export/delete actions instead of only checking visible UI feedback."
        ),
    )
    parser.add_argument(
        "--assert-workflow-artifacts",
        action="store_true",
        help=(
            "For local WORKFLOW sweeps, assert the restored lab_stages.toml contract and, "
            "when a selected run action is fired, that a workflow run log changed."
        ),
    )
    parser.add_argument("--combination-mode", choices=("off", "exhaustive"), default="exhaustive", help="Explore finite checkbox/toggle/radio/selectbox state combinations. Default: exhaustive.")
    parser.add_argument("--max-combinations", type=int, default=512, help="Maximum widget state combinations to execute per page view before failing the sweep as capped.")
    parser.add_argument("--max-options-per-widget", type=int, default=8, help="Maximum selectbox options included in combination coverage per widget.")
    parser.add_argument("--discovery-passes", type=int, default=2, help="Number of repeated widget-discovery passes per page state, used to catch widgets revealed by safe callbacks.")
    parser.add_argument("--max-action-clicks-per-page", type=int, default=25, help="Maximum real action-button clicks per page sweep. Use 0 to trial-probe all action buttons without firing callbacks.")
    parser.add_argument("--target-seconds", type=float, default=DEFAULT_TARGET_SECONDS)
    parser.add_argument("--screenshot-dir")
    parser.add_argument("--no-seed-demo-artifacts", action="store_true", help="Disable temporary demo artifacts used to exercise configured apps-pages more deeply.")
    parser.add_argument("--progress-log", help="Append NDJSON progress records for resumable long UI sweeps.")
    parser.add_argument("--resume-from-progress", help="Resume already passed pages from an NDJSON progress log.")
    parser.add_argument("--json-output", help="Write and refresh the JSON summary after every completed page.")
    parser.add_argument("--quiet-progress", action="store_true", help="Disable one-line progress updates on stderr.")
    parser.add_argument("--json", action="store_true")
    return parser


def render_human(summary: WidgetSweepSummary) -> str:
    lines = [
        "AGILAB widget robot",
        f"verdict: {'PASS' if summary.success else 'FAIL'}",
        f"kpi: total={summary.total_duration_seconds:.2f}s target<={summary.target_seconds:.2f}s within_target={'yes' if summary.within_target else 'no'}",
        f"apps={summary.app_count} pages={summary.page_count} widgets={summary.widget_count} main={summary.main_widget_count} sidebar={summary.sidebar_widget_count} interacted={summary.interacted_count} probed={summary.probed_count} skipped={summary.skipped_count} failed={summary.failed_count}",
        f"combinations: space={summary.combination_space_count} executed={summary.combination_count} failed={summary.combination_failed_count} skipped={summary.combination_skipped_count}",
    ]
    for page in summary.pages:
        lines.append(
            f"- {page.app}/{page.page}: {'OK' if page.success else 'FAIL'} status={page.status} "
            f"widgets={page.widget_count} main={page.main_widget_count} sidebar={page.sidebar_widget_count} "
            f"interacted={page.interacted_count} probed={page.probed_count} skipped={page.skipped_count} "
            f"failed={page.failed_count} combinations={page.combination_count}/{page.combination_space_count} "
            f"combo_failed={page.combination_failed_count} combo_skipped={page.combination_skipped_count}"
        )
        for failure in page.failures[:3]:
            lines.append(f"  failure: {failure.kind} {failure.label!r} - {failure.detail}")
        for skip in page.skips[:3]:
            lines.append(f"  skipped: {skip.kind} {skip.label!r} - {skip.detail}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.timeout <= 0:
        parser.error("--timeout must be greater than 0")
    if args.widget_timeout <= 0:
        parser.error("--widget-timeout must be greater than 0")
    if args.page_timeout < 0:
        parser.error("--page-timeout must be greater than or equal to 0")
    if args.action_timeout <= 0:
        parser.error("--action-timeout must be greater than 0")
    if args.max_combinations <= 0:
        parser.error("--max-combinations must be greater than 0")
    if args.max_options_per_widget <= 0:
        parser.error("--max-options-per-widget must be greater than 0")
    if args.interaction_mode == "actionability" and args.action_button_policy != "trial":
        parser.error("--action-button-policy safe-click/click/click-selected only applies with --interaction-mode full")
    click_action_labels = parse_csv(args.click_action_labels)
    preselect_labels = parse_csv(args.preselect_labels)
    if args.action_button_policy == "click-selected" and not click_action_labels:
        parser.error("--click-action-labels is required with --action-button-policy click-selected")
    if args.url and (args.assert_orchestrate_artifacts or args.assert_workflow_artifacts):
        parser.error("--assert-*artifacts options require a local robot-launched Streamlit server")
    if args.discovery_passes <= 0:
        parser.error("--discovery-passes must be greater than 0")
    if args.max_action_clicks_per_page < 0:
        parser.error("--max-action-clicks-per-page must be greater than or equal to 0")
    apps = resolve_apps(args.apps)
    pages = resolve_pages(args.pages)
    global_apps_pages = None if args.apps_pages == "configured" else resolve_apps_pages(args.apps_pages)
    screenshot_dir = Path(args.screenshot_dir).expanduser().resolve() if args.screenshot_dir else None
    progress_log = Path(args.progress_log).expanduser().resolve() if args.progress_log else None
    resume_progress_log = Path(args.resume_from_progress).expanduser().resolve() if args.resume_from_progress else None
    json_output = Path(args.json_output).expanduser().resolve() if args.json_output else None
    progress = ProgressReporter(progress_log, stderr=not args.quiet_progress)
    resume_page_results = load_completed_page_results(resume_progress_log) if resume_progress_log is not None else None
    app_specs = [(app, configured_apps_pages_for_app(app) if global_apps_pages is None else global_apps_pages) for app in apps]
    expected_page_count = sum(len(pages) + len(app_pages) for _, app_pages in app_specs)
    results: list[PageSweep] = []
    remote_url = normalize_remote_url(args.url) if args.url else None

    def on_page_result(page: PageSweep) -> None:
        results.append(page)
        if json_output is not None:
            write_summary_json(json_output, results, app_count=len(apps), target_seconds=args.target_seconds)

    progress.emit("run_start", app_count=len(apps), page_count=expected_page_count)
    for app, app_pages in app_specs:
        if remote_url:
            sweep_remote_app(
                app=app,
                base_url=remote_url,
                active_app_query=args.active_app or active_app_slug(str(app)),
                pages=pages,
                apps_pages=app_pages,
                remote_app_root=args.remote_app_root,
                timeout=args.timeout,
                widget_timeout=args.widget_timeout,
                interaction_mode=args.interaction_mode,
                action_button_policy=args.action_button_policy,
                click_action_labels=click_action_labels,
                preselect_labels=preselect_labels,
                missing_selected_action_policy=args.missing_selected_action_policy,
                action_timeout=args.action_timeout,
                combination_mode=args.combination_mode,
                max_combinations=args.max_combinations,
                max_options_per_widget=args.max_options_per_widget,
                discovery_passes=args.discovery_passes,
                max_action_clicks_per_page=args.max_action_clicks_per_page,
                browser_name=args.browser,
                headless=not args.headful,
                screenshot_dir=screenshot_dir,
                page_timeout=args.page_timeout,
                progress=progress,
                resume_page_results=resume_page_results,
                on_page_result=on_page_result,
            )
        else:
            sweep_app(
                app=app,
                pages=pages,
                apps_pages=app_pages,
                timeout=args.timeout,
                widget_timeout=args.widget_timeout,
                interaction_mode=args.interaction_mode,
                action_button_policy=args.action_button_policy,
                click_action_labels=click_action_labels,
                preselect_labels=preselect_labels,
                missing_selected_action_policy=args.missing_selected_action_policy,
                action_timeout=args.action_timeout,
                combination_mode=args.combination_mode,
                max_combinations=args.max_combinations,
                max_options_per_widget=args.max_options_per_widget,
                discovery_passes=args.discovery_passes,
                max_action_clicks_per_page=args.max_action_clicks_per_page,
                browser_name=args.browser,
                headless=not args.headful,
                screenshot_dir=screenshot_dir,
                seed_demo_artifacts=not args.no_seed_demo_artifacts,
                runtime_isolation=args.runtime_isolation,
                assert_orchestrate_artifacts=args.assert_orchestrate_artifacts,
                assert_workflow_artifacts=args.assert_workflow_artifacts,
                page_timeout=args.page_timeout,
                progress=progress,
                resume_page_results=resume_page_results,
                on_page_result=on_page_result,
            )
    summary = summarize(results, app_count=len(apps), target_seconds=args.target_seconds)
    if json_output is not None:
        write_summary_json(json_output, results, app_count=len(apps), target_seconds=args.target_seconds)
    progress.emit(
        "run_done",
        status="passed" if summary.success else "failed",
        duration_seconds=summary.total_duration_seconds,
        page_count=summary.page_count,
        failed_count=summary.failed_count,
        skipped_count=summary.skipped_count,
    )
    print(json.dumps(asdict(summary), indent=2) if args.json else render_human(summary))
    return 0 if summary.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
