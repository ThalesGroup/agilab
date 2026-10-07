import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import path from "node:path";
import { after, afterEach, before, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import React, { act } from "react";
import { build } from "esbuild";
import { JSDOM } from "jsdom";

const directory = path.dirname(fileURLToPath(import.meta.url));
const savedGlobals = new Map();
let scratch, dom, createRoot, CoordinateMap, AnalysisCurves;
const mounted = [];
function expose(name, value) {
  savedGlobals.set(name, Object.getOwnPropertyDescriptor(globalThis, name));
  Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
}
before(async () => {
  dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "https://agilab-analysis-test.invalid/" });
  for (const name of ["window", "document", "navigator", "HTMLElement", "HTMLInputElement", "Event", "KeyboardEvent"])
    expose(name, name === "window" ? dom.window : dom.window[name]);
  expose("IS_REACT_ACT_ENVIRONMENT", true);
  ({ createRoot } = await import("react-dom/client"));
  scratch = await mkdtemp(path.join(directory, ".agilab-analysis-low-power-test-"));
  const outfile = path.join(scratch, "agilab_react_analysis_low_power_test_module.mjs");
  // The override supports running the same interaction regression against an owned historical source copy.
  await build({
    entryPoints: [process.env.AGILAB_ANALYSIS_COMPONENT_TEST_SOURCE || path.join(directory, "agilab_react_analysis_components.jsx")],
    outfile, bundle: true, format: "esm", platform: "node", external: ["react", "react-dom/*"],
  });
  ({ CoordinateMap, AnalysisCurves } = await import(pathToFileURL(outfile).href));
});
afterEach(async () => {
  for (const { root, element } of mounted.splice(0)) {
    await act(async () => root.unmount());
    element.remove();
  }
});
after(async () => {
  if (scratch) await rm(scratch, { recursive: true, force: true });
  dom?.window.close();
  for (const [name, descriptor] of savedGlobals) {
    if (descriptor) Object.defineProperty(globalThis, name, descriptor);
    else delete globalThis[name];
  }
});
async function mount(Component, props) {
  const element = document.createElement("div");
  document.body.appendChild(element);
  const root = createRoot(element);
  mounted.push({ root, element });
  const render = async next => { await act(async () => root.render(React.createElement(Component, next))); };
  await render(props);
  return { element, render };
}
async function click(element) {
  await act(async () => element.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })));
}
async function key(element, value) {
  await act(async () => element.dispatchEvent(new KeyboardEvent("keydown", { key: value, bubbles: true, cancelable: true })));
}
async function changeValue(element, value) {
  await act(async () => {
    const prototype = element.tagName === "SELECT" ? dom.window.HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value").set.call(element, String(value));
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  });
}
function resetButton(element) { return [...element.querySelectorAll("button")].find(button => button.textContent === "Reset view"); }
function mapPayload(count = 160) {
  const reads = { coordinates: 0 };
  const points = Array.from({ length: count }, (_, row) => ({
    row, label: `Position ${row}`, group: row % 2 ? "Odd" : "Even",
    get latitude() { reads.coordinates++; return row / 10; },
    get longitude() { reads.coordinates++; return row / 5; },
  }));
  return { payload: { points }, reads };
}
function curvesPayload(count = 80) {
  const reads = { coordinates: 0, values: 0 };
  const rows = Array.from({ length: count }, (_, row) => ({
    row, label: `Row ${row}`,
    get x() { reads.coordinates++; return row; },
    values: {
      get a() { reads.values++; return row === 20 ? null : row * 2; },
      get b() { reads.values++; return row === 30 ? null : row * 3; },
    },
  }));
  return { payload: { rows, series: [{ id: "a", label: "Series A" }, { id: "b", label: "Series B" }],
    x_type: "number", x_label: "Elapsed", y_label: "Reading" }, reads };
}

test("map selection preserves geometry and updates only the old and new selection strokes", async t => {
  const { payload, reads } = mapPayload();
  const selections = [];
  const { element } = await mount(CoordinateMap, { payload, payloadKey: "map:1", onSelection: value => selections.push(value) });
  const circles = [...element.querySelectorAll("circle")];
  assert.equal(circles.length, payload.points.length);
  const geometry = circles.map(circle => [circle.getAttribute("cx"), circle.getAttribute("cy"), circle.getAttribute("r")]);
  reads.coordinates = 0;
  await click(circles[4]);
  assert.ok(reads.coordinates <= 12, `point selection reread ${reads.coordinates} coordinates`);
  t.diagnostic(`Map selection: ${reads.coordinates} coordinate reads for ${payload.points.length} retained positions.`);
  assert.deepEqual(selections.at(-1), { row: 4, label: "Position 4", latitude: .4, longitude: .8 });
  assert.match(element.querySelector("output").textContent, /Position 4: latitude 0.4, longitude 0.8/);
  assert.equal(circles[4].getAttribute("stroke"), "currentColor");
  const mutations = [];
  const observer = new dom.window.MutationObserver(records => mutations.push(...records));
  observer.observe(element.querySelector("svg"), { subtree: true, attributes: true });
  reads.coordinates = 0;
  await key(circles[9], " ");
  observer.disconnect();
  assert.ok(reads.coordinates <= 12, `keyboard selection reread ${reads.coordinates} coordinates`);
  assert.equal(selections.at(-1).row, 9);
  assert.equal(circles[4].getAttribute("stroke"), "none");
  assert.equal(circles[9].getAttribute("stroke"), "currentColor");
  assert.deepEqual(mutations.map(record => record.attributeName), ["stroke", "stroke"]);
  assert.deepEqual([...element.querySelectorAll("circle")], circles);
  assert.deepEqual(circles.map(circle => [circle.getAttribute("cx"), circle.getAttribute("cy"), circle.getAttribute("r")]), geometry);
  await key(circles[12], "Enter");
  assert.equal(selections.at(-1).row, 12);
});

test("map group, zoom and reset invalidate geometry without omitting positions", async () => {
  const { payload, reads } = mapPayload(40);
  const selections = [];
  const { element } = await mount(CoordinateMap, { payload, payloadKey: "map:1", onSelection: value => selections.push(value) });
  await click(element.querySelector("circle"));
  reads.coordinates = 0;
  await changeValue(element.querySelector("select"), "1");
  assert.equal(element.querySelectorAll("circle").length, 20);
  assert.equal(element.querySelector("circle").getAttribute("aria-label"), "Position Position 1");
  assert.ok(reads.coordinates > 20);
  assert.deepEqual(selections.at(-1), {});
  const first = element.querySelector("circle"), oldX = first.getAttribute("cx");
  await changeValue(element.querySelector('input[aria-label="Map zoom"]'), 2);
  assert.notEqual(first.getAttribute("cx"), oldX);
  assert.equal(Number(first.getAttribute("r")), 4 / Math.sqrt(2));
  await click(resetButton(element));
  assert.equal(element.querySelectorAll("circle").length, 40);
  assert.equal(element.querySelector("select").value, "");
  assert.equal(element.querySelector('input[aria-label="Map zoom"]').value, "1");
  assert.deepEqual(selections.at(-1), {});
});

test("curve selection does not rebuild paths or reread the full series", async t => {
  const { payload, reads } = curvesPayload();
  const selections = [];
  const { element } = await mount(AnalysisCurves, { payload, payloadKey: "curves:1", onSelection: value => selections.push(value) });
  const circles = [...element.querySelectorAll("circle")], paths = [...element.querySelectorAll("path")];
  assert.equal(circles.length, 158);
  assert.equal(paths.length, 2);
  assert.equal((paths[0].getAttribute("d").match(/M/g) || []).length, 2, "missing values must break the curve");
  const geometry = paths.map(path => path.getAttribute("d"));
  reads.coordinates = 0; reads.values = 0;
  await click(circles[0]);
  assert.equal(reads.coordinates, 1, "selection must read only the chosen x coordinate");
  assert.equal(reads.values, 2, "selection must read only the chosen value and label value");
  t.diagnostic(`Curve selection: ${reads.coordinates} x coordinate and ${reads.values} value reads for ${payload.rows.length} retained rows and two series.`);
  assert.deepEqual(selections.at(-1), { row: 0, series: "a", x: 0, y: 0, label: "Series A — Row 0: 0" });
  await key(circles.at(-1), "Enter");
  assert.equal(selections.at(-1).row, 79);
  assert.equal(selections.at(-1).series, "b");
  assert.equal(element.querySelector("output").textContent, "Series B — Row 79: 237");
  assert.deepEqual([...element.querySelectorAll("circle")], circles);
  assert.deepEqual([...element.querySelectorAll("path")], paths);
  assert.deepEqual(paths.map(path => path.getAttribute("d")), geometry);
});

test("curve series and range controls still redraw the selected data and reset missing-value gaps", async () => {
  const { payload, reads } = curvesPayload();
  const selections = [];
  const { element } = await mount(AnalysisCurves, { payload, payloadKey: "curves:1", onSelection: value => selections.push(value) });
  await click(element.querySelector("circle"));
  reads.coordinates = 0;
  await click(element.querySelector('input[type="checkbox"]'));
  assert.equal(element.querySelectorAll("path").length, 1);
  assert.equal(element.querySelectorAll("circle").length, 79);
  assert.ok(reads.coordinates > 79);
  assert.deepEqual(selections.at(-1), {});
  await changeValue(element.querySelector('input[aria-label="Range start"]'), 32);
  await changeValue(element.querySelector('input[aria-label="Range end"]'), 45);
  assert.equal(element.querySelectorAll("circle").length, 14);
  assert.equal(element.querySelector("circle").getAttribute("aria-label"), "Series B Row 32");
  await click(resetButton(element));
  assert.equal(element.querySelectorAll("path").length, 2);
  assert.equal(element.querySelectorAll("circle").length, 158);
  assert.equal(element.querySelector('input[aria-label="Range start"]').value, "0");
  assert.equal(element.querySelector('input[aria-label="Range end"]').value, "79");
  assert.deepEqual(selections.at(-1), {});
});

test("payload-key replacement resets map filters, selection and geometry even with the same payload object", async () => {
  const { payload } = mapPayload(8);
  const selections = [], onSelection = value => selections.push(value);
  const { element, render } = await mount(CoordinateMap, { payload, payloadKey: "map:1", onSelection });
  await changeValue(element.querySelector("select"), "1");
  await changeValue(element.querySelector('input[aria-label="Map zoom"]'), 2);
  await click(element.querySelector("circle"));
  payload.points = [{ row: 41, label: "Replacement", latitude: 48.9, longitude: 2.4, group: "New" }];
  await render({ payload, payloadKey: "map:2", onSelection });
  assert.equal(element.querySelectorAll("circle").length, 1);
  assert.equal(element.querySelector("circle").getAttribute("aria-label"), "Position Replacement");
  assert.equal(element.querySelector("select").value, "");
  assert.equal(element.querySelector('input[aria-label="Map zoom"]').value, "1");
  assert.deepEqual(selections.at(-1), {});
  await click(element.querySelector("circle"));
  assert.deepEqual(selections.at(-1), { row: 41, label: "Replacement", latitude: 48.9, longitude: 2.4 });
});

test("payload-key replacement resets curves and preserves UTC labels and the current selection callback", async () => {
  const { payload } = curvesPayload(8);
  const firstSelections = [], secondSelections = [];
  const { element, render } = await mount(AnalysisCurves, { payload, payloadKey: "curves:1", onSelection: value => firstSelections.push(value) });
  await click(element.querySelector('input[type="checkbox"]'));
  await changeValue(element.querySelector('input[aria-label="Range start"]'), 4);
  payload.rows = [{ row: 25, label: "2026-10-07", x: Date.UTC(2026, 9, 7), values: { temperature: 17 } }];
  payload.series = [{ id: "temperature", label: "Temperature" }];
  payload.x_type = "datetime";
  const onSelection = value => secondSelections.push(value);
  await render({ payload, payloadKey: "curves:2", onSelection });
  assert.equal(element.querySelectorAll("circle").length, 1);
  assert.equal(element.querySelectorAll('input[type="checkbox"]').length, 1);
  assert.equal(element.querySelector('input[type="checkbox"]').checked, true);
  assert.match(element.querySelector("svg").getAttribute("aria-label"), /Elapsed \(UTC\)/);
  assert.match(element.querySelector("svg").textContent, /10-07/);
  assert.deepEqual(secondSelections.at(-1), {});
  const firstCount = firstSelections.length;
  await key(element.querySelector("circle"), "Enter");
  assert.equal(firstSelections.length, firstCount);
  assert.deepEqual(secondSelections.at(-1), { row: 25, series: "temperature", x: Date.UTC(2026, 9, 7), y: 17,
    label: "Temperature — 2026-10-07: 17" });
});
