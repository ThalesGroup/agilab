import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import path from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { build } from "esbuild";

const directory = path.dirname(fileURLToPath(import.meta.url));
let scratch, PythonViewApp, MainInterface;
before(async () => {
  scratch = await mkdtemp(path.join(directory, ".agilab-contextual-tools-test-"));
  for (const stem of ["agilab_react_python_host", "agilab_react_main_interface"]) {
    await build({
      entryPoints: [path.join(directory, stem + ".jsx")],
      outfile: path.join(scratch, stem + ".mjs"),
      bundle: true, format: "esm", platform: "node", external: ["react", "react-dom/*"],
      loader: { ".css": "empty" },
    });
  }
  // The browser bootstrap is inert when no host mount exists.
  const previousDocument = globalThis.document;
  globalThis.document = { compatMode: "CSS1Compat", getElementById: () => null };
  try {
    ({ PythonViewApp } = await import(pathToFileURL(path.join(scratch, "agilab_react_python_host.mjs")).href));
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  }
  ({ MainInterface } = await import(pathToFileURL(path.join(scratch, "agilab_react_main_interface.mjs")).href));
});
after(async () => { if (scratch) await rm(scratch, { recursive: true, force: true }); });

const node = (id, kind, props = {}, children = []) => ({ id, kind, props, children });
const workspace = {
  brand: "AGILAB", project: "owned_preview_project", projects: ["owned_preview_project"],
  route: "home", welcome_title: "Owned preview", routes: [
    { id: "home", label: "HOME", primary: true },
    { id: "analysis", label: "ANALYSIS", primary: true },
    { id: "settings", label: "SETTINGS", primary: false },
  ],
};
function host(main = [], sidebar = []) {
  return renderToStaticMarkup(React.createElement(PythonViewApp, {
    transport: {}, initialPayload: { path: "/", query: {}, config: {}, nodes: { main, sidebar } },
  }));
}

test("empty Python sidebar has no panel or fallback Tools control", () => {
  const html = host([node("body", "text", { body: "Full-width workspace" })]);
  assert.match(html, /Full-width workspace/);
  assert.doesNotMatch(html, /data-region="sidebar"|py-sidebar-toggle|py-with-sidebar|Close tools/);
});

test("standalone contextual controls start hidden without reserving a desktop column", () => {
  const labels = ["Python editor", "Create project", "Delete project", "Dataframe", "Pipeline", "Environment"];
  const html = host([], labels.map((label, index) => node("control-" + index, "text", { body: label })));
  assert.match(html, /<aside[^>]*aria-label="Contextual tools"[^>]*hidden=""/);
  assert.doesNotMatch(html, /py-with-sidebar|>Menu</);
  assert.match(html, /class="py-sidebar-toggle" aria-expanded="false" aria-controls="[^"]+">Tools</);
  for (const label of labels) assert.ok(html.includes(label), label + " must remain mounted");
  assert.equal((html.match(/>Tools<\/button>/g) || []).length, 1);
});

test("workspace header owns Tools without a duplicate host toggle", () => {
  const header = node("header", "component", {
    name: "agilab_react_main_interface", data: workspace, js: "/owned-main.js", css: "/owned-main.css",
  });
  const html = host([node("group", "container", {}, [header])], [node("control", "text", { body: "Project commands" })]);
  assert.match(html, /data-region="sidebar"/);
  assert.doesNotMatch(html, /py-sidebar-toggle|>Menu</);
});

test("workspace disclosure reflects host visibility and retains secondary navigation", () => {
  for (const open of [false, true]) {
    const html = renderToStaticMarkup(React.createElement(MainInterface, {
      data: { ...workspace, route: "analysis" },
      onAction: () => assert.fail("Rendering must not dispatch a Python action"),
      toolsPanel: { available: true, open, setOpen: () => assert.fail("Rendering must not toggle tools") },
    }));
    assert.match(html, new RegExp('aria-expanded="' + open + '">Tools</summary>'));
    assert.match(html, /SETTINGS/);
    assert.equal(/class="agilab-workspace-tools" open=""/.test(html), open);
    assert.doesNotMatch(html, /aria-controls=/, "ID references cannot cross the component shadow root");
  }
});

test("without contextual controls the existing native disclosure remains available", () => {
  const html = renderToStaticMarkup(React.createElement(MainInterface, {
    data: workspace, onAction: () => {},
    toolsPanel: { available: false, open: false, setOpen: () => assert.fail("No panel exists") },
  }));
  assert.ok(html.includes('<details class="agilab-workspace-tools"><summary>Tools</summary>'));
  assert.match(html, /SETTINGS/);
});
