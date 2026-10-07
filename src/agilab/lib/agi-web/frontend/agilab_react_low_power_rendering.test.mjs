import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import path from "node:path";
import { after, afterEach, before, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { act } from "react";
import { build } from "esbuild";
import { JSDOM } from "jsdom";

const directory = path.dirname(fileURLToPath(import.meta.url));
const globals = new Map();
let dom, scratch, mountPythonView, cleanup, purifier, originalSanitize, sanitizations = 0;
const node = (id, kind, props = {}, children = []) => ({ id, kind, props, children });
const payload = (revision, main, sidebar = []) => ({ revision, csrf_token: "owned-rendering-token",
  path: "/", query: {}, config: { page_title: "Low power rendering regression" }, nodes: { main, sidebar } });
function expose(name, value) {
  if (!globals.has(name)) globals.set(name, Object.getOwnPropertyDescriptor(globalThis, name));
  Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
}
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}
before(async () => {
  dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "https://agilab-low-power-test.invalid/" });
  for (const name of ["window", "document", "navigator", "location", "history", "HTMLElement", "HTMLInputElement", "Event"])
    expose(name, name === "window" ? dom.window : dom.window[name]);
  expose("IS_REACT_ACT_ENVIRONMENT", true);
  ({ default: purifier } = await import("dompurify"));
  originalSanitize = purifier.sanitize;
  purifier.sanitize = (...args) => { sanitizations += 1; return originalSanitize(...args); };
  scratch = await mkdtemp(path.join(directory, ".agilab-low-power-rendering-test-"));
  const outfile = path.join(scratch, "agilab_low_power_python_host_test_module.mjs");
  await build({ entryPoints: [path.join(directory, "agilab_react_python_host.jsx")], outfile,
    bundle: true, format: "esm", platform: "node", external: ["react", "react-dom/*", "dompurify"],
    loader: { ".css": "empty" } });
  ({ mountPythonView } = await import(pathToFileURL(outfile).href));
});
afterEach(async () => {
  if (cleanup) { await act(() => cleanup()); cleanup = null; }
  document.body.replaceChildren(); sanitizations = 0;
});
after(async () => {
  if (purifier) purifier.sanitize = originalSanitize;
  dom?.window.close();
  if (scratch) await rm(scratch, { recursive: true, force: true });
  for (const [name, descriptor] of globals) {
    if (descriptor) Object.defineProperty(globalThis, name, descriptor); else delete globalThis[name];
  }
});
async function mount(initialPayload, transport) {
  const element = document.createElement("div"); document.body.append(element);
  await act(() => { cleanup = mountPythonView(element, { initialPayload, transport }); });
  return element;
}
async function changeInput(input, value) {
  await act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

test("form drafts, tools and busy state preserve expensive sibling rendering while new Python data updates", async () => {
  let serializedCells = 0;
  const rows = Array.from({ length: 250 }, (_, index) => [{
    toJSON() { serializedCells += 1; return { index, label: `Sample ${index}` }; },
  }]);
  const form = node("filter-form", "form", {}, [
    node("filter", "text_input", { key: "filter", label: "Filter", value: "", form: "filter-form" }),
    node("apply", "form_submit_button", { key: "apply", label: "Apply", form: "filter-form" }),
  ]);
  const heavy = [node("explanation", "markdown", { body: "# Analysis\n\n" + "Observed **samples** and $x^2$.\n\n".repeat(80) }),
    node("markup", "html", { body: '<b>Trusted text</b><img src="x" onerror="alert(1)">' }),
    node("equation", "latex", { body: "x^2 + y^2 = 1" }),
    node("samples", "dataframe", { key: "samples", columns: ["Sample"], rows })];
  const sidebar = [node("tool", "caption", { body: "Contextual settings" })];
  const actions = [], reply = deferred();
  const element = await mount(payload(1, [form, ...heavy], sidebar), {
    action: action => { actions.push(action); return reply.promise; },
  });
  assert.equal(serializedCells, 250);
  assert.equal(sanitizations, 3);
  assert.equal(element.querySelector("[onerror]"), null);
  const markdown = element.querySelector(".py-markdown"), table = element.querySelector("table");
  const renderedSanitizations = sanitizations, renderedCells = serializedCells;
  for (const text of ["s", "sa", "sample"]) await changeInput(element.querySelector('[aria-label="Filter"]'), text);
  assert.equal(actions.length, 0, "Form drafts must remain local until submission.");
  assert.equal(element.querySelector('[aria-label="Filter"]').value, "sample");
  await act(() => element.querySelector(".py-sidebar-toggle").click());
  assert.equal(element.querySelector("aside").hidden, false);
  await act(() => element.querySelector("aside button").click());
  assert.equal(element.querySelector("aside").hidden, true);
  await act(async () => element.querySelector('[data-form="filter-form"] button').click());
  assert.equal(element.querySelector("[aria-busy]").getAttribute("aria-busy"), "true");
  assert.deepEqual(actions, [{ id: "apply", value: true, revision: 1, csrf_token: "owned-rendering-token",
    form_values: { filter: "sample" } }]);
  assert.deepEqual({ sanitizations, serializedCells },
    { sanitizations: renderedSanitizations, serializedCells: renderedCells },
    "Unrelated local state must not repeat markup sanitization or serialize unchanged table cells.");
  assert.equal(element.querySelector(".py-markdown"), markdown);
  assert.equal(element.querySelector("table"), table);
  const nextForm = node("filter-form", "form", {}, [
    node("filter", "text_input", { key: "filter", label: "Filter", value: "accepted", form: "filter-form" }),
    node("apply", "form_submit_button", { key: "apply", label: "Apply", form: "filter-form" }),
  ]);
  await act(async () => reply.resolve(payload(2, [nextForm,
    node("explanation", "markdown", { body: "# Updated analysis" }),
    node("samples", "dataframe", { key: "samples", columns: ["Result"], rows: [["updated sample"]] }),
  ], sidebar)));
  assert.equal(element.querySelector('[aria-label="Filter"]').value, "accepted");
  assert.match(element.querySelector(".py-markdown").textContent, /Updated analysis/);
  assert.equal(element.querySelector("td").textContent, "updated sample");
  assert.equal(sanitizations, renderedSanitizations + 1);
  assert.equal(element.querySelector("[aria-busy]").getAttribute("aria-busy"), "false");
});

test("selectable tables retain busy protection and use the newest selection and revision", async () => {
  const actions = [], replies = [deferred(), deferred()];
  const table = selected => node("samples", "dataframe", { key: "samples", columns: ["Sample"],
    rows: [["A"], ["B"]], selection_mode: "multi-row", value: { rows: selected } });
  const element = await mount(payload(1, [table([0])]), {
    action: action => { actions.push(action); return replies[actions.length - 1].promise; },
  });
  await act(async () => element.querySelector('[aria-label="Select row 2"]').click());
  assert.deepEqual(actions[0].value, { rows: [0, 1] });
  assert.ok([...element.querySelectorAll("input")].every(input => input.disabled));
  await act(async () => replies[0].resolve(payload(2, [table([0, 1])])));
  assert.ok([...element.querySelectorAll("input")].every(input => !input.disabled && input.checked));
  await act(async () => element.querySelector('[aria-label="Select row 1"]').click());
  assert.equal(actions[1].revision, 2);
  assert.deepEqual(actions[1].value, { rows: [1] });
  await act(async () => replies[1].resolve(payload(3, [table([1])])));
  assert.deepEqual([...element.querySelectorAll("input")].map(input => input.checked), [false, true]);
});

test("unchanged markup remains parsed once across fresh Python payloads and links navigate with current data", async () => {
  const body = "# Stable explanation\n\n$x^2$ and **samples**.";
  const view = (revision, url) => payload(revision, [node("explanation", "markdown", { body }),
    node("update", "button", { key: "update", label: "Update" }),
    node("destination", "page_link", { key: "destination", label: "Details", url })]);
  const renders = [];
  const element = await mount(view(1, "/old?item=old"), {
    action: async () => view(2, "/new?item=current"),
    render: async request => { renders.push(request); return { ...view(3, "/new"), path: request.path, query: request.query }; },
  });
  assert.equal(sanitizations, 1);
  await act(async () => element.querySelector("button").click());
  assert.equal(sanitizations, 1, "Fresh Python nodes with the same markdown body must not repeat parsing.");
  assert.equal(element.querySelector("a").getAttribute("href"), "/new?item=current");
  await act(async () => element.querySelector("a").click());
  assert.deepEqual(renders, [{ path: "/new", query: { item: "current" } }]);
  assert.equal(sanitizations, 1);
});
