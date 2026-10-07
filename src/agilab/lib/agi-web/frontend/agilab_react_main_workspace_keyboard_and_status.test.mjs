import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { after, afterEach, before, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import React, { act } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { build } from "esbuild";
import { JSDOM } from "jsdom";

const directory = path.dirname(fileURLToPath(import.meta.url));
const globals = new Map();
let dom, scratch, mountPythonView, ProjectWorkspace, mainModuleURL, disposeOwnedMainInterfaces, cleanup;
const node = (id, kind, props = {}) => ({ id, kind, props, children: [] });
const project = "owned_keyboard_project";
const routes = [
  { id: "home", label: "HOME", primary: true },
  { id: "project", label: "PROJECT", primary: true },
  { id: "analysis", label: "ANALYSIS", primary: true },
  { id: "settings", label: "SETTINGS", primary: false },
];
function expose(name, value) {
  globals.set(name, Object.getOwnPropertyDescriptor(globalThis, name));
  Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
}
before(async () => {
  dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "https://agilab-workspace-ux.invalid/" });
  for (const name of ["window", "document", "navigator", "location", "history", "HTMLElement", "Event", "KeyboardEvent"])
    expose(name, name === "window" ? dom.window : dom.window[name]);
  expose("IS_REACT_ACT_ENVIRONMENT", true);
  scratch = await mkdtemp(path.join(directory, ".agilab-workspace-keyboard-test-"));
  for (const stem of ["agilab_react_main_interface", "agilab_react_python_host"]) {
    await build({ entryPoints: [path.join(directory, stem + ".jsx")],
      outfile: path.join(scratch, stem + ".mjs"), bundle: true, format: "esm", platform: "node",
      external: ["react", "react-dom/*"], loader: { ".css": "empty" } });
  }
  ({ ProjectWorkspace } = await import(pathToFileURL(path.join(scratch, "agilab_react_main_interface.mjs")).href));
  // Dispose the test's independent island roots before the outer React host.
  // This preserves real interaction code without unmounting a root during another root's teardown.
  const ownedMainModule = path.join(scratch, "agilab_owned_main_workspace_test_fixture.mjs");
  await writeFile(ownedMainModule, `
    import mount from "./agilab_react_main_interface.mjs";
    const live = new Map();
    export function disposeOwnedMainInterfaces() {
      for (const [parent, dispose] of live) { live.delete(parent); dispose(); }
    }
    export default function(options) {
      const dispose = mount(options);
      live.set(options.parentElement, dispose);
      return () => {
        if (live.get(options.parentElement) === dispose) {
          live.delete(options.parentElement); dispose();
        }
      };
    }
  `);
  mainModuleURL = pathToFileURL(ownedMainModule).href;
  ({ disposeOwnedMainInterfaces } = await import(mainModuleURL));
  ({ mountPythonView } = await import(pathToFileURL(path.join(scratch, "agilab_react_python_host.mjs")).href));
});
afterEach(async () => {
  if (disposeOwnedMainInterfaces) await act(() => disposeOwnedMainInterfaces());
  if (cleanup) { await act(() => cleanup()); cleanup = null; }
  document.body.replaceChildren();
});
after(async () => {
  dom?.window.close();
  if (scratch) await rm(scratch, { recursive: true, force: true });
  for (const [name, descriptor] of globals) {
    if (descriptor) Object.defineProperty(globalThis, name, descriptor); else delete globalThis[name];
  }
});
function island(id, data) {
  return node(id, "component", { name: "agilab_react_main_interface", data,
    js: mainModuleURL, css: "https://agilab-workspace-ux.invalid/main.css", isolate_styles: true });
}
async function mountWorkspace(route) {
  const shell = { brand: "AGILAB", project, projects: [project], route, routes };
  const content = route === "project"
    ? { view: "project_workspace", project, project_path: "/owned/project", route, cards: [],
        actions: [{ id: "orchestrate", label: "Run project", description: "Configure a run." }] }
    : { view: "analysis_workspace", project, project_path: "/owned/project", route, context: "owned-analysis",
        draft_views: [], draft_notebooks: [], selected_views: [], selected_notebooks: [],
        views: [], notebooks: [], overview: { cards: [] }, export_available: true };
  const element = document.createElement("div"); document.body.append(element);
  await act(async () => {
    cleanup = mountPythonView(element, { initialPayload: {
      revision: 1, csrf_token: "owned-keyboard-token", path: "/" + route.toUpperCase(), query: {}, config: {},
      nodes: { main: [island("header", shell), island("workspace", content)],
        sidebar: [node("settings", "caption", { body: "Contextual project settings" })] },
    }, transport: { action: () => assert.fail("Keyboard dismissal must not execute a Python action") } });
  });
  const roots = [...element.querySelectorAll(".py-island")].map(item => item.shadowRoot);
  const summary = roots[0].querySelector("summary");
  assert.ok(summary, "The real main interface must have mounted in its shadow root.");
  await act(async () => {
    summary.click();
    await new Promise(resolve => setTimeout(resolve, 0));
  });
  assert.equal(element.querySelector("aside").hidden, false);
  return { element, roots, summary };
}
for (const route of ["project", "analysis"]) {
  test(`${route} content lets Escape close native Tools and restore focus across shadow roots`, async () => {
    const { element, roots, summary } = await mountWorkspace(route);
    const action = [...roots[1].querySelectorAll("button")].find(button => !button.disabled);
    assert.ok(action, "The focus target must be an enabled workspace action.");
    action.focus();
    assert.equal(roots[1].activeElement, action);
    await act(() => action.dispatchEvent(new KeyboardEvent("keydown", {
      key: "Tab", bubbles: true, composed: true, cancelable: true,
    })));
    assert.equal(element.querySelector("aside").hidden, false, "Other keys must keep Tools open.");
    await act(() => action.dispatchEvent(new KeyboardEvent("keydown", {
      key: "Escape", bubbles: true, composed: true, cancelable: true,
    })));
    assert.equal(element.querySelector("aside").hidden, true);
    assert.equal(roots[0].activeElement, summary, "Focus returns to the Tools disclosure.");
    assert.equal(summary.getAttribute("aria-expanded"), "false");
    assert.match(element.querySelector("aside").textContent, /Contextual project settings/,
      "Dismissal retains the native controls and their state.");
  });
}
test("normal onboarding cards retain evidence while only broken prerequisites ask for attention", () => {
  const cards = [
    { label: "API keys", value: "Optional", caption: "no online provider key found",
      state: "incomplete", display_state: "neutral", status_label: "Optional" },
    { label: "Runs", value: "0", caption: "no run logs yet",
      state: "incomplete", display_state: "neutral", status_label: "No runs yet" },
    { label: "Manager env", value: "missing", caption: ".venv in owned_project", state: "incomplete" },
  ];
  const html = renderToStaticMarkup(React.createElement(ProjectWorkspace, {
    data: { project, cards, actions: [] }, onAction: () => assert.fail("Rendering must not dispatch an action"),
  }));
  assert.equal((html.match(/>Needs attention</g) || []).length, 1);
  assert.equal((html.match(/agilab-health-card--neutral/g) || []).length, 2);
  for (const card of cards) {
    assert.ok(html.includes(card.label));
    assert.ok(html.includes(card.value));
    assert.ok(html.includes(card.caption));
  }
  assert.match(html, />Optional<\/small>/);
  assert.match(html, />No runs yet<\/small>/);
});
