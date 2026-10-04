import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import path from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { build } from "esbuild";

const directory = path.dirname(fileURLToPath(import.meta.url));
let scratch;
let MainInterface;
before(async () => {
  scratch = await mkdtemp(path.join(directory, ".agilab-home-journey-test-"));
  const output = path.join(scratch, "agilab_react_home_journey_render.mjs");
  await build({
    entryPoints: [path.join(directory, "agilab_react_main_interface.jsx")],
    outfile: output, bundle: true, format: "esm", platform: "node", packages: "external",
  });
  ({ MainInterface } = await import(pathToFileURL(output).href));
});
after(async () => { if (scratch) await rm(scratch, { recursive: true, force: true }); });

function render(overrides = {}) {
  const data = {
    brand: "AGILAB", welcome_title: "Run a project, explore its results",
    project: "flight_telemetry_project", projects: ["flight_telemetry_project"], route: "home",
    routes: [
      { id: "home", label: "HOME", primary: true, description: "" },
      { id: "workflow", label: "WORKFLOW", primary: true, description: "Edit your pipeline" },
      { id: "analysis", label: "ANALYSIS", primary: true, description: "Explore results" },
      { id: "settings", label: "SETTINGS", primary: false, description: "" },
    ], ...overrides,
  };
  return renderToStaticMarkup(React.createElement(MainInterface, {
    data, onAction: () => assert.fail("Rendering must not change project or start a run"),
  }));
}

test("default demo home keeps expert routes and notebook export collapsed", () => {
  const html = render();
  assert.match(html, /Run a project, explore its results/);
  const shortcuts = html.match(/<details class="agilab-home-shortcuts">([\s\S]*?)<\/details>/);
  assert.ok(shortcuts, "Workspace shortcuts must be a closed native details element");
  assert.match(shortcuts[1], /Workspace shortcuts and notebook export/);
  assert.match(shortcuts[1], /supported maps and charts in Jupyter/);
  assert.match(shortcuts[1], /Edit your pipeline/);
  assert.doesNotMatch(html.replace(shortcuts[0], ""), /Edit your pipeline/);
  assert.doesNotMatch(html, /Continue this project/);
  assert.match(html, /aria-label="Workspace navigation"/);
});

test("a selected custom project has a direct continuation and escaped identity", () => {
  const html = render({ project: "custom_<demo>_project", projects: ["custom_<demo>_project"] });
  assert.match(html, /Continue this project/);
  assert.match(html, /custom_&lt;demo&gt;_project/);
  assert.doesNotMatch(html, /<demo>/);
});

test("continuation is unavailable without the server-registered workflow route", () => {
  const html = render({ project: "custom_project", routes: [{ id: "home", label: "HOME", primary: true }] });
  assert.doesNotMatch(html, /Continue this project/);
});

test("other workspaces retain navigation without duplicate home onboarding", () => {
  const html = render({ route: "analysis" });
  assert.match(html, /aria-current="page"[^>]*>ANALYSIS/);
  assert.doesNotMatch(html, /agilab-workspace-home/);
});
