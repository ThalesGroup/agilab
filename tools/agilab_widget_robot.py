#!/usr/bin/env python3
"""Sweep AGILAB public app pages and exercise visible Streamlit widgets.

By default the robot performs real interactions for input/navigation widgets.
Runtime action buttons are actionability-checked with ``trial=True`` unless
``--action-button-policy click`` is supplied, because clicking INSTALL/EXECUTE
buttons can start installers, workers, benchmarks, or training jobs.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_ROBOT_PATH = REPO_ROOT / "tools/agilab_web_robot.py"
DEFAULT_APPS_ROOT = REPO_ROOT / "src/agilab/apps/builtin"
DEFAULT_PAGES = ("", "PROJECT", "ORCHESTRATE", "PIPELINE", "ANALYSIS")
DEFAULT_TIMEOUT_SECONDS = 90.0
DEFAULT_WIDGET_TIMEOUT_SECONDS = 3.0
DEFAULT_TARGET_SECONDS = 600.0
DEFAULT_INTERACTION_MODE = "full"
DEFAULT_ACTION_BUTTON_POLICY = "trial"
ACTION_BUTTON_KINDS = {"button", "form_submit_button", "download_button"}
PAGE_EXPECTED_TEXT = {
    "": ("AGILAB", "Start here"),
    "PROJECT": ("PROJECT", "Active app", "Project"),
    "ORCHESTRATE": ("ORCHESTRATE", "INSTALL", "EXECUTE"),
    "PIPELINE": ("PIPELINE", "Pipeline", "Run"),
    "ANALYSIS": ("ANALYSIS", "Choose pages", "View:"),
}
PAGE_MIN_WIDGETS = {
    "": 5,
    "PROJECT": 5,
    "ORCHESTRATE": 5,
    "PIPELINE": 3,
    "ANALYSIS": 3,
}

WIDGET_COLLECTOR_JS = r"""
() => {
  const specs = [
    ["button", "[data-testid='stButton'] button"],
    ["form_submit_button", "[data-testid='stFormSubmitButton'] button"],
    ["download_button", "[data-testid='stDownloadButton'] button"],
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
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
  };

  const labelFor = (el) => {
    const direct = el.getAttribute("aria-label") || el.getAttribute("title") || el.getAttribute("placeholder");
    if (direct && direct.trim()) {
      return direct.trim();
    }
    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
      const label = document.getElementById(labelledBy);
      if (label && label.innerText.trim()) {
        return label.innerText.trim().replace(/\s+/g, " ").slice(0, 120);
      }
    }
    const container = el.closest("[data-testid]");
    const text = (container || el).innerText || el.value || el.textContent || "";
    return text.trim().replace(/\s+/g, " ").slice(0, 120);
  };

  const testIdFor = (el) => {
    const container = el.closest("[data-testid]");
    return container ? container.getAttribute("data-testid") : "";
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
      if (!visible(el)) {
        continue;
      }
      if (seen.has(el)) {
        continue;
      }
      seen.add(el);
      const id = `agilab-widget-${nextId++}`;
      el.setAttribute("data-agilab-widget-id", id);
      widgets.push({
        id,
        kind,
        label: labelFor(el),
        disabled: Boolean(el.disabled || el.getAttribute("aria-disabled") === "true"),
        role: el.getAttribute("role") || "",
        tag: el.tagName.toLowerCase(),
        type: el.getAttribute("type") || "",
        testid: testIdFor(el),
        path: pathFor(el),
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
      details.open = true;
      changed += 1;
    }
  }
  return changed;
}
"""


@dataclass(frozen=True)
class WidgetProbe:
    app: str
    page: str
    kind: str
    label: str
    status: str
    detail: str
    url: str


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


def _load_web_robot() -> Any:
    spec = importlib.util.spec_from_file_location("agilab_web_robot_for_widget_sweep", WEB_ROBOT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {WEB_ROBOT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def public_builtin_apps(apps_root: Path = DEFAULT_APPS_ROOT) -> list[Path]:
    return sorted(path.resolve() for path in apps_root.glob("*_project") if path.is_dir())


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def resolve_apps(apps: str, *, apps_root: Path = DEFAULT_APPS_ROOT) -> list[Path | str]:
    if apps == "all":
        return public_builtin_apps(apps_root)
    resolved: list[Path | str] = []
    for item in parse_csv(apps):
        candidate = Path(item).expanduser()
        if candidate.exists():
            resolved.append(candidate.resolve())
            continue
        builtin_candidate = apps_root / item
        if builtin_candidate.exists():
            resolved.append(builtin_candidate.resolve())
            continue
        resolved.append(item)
    return resolved


def resolve_pages(pages: str) -> list[str]:
    if pages == "all":
        return list(DEFAULT_PAGES)
    return ["" if page.upper() == "HOME" else page for page in parse_csv(pages)]


def page_label(page: str) -> str:
    return page or "HOME"


def wait_for_page_ready(page: Any, *, timeout_ms: float) -> None:
    deadline = time.perf_counter() + timeout_ms / 1000.0
    while time.perf_counter() < deadline:
        text = ""
        try:
            text = page.locator("body").inner_text(timeout=1000).lower()
        except Exception:
            pass
        spinner_count = 0
        try:
            spinner_count = page.locator("[data-testid='stSpinner']").count()
        except Exception:
            pass
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


def active_app_aliases(active_app: str) -> set[str]:
    slug = Path(str(active_app).rstrip("/")).name
    aliases = {slug}
    if slug.endswith("_project"):
        aliases.add(slug[: -len("_project")])
    return aliases


def active_app_route_matches(web_robot: Any, url: str, expected_active_app: str) -> bool:
    actual = web_robot.routed_active_app_slug(url)
    return actual in active_app_aliases(expected_active_app)


def _widget_fingerprint(widget: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(widget.get("kind", "")),
        _normalized_label(str(widget.get("label", ""))),
        str(widget.get("testid", "")),
        str(widget.get("path", "")),
    )


def _normalized_label(label: str) -> str:
    return (
        label.replace("keyboard_arrow_right", "")
        .replace("keyboard_arrow_down", "")
        .strip()
        .lower()
    )


def _same_widget(widget: dict[str, Any], candidate: dict[str, Any]) -> bool:
    kind = str(widget.get("kind", ""))
    if kind != str(candidate.get("kind", "")):
        return False
    label = _normalized_label(str(widget.get("label", "")))
    candidate_label = _normalized_label(str(candidate.get("label", "")))
    if label and candidate_label and label == candidate_label:
        return True
    if label and candidate_label and (label in candidate_label or candidate_label in label):
        return True
    if widget.get("testid") and widget.get("testid") == candidate.get("testid"):
        return str(widget.get("path", "")) == str(candidate.get("path", ""))
    return False


def _short_detail(detail: str, *, limit: int = 500) -> str:
    return detail if len(detail) <= limit else detail[: limit - 3] + "..."


def _widget_locator(page: Any, widget: dict[str, Any], *, timeout_ms: float) -> Any:
    locator = page.locator(f"[data-agilab-widget-id='{widget['id']}']").first
    try:
        if locator.count() > 0:
            return locator
    except Exception:
        return locator

    refreshed_widgets = page.evaluate(WIDGET_COLLECTOR_JS)
    fingerprint = _widget_fingerprint(widget)
    for refreshed in refreshed_widgets:
        if _widget_fingerprint(refreshed) == fingerprint:
            widget["id"] = refreshed["id"]
            return page.locator(f"[data-agilab-widget-id='{widget['id']}']").first
    for refreshed in refreshed_widgets:
        if _same_widget(widget, refreshed):
            widget["id"] = refreshed["id"]
            return page.locator(f"[data-agilab-widget-id='{widget['id']}']").first
    return locator


def _visible_exception_detail(page: Any) -> str | None:
    try:
        exceptions = page.locator("[data-testid='stException']")
        if exceptions.count() > 0 and exceptions.first.is_visible(timeout=500):
            text = exceptions.first.inner_text(timeout=500)
            return _short_detail(text or "Streamlit exception rendered")
    except Exception:
        return None
    return None


def _assert_no_visible_exception(page: Any) -> tuple[bool, str]:
    detail = _visible_exception_detail(page)
    if detail:
        return False, detail
    return True, ""


def _fill_and_restore(locator: Any, value: str, *, timeout_ms: float) -> None:
    original = locator.input_value(timeout=timeout_ms)
    next_value = f"{original} robot" if original else value
    locator.fill(next_value, timeout=timeout_ms)
    locator.fill(original, timeout=timeout_ms)


def _interact_widget(
    page: Any,
    locator: Any,
    widget: dict[str, Any],
    *,
    timeout_ms: float,
    action_button_policy: str,
    upload_file: Path,
) -> tuple[str, str]:
    kind = str(widget.get("kind", ""))
    if kind in ACTION_BUTTON_KINDS:
        if action_button_policy == "click":
            try:
                locator.click(timeout=timeout_ms)
            except Exception:
                locator.click(timeout=timeout_ms, force=True)
            page.wait_for_timeout(250)
            ok, detail = _assert_no_visible_exception(page)
            if not ok:
                return "failed", f"button click rendered exception: {detail}"
            return "interacted", "clicked action button"
        try:
            locator.click(timeout=timeout_ms, trial=True)
            return "probed", "action button browser-clickable; callback not fired by default"
        except Exception as exc:
            return (
                "probed",
                _short_detail(
                    "action button visible/enabled but trial click was layout-intercepted; "
                    f"callback not fired by default: {exc}"
                ),
            )

    if kind in {"checkbox", "toggle"}:
        try:
            was_checked = locator.is_checked(timeout=timeout_ms)
        except Exception:
            was_checked = None
        locator.click(timeout=timeout_ms)
        page.wait_for_timeout(250)
        if was_checked is not None:
            locator = _widget_locator(page, widget, timeout_ms=timeout_ms)
            try:
                if locator.is_checked(timeout=timeout_ms) != was_checked:
                    locator.click(timeout=timeout_ms)
                    page.wait_for_timeout(250)
            except Exception:
                pass
        ok, detail = _assert_no_visible_exception(page)
        if not ok:
            return "failed", f"{kind} interaction rendered exception: {detail}"
        return "interacted", f"clicked and restored {kind}"

    if kind == "radio":
        restore_state = None
        try:
            restore_state = locator.evaluate(
                """
                (el) => {
                  const checked = el.name
                    ? document.querySelector(`input[type="radio"][name="${CSS.escape(el.name)}"]:checked`)
                    : null;
                  return checked ? {name: checked.name, value: checked.value} : null;
                }
                """
            )
        except Exception:
            restore_state = None
        locator.click(timeout=timeout_ms)
        page.wait_for_timeout(250)
        if restore_state:
            try:
                restored = page.evaluate(
                    """
                    ({name, value}) => {
                      for (const el of document.querySelectorAll('input[type="radio"]')) {
                        if (el.name === name && el.value === value) {
                          el.setAttribute("data-agilab-radio-restore", "1");
                          return true;
                        }
                      }
                      return false;
                    }
                    """,
                    restore_state,
                )
                if restored:
                    page.locator("[data-agilab-radio-restore='1']").first.click(timeout=timeout_ms)
                    page.wait_for_timeout(250)
            except Exception:
                pass
        ok, detail = _assert_no_visible_exception(page)
        if not ok:
            return "failed", f"{kind} interaction rendered exception: {detail}"
        return "interacted", "clicked and restored radio option"

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
        try:
            locator.click(timeout=timeout_ms)
        except Exception:
            locator.click(timeout=timeout_ms, force=True)
        page.wait_for_timeout(150)
        page.keyboard.press("Escape")
        return "interacted", f"opened and closed {kind}"

    if kind == "file_uploader":
        input_locator = locator.locator("input[type='file']").first
        input_locator.set_input_files(str(upload_file), timeout=timeout_ms)
        page.wait_for_timeout(250)
        ok, detail = _assert_no_visible_exception(page)
        if not ok:
            return "failed", f"file uploader rendered exception: {detail}"
        return "interacted", "uploaded temporary robot fixture"

    if kind == "data_editor":
        locator.click(timeout=timeout_ms)
        return "interacted", "focused data editor/dataframe region"

    if kind in {"tab", "expander"}:
        try:
            locator.click(timeout=timeout_ms)
        except Exception:
            locator.click(timeout=timeout_ms, force=True)
        page.wait_for_timeout(250)
        ok, detail = _assert_no_visible_exception(page)
        if not ok:
            return "failed", f"{kind} interaction rendered exception: {detail}"
        return "interacted", f"clicked {kind}"

    locator.click(timeout=timeout_ms, trial=True)
    return "probed", f"unknown widget kind actionability verified ({kind})"


def _probe_widget(
    page: Any,
    widget: dict[str, Any],
    *,
    timeout_ms: float,
    interaction_mode: str,
    action_button_policy: str,
    upload_file: Path,
) -> tuple[str, str]:
    if widget.get("disabled"):
        return "probed", "disabled state verified"

    locator = _widget_locator(page, widget, timeout_ms=timeout_ms)
    kind = str(widget.get("kind", ""))
    try:
        locator.scroll_into_view_if_needed(timeout=timeout_ms)
        if not locator.is_visible(timeout=timeout_ms):
            return "skipped", "not visible after collection"
        if not locator.is_enabled(timeout=timeout_ms):
            return "skipped", "not enabled"
        locator.bounding_box(timeout=timeout_ms)
        if interaction_mode == "actionability":
            if kind in ACTION_BUTTON_KINDS:
                locator.click(timeout=timeout_ms, trial=True)
            return "probed", f"visible/enabled ok ({kind})"
        return _interact_widget(
            page,
            locator,
            widget,
            timeout_ms=timeout_ms,
            action_button_policy=action_button_policy,
            upload_file=upload_file,
        )
    except Exception as exc:
        return "skipped", _short_detail(f"volatile after collection: {exc}")


def _collect_and_probe_current_view(
    page: Any,
    *,
    app_name: str,
    page_name: str,
    timeout_ms: float,
    widget_timeout_ms: float,
    interaction_mode: str,
    action_button_policy: str,
    upload_file: Path,
    restore_view: Any | None,
    known: set[tuple[str, str, str, str]],
) -> list[WidgetProbe]:
    page.evaluate(OPEN_EXPANDERS_JS)
    widgets = page.evaluate(WIDGET_COLLECTOR_JS)
    probes: list[WidgetProbe] = []
    for widget in widgets:
        fingerprint = _widget_fingerprint(widget)
        if fingerprint in known:
            continue
        known.add(fingerprint)
        status, detail = _probe_widget(
            page,
            widget,
            timeout_ms=widget_timeout_ms,
            interaction_mode=interaction_mode,
            action_button_policy=action_button_policy,
            upload_file=upload_file,
        )
        if status == "skipped" and "volatile after collection" in detail and restore_view is not None:
            try:
                restore_view()
                status, detail = _probe_widget(
                    page,
                    widget,
                    timeout_ms=widget_timeout_ms,
                    interaction_mode=interaction_mode,
                    action_button_policy=action_button_policy,
                    upload_file=upload_file,
                )
                if status != "skipped":
                    detail = f"{detail}; recovered after page restore"
            except Exception as exc:
                status = "skipped"
                detail = _short_detail(f"restore retry failed: {exc}")
        probes.append(
            WidgetProbe(
                app=app_name,
                page=page_label(page_name),
                kind=str(widget.get("kind", "")),
                label=str(widget.get("label", "")),
                status=status,
                detail=detail,
                url=page.url,
            )
        )
    return probes


def sweep_page(
    page: Any,
    *,
    web_robot: Any,
    base_url: str,
    active_app_query: str,
    app_name: str,
    page_name: str,
    timeout: float,
    widget_timeout: float,
    interaction_mode: str,
    action_button_policy: str,
    upload_file: Path,
    screenshot_dir: Path | None = None,
) -> PageSweep:
    started = time.perf_counter()
    timeout_ms = timeout * 1000.0
    widget_timeout_ms = widget_timeout * 1000.0
    target_url = (
        web_robot.build_url(base_url, active_app=active_app_query)
        if not page_name
        else web_robot.build_page_url(base_url, page_name, active_app=active_app_query)
    )
    probes: list[WidgetProbe] = []
    try:
        page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
        health = web_robot.assert_page_healthy(
            page,
            label=f"{app_name}:{page_label(page_name)}",
            expect_any=PAGE_EXPECTED_TEXT.get(page_name, (page_label(page_name),)),
            timeout_ms=timeout_ms,
            screenshot_dir=screenshot_dir,
        )
        if not health.success:
            probes.append(
                WidgetProbe(app_name, page_label(page_name), "page", "", "failed", health.detail, page.url)
            )
        else:
            def restore_view() -> None:
                page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
                health_after_restore = web_robot.assert_page_healthy(
                    page,
                    label=f"{app_name}:{page_label(page_name)}:restore",
                    expect_any=PAGE_EXPECTED_TEXT.get(page_name, (page_label(page_name),)),
                    timeout_ms=timeout_ms,
                    screenshot_dir=screenshot_dir,
                )
                if not health_after_restore.success:
                    raise RuntimeError(health_after_restore.detail)
                page.wait_for_timeout(1000)
                wait_for_page_ready(page, timeout_ms=timeout_ms)
                wait_for_widgets_ready(page, page_name=page_name, timeout_ms=timeout_ms)
                page.evaluate(OPEN_EXPANDERS_JS)

            page.wait_for_timeout(3000)
            wait_for_page_ready(page, timeout_ms=timeout_ms)
            wait_for_widgets_ready(page, page_name=page_name, timeout_ms=timeout_ms)
            if not active_app_route_matches(web_robot, page.url, active_app_query):
                screenshot = web_robot._screenshot(
                    page,
                    screenshot_dir,
                    f"{app_name}-{page_label(page_name)}-active-app",
                )
                detail = (
                    f"active_app routed to {web_robot.routed_active_app_slug(page.url)!r}, "
                    f"expected one of {sorted(active_app_aliases(active_app_query))!r}"
                )
                if screenshot:
                    detail += f"; screenshot={screenshot}"
                probes.append(
                    WidgetProbe(app_name, page_label(page_name), "active_app", "", "failed", detail, page.url)
                )
            else:
                known: set[tuple[str, str, str, str]] = set()
                probes.extend(
                    _collect_and_probe_current_view(
                        page,
                        app_name=app_name,
                        page_name=page_name,
                        timeout_ms=timeout_ms,
                        widget_timeout_ms=widget_timeout_ms,
                        interaction_mode=interaction_mode,
                        action_button_policy=action_button_policy,
                        upload_file=upload_file,
                        restore_view=restore_view,
                        known=known,
                    )
                )
                tab_count = page.locator("[role='tab']").count()
                for index in range(tab_count):
                    tab = page.locator("[role='tab']").nth(index)
                    try:
                        if tab.is_visible(timeout=widget_timeout_ms) and tab.is_enabled(timeout=widget_timeout_ms):
                            tab.focus(timeout=widget_timeout_ms)
                            tab.press("Enter", timeout=widget_timeout_ms)
                            page.wait_for_timeout(250)
                            probes.extend(
                                _collect_and_probe_current_view(
                                    page,
                                    app_name=app_name,
                                    page_name=page_name,
                                    timeout_ms=timeout_ms,
                                    widget_timeout_ms=widget_timeout_ms,
                                    interaction_mode=interaction_mode,
                                    action_button_policy=action_button_policy,
                                    upload_file=upload_file,
                                    restore_view=restore_view,
                                    known=known,
                                )
                            )
                    except Exception as exc:
                        probes.append(
                            WidgetProbe(
                                app_name,
                                page_label(page_name),
                                "tab",
                                f"tab #{index + 1}",
                                "failed",
                                _short_detail(f"tab sweep failed: {exc}"),
                                page.url,
                            )
                        )
    except Exception as exc:
        probes.append(WidgetProbe(app_name, page_label(page_name), "page", "", "failed", str(exc), target_url))

    failed = [probe for probe in probes if probe.status == "failed"]
    skipped = [probe for probe in probes if probe.status == "skipped"]
    probed = [probe for probe in probes if probe.status == "probed"]
    interacted = [probe for probe in probes if probe.status == "interacted"]
    return PageSweep(
        app=app_name,
        page=page_label(page_name),
        success=not failed and not skipped,
        duration_seconds=time.perf_counter() - started,
        widget_count=len(probes),
        interacted_count=len(interacted),
        probed_count=len(probed),
        skipped_count=len(skipped),
        failed_count=len(failed),
        url=getattr(page, "url", target_url),
        failures=failed[:20],
        skips=skipped[:20],
    )


def sweep_app(
    *,
    app: Path | str,
    pages: Sequence[str],
    timeout: float,
    widget_timeout: float,
    interaction_mode: str,
    action_button_policy: str,
    browser_name: str,
    headless: bool,
    screenshot_dir: Path | None,
) -> list[PageSweep]:
    web_robot = _load_web_robot()
    app_name = web_robot.active_app_slug(str(app))
    port = web_robot._free_port()
    base_url = f"http://127.0.0.1:{port}"
    local_active_app = web_robot.resolve_local_active_app(str(app), str(web_robot.DEFAULT_APPS_PATH))
    command = web_robot.build_streamlit_command(
        active_app=local_active_app,
        apps_path=web_robot.DEFAULT_APPS_PATH,
        port=port,
    )
    results: list[PageSweep] = []
    with web_robot.StreamlitServer(command, env=web_robot.build_server_env(), url=base_url):
        health = web_robot.wait_for_streamlit_health(base_url, timeout=timeout)
        if not health.success:
            return [
                PageSweep(
                    app=app_name,
                    page="SERVER",
                    success=False,
                    duration_seconds=health.duration_seconds,
                    widget_count=1,
                    interacted_count=0,
                    probed_count=0,
                    skipped_count=0,
                    failed_count=1,
                    url=health.url or base_url,
                    failures=[
                        WidgetProbe(app_name, "SERVER", "streamlit", "", "failed", health.detail, health.url or base_url)
                    ],
                    skips=[],
                )
            ]
        _, _, sync_playwright = web_robot._load_playwright()
        with sync_playwright() as playwright:
            browser_type = getattr(playwright, browser_name)
            browser = browser_type.launch(headless=headless)
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            try:
                page = context.new_page()
                with tempfile.TemporaryDirectory(prefix="agilab-widget-robot-") as tmp_dir:
                    upload_file = Path(tmp_dir) / "upload-fixture.txt"
                    upload_file.write_text("agilab widget robot fixture\n", encoding="utf-8")
                    for page_name in pages:
                        results.append(
                            sweep_page(
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
                                upload_file=upload_file,
                                screenshot_dir=screenshot_dir,
                            )
                        )
            finally:
                context.close()
                browser.close()
    return results


def summarize(pages: Sequence[PageSweep], *, app_count: int, target_seconds: float) -> WidgetSweepSummary:
    total = sum(page.duration_seconds for page in pages)
    widget_count = sum(page.widget_count for page in pages)
    interacted_count = sum(page.interacted_count for page in pages)
    probed_count = sum(page.probed_count for page in pages)
    skipped_count = sum(page.skipped_count for page in pages)
    failed_count = sum(page.failed_count for page in pages)
    success = bool(pages) and failed_count == 0 and skipped_count == 0
    return WidgetSweepSummary(
        success=success,
        total_duration_seconds=total,
        target_seconds=target_seconds,
        within_target=success and total <= target_seconds,
        app_count=app_count,
        page_count=len(pages),
        widget_count=widget_count,
        interacted_count=interacted_count,
        probed_count=probed_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        pages=list(pages),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate visible widgets across AGILAB public built-in apps through a real browser."
    )
    parser.add_argument(
        "--apps",
        default="all",
        help="Comma-separated built-in app names/paths, or 'all'. Default: all.",
    )
    parser.add_argument(
        "--pages",
        default="all",
        help="Comma-separated page routes, or 'all'. Default: HOME,PROJECT,ORCHESTRATE,PIPELINE,ANALYSIS.",
    )
    parser.add_argument("--browser", choices=("chromium", "firefox", "webkit"), default="chromium")
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--widget-timeout", type=float, default=DEFAULT_WIDGET_TIMEOUT_SECONDS)
    parser.add_argument(
        "--interaction-mode",
        choices=("actionability", "full"),
        default=DEFAULT_INTERACTION_MODE,
        help=(
            "actionability only verifies browser actionability; full performs real "
            "interactions for non-action widgets. Default: full."
        ),
    )
    parser.add_argument(
        "--action-button-policy",
        choices=("trial", "click"),
        default=DEFAULT_ACTION_BUTTON_POLICY,
        help=(
            "How to handle runtime action buttons in full mode. 'trial' avoids firing "
            "INSTALL/EXECUTE callbacks; 'click' really clicks them. Default: trial."
        ),
    )
    parser.add_argument("--target-seconds", type=float, default=DEFAULT_TARGET_SECONDS)
    parser.add_argument("--screenshot-dir")
    parser.add_argument("--json", action="store_true")
    return parser


def render_human(summary: WidgetSweepSummary) -> str:
    lines = [
        "AGILAB widget robot",
        f"verdict: {'PASS' if summary.success else 'FAIL'}",
        (
            "kpi: "
            f"total={summary.total_duration_seconds:.2f}s "
            f"target<={summary.target_seconds:.2f}s "
            f"within_target={'yes' if summary.within_target else 'no'}"
        ),
        (
            f"apps={summary.app_count} pages={summary.page_count} "
            f"widgets={summary.widget_count} interacted={summary.interacted_count} "
            f"probed={summary.probed_count} skipped={summary.skipped_count} "
            f"failed={summary.failed_count}"
        ),
    ]
    for page in summary.pages:
        status = "OK" if page.success else "FAIL"
        lines.append(
            f"- {page.app}/{page.page}: {status} "
            f"widgets={page.widget_count} interacted={page.interacted_count} "
            f"probed={page.probed_count} skipped={page.skipped_count} "
            f"failed={page.failed_count}"
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
    if args.interaction_mode == "actionability" and args.action_button_policy == "click":
        parser.error("--action-button-policy click only applies with --interaction-mode full")
    apps = resolve_apps(args.apps)
    pages = resolve_pages(args.pages)
    screenshot_dir = Path(args.screenshot_dir).expanduser().resolve() if args.screenshot_dir else None

    results: list[PageSweep] = []
    for app in apps:
        results.extend(
            sweep_app(
                app=app,
                pages=pages,
                timeout=args.timeout,
                widget_timeout=args.widget_timeout,
                interaction_mode=args.interaction_mode,
                action_button_policy=args.action_button_policy,
                browser_name=args.browser,
                headless=not args.headful,
                screenshot_dir=screenshot_dir,
            )
        )

    summary = summarize(results, app_count=len(apps), target_seconds=args.target_seconds)
    if args.json:
        print(json.dumps(asdict(summary), indent=2))
    else:
        print(render_human(summary))
    return 0 if summary.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
