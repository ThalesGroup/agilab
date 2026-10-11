import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import path from "node:path";
import { after, afterEach, before, beforeEach, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import React, { act } from "react";
import { build } from "esbuild";
import { JSDOM } from "jsdom";

const directory = path.dirname(fileURLToPath(import.meta.url));
const globals = new Map();
let dom, scratch, root, element, createRoot, MainInterface, workbenchLayoutKey, normalizeWorkbenchLayout;
const actions = [];
const routes = [
  { id: "home", label: "HOME", primary: true },
  { id: "workflow", label: "WORKFLOW", primary: true },
  { id: "orchestrate", label: "ORCHESTRATE", primary: true },
  { id: "settings", label: "SETTINGS", primary: false },
];
function payload(project = "owned_local_project", overrides = {}) {
  return { brand: "AGILAB", welcome_title: "Run a project, explore its results", project,
    projects: [...new Set([project, "other_project"])], routes, route: "home", workbench: { schema_version: 1,
      profiles: [
        { id: "local", label: "Local app", description: "Review local settings before running.", route: "workflow", pane_id: "context" },
        { id: "cluster", label: "Cluster", description: "Review workers and deployment.", route: "orchestrate", pane_id: "diagnostics" },
        { id: "notebook", label: "Notebook", description: "Export an editable Python notebook.", route: "workflow", pane_id: "commands" },
      ],
      commands: [
        { id: "open_notebook", label: "Open notebook export", description: "Open Workflow; no pipeline execution.", kind: "navigate", value: "workflow" },
        { id: "install_app", label: "Install app", description: "Resolve or download project dependencies using ORCHESTRATE.", kind: "orchestrate_action", value: "install", requires_review: true },
        { id: "run_app", label: "Run configured project", description: "Use the current project settings in ORCHESTRATE.", kind: "orchestrate_action", value: "run", requires_review: true },
        { id: "disabled_command", label: "Unavailable command", kind: "navigate", value: "settings", disabled: true, reason: "Unavailable for this project" },
      ],
      diagnostics: [{ id: "worker", label: "Worker environment", value: "Not inspected" }],
      panes: [
        { id: "context", label: "Context", kind: "context" },
        { id: "diagnostics", label: "Diagnostics", kind: "diagnostics" },
        { id: "commands", label: "Profile commands", kind: "commands" },
      ], ...overrides } };
}
function expose(name, value) {
  globals.set(name, Object.getOwnPropertyDescriptor(globalThis, name));
  Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
}
before(async () => {
  dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "https://agilab-operator-workbench.invalid/" });
  for (const name of ["window", "document", "navigator", "HTMLElement", "HTMLInputElement", "Event", "KeyboardEvent"])
    expose(name, name === "window" ? dom.window : dom.window[name]);
  expose("IS_REACT_ACT_ENVIRONMENT", true);
  ({ createRoot } = await import("react-dom/client"));
  // jsdom does not implement the browser's modal dialog methods.
  dom.window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  dom.window.HTMLDialogElement.prototype.close = function () { this.open = false; this.dispatchEvent(new Event("close")); };
  scratch = await mkdtemp(path.join(directory, ".agilab-operator-workbench-test-"));
  const outfile = path.join(scratch, "agilab_operator_workbench_behavior_module.mjs");
  await build({ entryPoints: [path.join(directory, "agilab_react_main_interface.jsx")], outfile,
    bundle: true, format: "esm", platform: "node", packages: "external" });
  ({ MainInterface, workbenchLayoutKey, normalizeWorkbenchLayout } = await import(pathToFileURL(outfile).href));
});
beforeEach(() => { actions.length = 0; window.localStorage.clear(); });
afterEach(async () => { if (root) await act(async () => root.unmount()); root = null; document.body.replaceChildren(); });
after(async () => {
  if (scratch) await rm(scratch, { recursive: true, force: true });
  dom.window.close();
  for (const [name, descriptor] of globals) {
    if (descriptor) Object.defineProperty(globalThis, name, descriptor); else delete globalThis[name];
  }
});
async function render(data = payload()) {
  if (!root) { element = document.createElement("div"); document.body.append(element); root = createRoot(element); }
  await act(async () => root.render(React.createElement(MainInterface, { data, onAction: value => actions.push(value) })));
}
function button(text, within = element) {
  const found = [...within.querySelectorAll("button")].find(item => item.textContent.trim() === text);
  assert.ok(found, `Expected button: ${text}`); return found;
}
async function click(text, within = element) { await act(async () => button(text, within).click()); }
async function select(label, value) {
  const targetLabel = [...element.querySelectorAll("label")].find(item => item.textContent === label);
  assert.ok(targetLabel, `Expected select label: ${label}`);
  const control = document.getElementById(targetLabel.htmlFor);
  assert.equal(control.tagName, "SELECT", "Workbench control must have its own label");
  await act(async () => { control.value = value; control.dispatchEvent(new Event("change", { bubbles: true })); });
}
async function shortcut(options = { ctrlKey: true }) {
  await act(async () => document.dispatchEvent(new KeyboardEvent("keydown", { key: "k", bubbles: true, cancelable: true, ...options })));
}

test("profile discovery and changes do not execute; opening uses the existing route dispatcher", async () => {
  await render(); assert.deepEqual(actions, []);
  await select("Profile", "cluster"); assert.deepEqual(actions, []);
  assert.match(element.textContent, /Review workers and deployment/);
  await click("Open Cluster");
  assert.deepEqual(actions, [{ kind: "navigate", value: "orchestrate", project: "owned_local_project", route: "home" }]);
});

test("global Cmd/Ctrl K opens a labelled modal, keyboard dispatches a read-only command and restores focus", async () => {
  await render(); const otherInput = document.createElement("input"); document.body.append(otherInput); otherInput.focus();
  await shortcut({ metaKey: true });
  const dialog = element.querySelector("dialog"); assert.equal(dialog.open, true);
  assert.equal(document.activeElement.getAttribute("role"), "combobox");
  assert.match(document.getElementById(dialog.getAttribute("aria-labelledby")).textContent, /Workspace commands/);
  await act(async () => document.activeElement.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true })));
  assert.deepEqual(actions, [{ kind: "workbench_command", value: "open_notebook", project: "owned_local_project", route: "home" }]);
  assert.equal(dialog.open, false); assert.equal(document.activeElement, otherInput);
});

test("the isolated native component restores its shadow focus and scrolls keyboard selection inside its own dialog", async () => {
  const host = document.createElement("div"); document.body.append(host);
  const shadow = host.attachShadow({ mode: "open" });
  element = document.createElement("div"); shadow.append(element); root = createRoot(element);
  await render();
  const trigger = button("Commands ⌘/Ctrl K"), scrolled = [];
  for (const option of element.querySelectorAll("[role=option]")) option.scrollIntoView = () => scrolled.push(option.textContent);
  trigger.focus(); await act(async () => trigger.click());
  const search = element.querySelector("[role=combobox]");
  assert.equal(shadow.activeElement, search);
  await act(async () => search.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, composed: true, cancelable: true })));
  assert.match(scrolled.at(-1), /Install app/);
  await act(async () => search.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, composed: true, cancelable: true })));
  assert.equal(shadow.activeElement, trigger); assert.deepEqual(actions, []);
});

test("mutating command selection only reviews; cancel emits nothing and explicit Execute emits reviewed registry ID", async () => {
  await render(); await shortcut();
  await click("Install appResolve or download project dependencies using ORCHESTRATE.Review required");
  assert.deepEqual(actions, []); assert.match(element.querySelector("dialog").textContent, /Review command/);
  assert.match(element.querySelector("dialog").textContent, /owned_local_project/);
  await click("Close"); assert.deepEqual(actions, []);
  await shortcut(); await click("Install appResolve or download project dependencies using ORCHESTRATE.Review required");
  await click("Execute command");
  assert.deepEqual(actions, [{ kind: "workbench_command", value: "install_app", project: "owned_local_project", route: "home", reviewed: true }]);
});

test("a changed command cannot execute under an earlier review", async () => {
  const data = payload(); await render(data); await shortcut();
  await click("Run configured projectUse the current project settings in ORCHESTRATE.Review required");
  const commands = data.workbench.commands.map(item => item.id === "run_app" ? { ...item, value: "install" } : item);
  await render(payload("owned_local_project", { commands }));
  assert.equal(button("Execute command").disabled, true);
  assert.match(element.querySelector("dialog").textContent, /command or project changed/);
  await click("Execute command"); assert.deepEqual(actions, []);
});

test("layout is bounded, validated against discovery and persisted separately for each project", async () => {
  window.localStorage.setItem(workbenchLayoutKey("owned_local_project"), JSON.stringify({ version: 1,
    profile_id: "unknown", pane_id: "javascript:bad", split: "yes", secret: "not retained" }));
  await render();
  let layout = JSON.parse(window.localStorage.getItem(workbenchLayoutKey("owned_local_project")));
  assert.deepEqual(layout, { version: 1, profile_id: "local", split: false, pane_id: "context" });
  await select("Profile", "cluster"); await click("Show pane");
  layout = JSON.parse(window.localStorage.getItem(workbenchLayoutKey("owned_local_project")));
  assert.deepEqual(layout, { version: 1, profile_id: "cluster", split: true, pane_id: "diagnostics" });
  assert.match(element.querySelector("aside").textContent, /Worker environmentNot inspected/);
  await render(payload("other_project"));
  assert.equal(element.querySelector(".agilab-workbench-toolbar select").value, "local");
  assert.equal(element.querySelector("aside"), null);
  await render(payload());
  assert.equal(element.querySelector(".agilab-workbench-toolbar select").value, "cluster");
  assert.deepEqual(actions, []);
});

test("corrupt, oversized and obsolete browser layout state falls back without executing discovery", async () => {
  for (const text of ["{broken", "x".repeat(5000), JSON.stringify({ version: 0, profile_id: "cluster", split: true })]) {
    window.localStorage.setItem(workbenchLayoutKey("owned_local_project"), text);
    await render(payload());
    assert.equal(element.querySelector(".agilab-workbench-toolbar select").value, "local");
    await act(async () => root.unmount()); root = null; element.remove();
  }
  assert.deepEqual(actions, []);
  assert.deepEqual(normalizeWorkbenchLayout({ version: 1, profile_id: "notebook", split: true }, payload().workbench),
    { version: 1, profile_id: "notebook", split: true, pane_id: "commands" });
});

test("Escape closes the palette without triggering navigation or an execution", async () => {
  await render(); await shortcut();
  await act(async () => document.activeElement.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })));
  assert.equal(element.querySelector("dialog").open, false); assert.deepEqual(actions, []);
});

test("a queued native close event cannot close a palette reopened after Escape", async () => {
  const prototype = dom.window.HTMLDialogElement.prototype, originalClose = prototype.close;
  const queuedCloseEvents = [];
  prototype.close = function () { this.open = false; queuedCloseEvents.push(this); };
  try {
    await render(); await shortcut();
    const dialog = element.querySelector("dialog"); assert.equal(dialog.open, true);
    await act(async () => document.activeElement.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })));
    assert.equal(dialog.open, false); assert.equal(queuedCloseEvents.length, 1);
    await shortcut(); assert.equal(dialog.open, true);
    await act(async () => queuedCloseEvents.shift().dispatchEvent(new Event("close")));
    assert.equal(dialog.open, true, "Closing the previous modal must not dismiss its new open cycle");
    assert.deepEqual(actions, []);
  } finally { prototype.close = originalClose; }
});

test("an actual native dialog close updates state and the palette can open again", async () => {
  await render(); await shortcut();
  const dialog = element.querySelector("dialog");
  await act(async () => dialog.close()); assert.equal(dialog.open, false);
  await shortcut(); assert.equal(dialog.open, true); assert.deepEqual(actions, []);
});

test("command search filters without executing and keyboard skips disabled results", async () => {
  await render(); await shortcut();
  const search = document.activeElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(search, "notebook");
    search.dispatchEvent(new Event("input", { bubbles: true }));
  });
  assert.equal(element.querySelectorAll("[role=option]").length, 1);
  assert.match(element.querySelector("[role=option]").textContent, /Open notebook export/);
  assert.deepEqual(actions, []);
  await click("Close");
  const commands = [{ id: "blocked", label: "Blocked first", kind: "navigate", value: "settings", disabled: true },
    ...payload().workbench.commands];
  await render(payload("owned_local_project", { commands })); await shortcut();
  const selected = document.getElementById(document.activeElement.getAttribute("aria-activedescendant"));
  assert.match(selected.textContent, /Open notebook export/);
  await act(async () => document.activeElement.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true })));
  const next = document.getElementById(document.activeElement.getAttribute("aria-activedescendant"));
  assert.match(next.textContent, /Install app/); assert.deepEqual(actions, []);
});

test("a project change discards the pending review and storage denial still allows navigation", async () => {
  await render(); await shortcut();
  await click("Install appResolve or download project dependencies using ORCHESTRATE.Review required");
  await render(payload("other_project"));
  assert.equal(element.querySelector("dialog").open, false); assert.deepEqual(actions, []);
  const storagePrototype = Object.getPrototypeOf(window.localStorage);
  const originalGet = storagePrototype.getItem, originalSet = storagePrototype.setItem;
  storagePrototype.getItem = () => { throw new Error("Storage disabled"); };
  storagePrototype.setItem = () => { throw new Error("Storage disabled"); };
  try {
    await render(payload("storage_denied_project"));
    await click("Open Local app");
    assert.deepEqual(actions, [{ kind: "navigate", value: "workflow", project: "storage_denied_project", route: "home" }]);
  } finally { storagePrototype.getItem = originalGet; storagePrototype.setItem = originalSet; }
});

test("pages without the versioned workbench contract preserve the current navigation", async () => {
  const data = payload(); delete data.workbench; await render(data);
  assert.equal(element.querySelector(".agilab-operator-workbench"), null);
  await shortcut(); assert.equal(element.querySelector("dialog"), null);
  await click("WORKFLOW");
  assert.deepEqual(actions, [{ kind: "navigate", value: "workflow", project: "owned_local_project", route: "home" }]);
});
