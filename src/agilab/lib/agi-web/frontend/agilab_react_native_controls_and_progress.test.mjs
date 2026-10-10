import assert from "node:assert/strict";
import { copyFile, mkdtemp, readFile, rm } from "node:fs/promises";
import path from "node:path";
import { after, afterEach, before, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { act } from "react";
import { build } from "esbuild";
import { JSDOM } from "jsdom";

const [nodeMajor, nodeMinor, nodePatch] = process.versions.node.split(".").map(Number);
assert.ok(nodeMajor >= 26 || (nodeMajor === 24 && nodeMinor >= 15)
  || (nodeMajor === 22 && (nodeMinor > 22 || (nodeMinor === 22 && nodePatch >= 2))),
"Native DOM tests require Node 22.22.2+, Node 24.15.0+, or Node 26+.");

const directory = path.dirname(fileURLToPath(import.meta.url));
let scratch, dom, mountPythonView, cleanup;
const globals = new Map();
const node = (id, kind, props = {}) => ({ id, kind, props, children: [] });
const payload = (revision, nodes) => ({
  revision, csrf_token: "owned-synthetic-token", path: "/", query: {},
  config: { page_title: "Native control regression" }, nodes: { main: nodes, sidebar: [] },
});
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
  dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "https://agilab-native-test.invalid/" });
  for (const name of ["window", "document", "navigator", "location", "history", "HTMLElement", "HTMLInputElement", "Event", "FocusEvent"])
    expose(name, name === "window" ? dom.window : dom.window[name]);
  expose("IS_REACT_ACT_ENVIRONMENT", true);
  scratch = await mkdtemp(path.join(directory, ".agilab-native-controls-test-"));
  const outfile = path.join(scratch, "agilab_native_controls_host_test_module.mjs");
  await build({ entryPoints: [path.join(directory, "agilab_react_python_host.jsx")],
    outfile, bundle: true, format: "esm", platform: "node",
    external: ["react", "react-dom/*"], loader: { ".css": "empty" } });
  ({ mountPythonView } = await import(pathToFileURL(outfile).href));
});
afterEach(async () => {
  if (cleanup) { await act(() => cleanup()); cleanup = null; }
  document.body.replaceChildren();
  for (const name of ["fetch", "setInterval", "clearInterval"]) {
    if (!globals.has(name)) continue;
    const descriptor = globals.get(name);
    if (descriptor) Object.defineProperty(globalThis, name, descriptor); else delete globalThis[name];
    globals.delete(name);
  }
});
after(async () => {
  dom?.window.close();
  if (scratch) await rm(scratch, { recursive: true, force: true });
  for (const [name, descriptor] of globals) {
    if (descriptor) Object.defineProperty(globalThis, name, descriptor); else delete globalThis[name];
  }
});
async function mount(initialPayload, transport = null) {
  const element = document.createElement("div"); document.body.append(element);
  await act(() => { cleanup = mountPythonView(element, { initialPayload, transport }); });
  return element;
}
async function changeInput(input, value, event = "change") {
  await act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, value);
    input.dispatchEvent(new Event(event, { bubbles: true }));
  });
}

test("a delayed poll cannot replace the accepted view while the next queued action runs", async () => {
  const controls = [node("edit", "text_input", { label: "Edit", key: "edit", value: "" }),
    node("apply", "button", { label: "Apply", key: "apply" })];
  const initial = payload(1, [...controls, node("body", "text", { body: "Initial view" })]);
  const completed = revision => payload(revision,
    [...controls.map(item => item.id === "edit" ? { ...item, props: { ...item.props, value: "draft" } } : item),
      node("body", "text", { body: `Accepted view ${revision}` })]);
  const actions = [], actionReplies = [deferred(), deferred()], progressReply = deferred(), intervals = [];
  expose("fetch", async (url, options) => {
    if (url === "/api/progress") return progressReply.promise;
    assert.equal(url, "/api/action"); actions.push(JSON.parse(options.body));
    return actionReplies[actions.length - 1].promise;
  });
  expose("setInterval", callback => { intervals.push(callback); return intervals.length; });
  expose("clearInterval", () => {});
  const element = await mount(initial);
  const input = element.querySelector('input[type="text"]');
  await changeInput(input, "draft", "input");
  await act(() => { input.dispatchEvent(new FocusEvent("focusout", { bubbles: true })); });
  assert.equal(actions.length, 1);
  assert.equal(element.querySelector("button").disabled, false);
  await act(() => { element.querySelector("button").click(); });
  let latePoll;
  act(() => { latePoll = intervals[0](); });
  await act(async () => { actionReplies[0].resolve({ ok: true, json: async () => completed(2) }); });
  assert.equal(actions.length, 2);
  assert.equal(actions[1].revision, 2);
  assert.match(element.textContent, /Accepted view 2/);
  await act(async () => {
    progressReply.resolve({ ok: true, json: async () => ({
      ...initial, running: true, nodes: { main: [...controls, node("body", "text", { body: "Obsolete progress" })], sidebar: [] },
    }) });
    await latePoll;
  });
  assert.match(element.textContent, /Accepted view 2/);
  assert.doesNotMatch(element.textContent, /Obsolete progress/);
  await act(async () => { actionReplies[1].resolve({ ok: true, json: async () => completed(3) }); });
  assert.match(element.textContent, /Accepted view 3/);
  assert.equal(element.querySelector('[aria-busy]').getAttribute("aria-busy"), "false");
});

test("an active poll still displays progress before its owning action completes", async () => {
  const button = node("apply", "button", { label: "Apply", key: "apply" });
  const actionReply = deferred(), intervals = [];
  expose("fetch", async url => url === "/api/action" ? actionReply.promise : {
    ok: true, json: async () => ({ ...payload(1, [button, node("progress", "text", { body: "Current progress" })]), running: true }),
  });
  expose("setInterval", callback => { intervals.push(callback); return intervals.length; });
  expose("clearInterval", () => {});
  const element = await mount(payload(1, [button]));
  await act(() => { element.querySelector("button").click(); });
  await act(async () => { await intervals[0](); });
  assert.match(element.textContent, /Current progress/);
  await act(async () => { actionReply.resolve({ ok: true, json: async () => payload(2, [button, node("result", "text", { body: "Final result" })]) }); });
  assert.match(element.textContent, /Final result/);
  assert.doesNotMatch(element.textContent, /Current progress/);
});

function datePayload(revision, value, range = true) {
  return payload(revision, [node("period", "date_input", { label: "Period", key: "period", value, range,
    min_value: "2026-01-01", max_value: "2026-12-31" })]);
}
async function dateView(value, range = true) {
  const actions = []; let revision = 1;
  const element = await mount(datePayload(revision, value, range), {
    action: async action => { actions.push(action); return datePayload(++revision, action.value, range); },
  });
  return { element, actions, inputs: () => [...element.querySelectorAll('input[type="date"]')] };
}

test("an empty date range can be completed and either bound can be cleared", async () => {
  const view = await dateView([]);
  assert.equal(view.inputs().length, 2);
  assert.equal(view.inputs()[0].getAttribute("aria-label"), "Period start");
  assert.equal(view.inputs()[1].getAttribute("aria-label"), "Period end");
  assert.notEqual(view.inputs()[0].id, view.inputs()[1].id);
  assert.equal(view.inputs()[1].disabled, true);
  await changeInput(view.inputs()[0], "2026-10-06");
  assert.deepEqual(view.actions.at(-1).value, ["2026-10-06"]);
  assert.equal(view.inputs()[1].disabled, false);
  await changeInput(view.inputs()[1], "2026-10-07");
  assert.deepEqual(view.actions.at(-1).value, ["2026-10-06", "2026-10-07"]);
  await changeInput(view.inputs()[1], "");
  assert.deepEqual(view.actions.at(-1).value, ["2026-10-06"]);
  await changeInput(view.inputs()[0], "");
  assert.deepEqual(view.actions.at(-1).value, []);
  assert.deepEqual(view.inputs().map(input => input.value), ["", ""]);
  assert.equal(view.inputs()[1].disabled, true);
  assert.equal(view.actions.length, 4);
});

test("a one-date range exposes an end input and clearing its start never shifts the end", async () => {
  const view = await dateView(["2026-10-06"]);
  assert.equal(view.inputs().length, 2);
  assert.equal(view.inputs()[1].disabled, false);
  await changeInput(view.inputs()[1], "2026-10-07");
  assert.deepEqual(view.actions.at(-1).value, ["2026-10-06", "2026-10-07"]);
  await changeInput(view.inputs()[0], "");
  assert.deepEqual(view.actions.at(-1).value, []);
  assert.deepEqual(view.inputs().map(input => input.value), ["", ""]);
});

test("editing a full range preserves its other bound and scalar dates remain one input", async () => {
  const view = await dateView(["2026-10-06", "2026-10-07"]);
  assert.equal(view.inputs().length, 2);
  await changeInput(view.inputs()[0], "2026-10-05");
  assert.deepEqual(view.actions.at(-1).value, ["2026-10-05", "2026-10-07"]);
  assert.deepEqual(view.inputs().map(input => input.value), ["2026-10-05", "2026-10-07"]);
  await act(() => cleanup()); cleanup = null;
  const scalar = await dateView("2026-10-06", false);
  assert.equal(scalar.inputs().length, 1);
  await changeInput(scalar.inputs()[0], "2026-10-07");
  assert.equal(scalar.actions.at(-1).value, "2026-10-07");
});

test("the packaged production bundle completes an initially empty date range", async () => {
  const packaged = new URL("../src/agi_web/react_python_host_assets/agilab_react_python_host.js", import.meta.url);
  const module = path.join(scratch, "agilab_native_packaged_production_host_exact_bytes.mjs");
  await copyFile(packaged, module);
  assert.deepEqual(await readFile(module), await readFile(packaged));
  const { mountPythonView: mountPackaged } = await import(pathToFileURL(module).href);
  const element = document.createElement("div"); document.body.append(element);
  const actions = []; let revision = 1;
  const waitFor = async predicate => {
    for (let attempt = 0; attempt < 100; attempt++) {
      if (predicate()) return;
      await new Promise(resolve => setTimeout(resolve, 1));
    }
    assert.fail("The packaged React host did not render its expected date controls.");
  };
  const inputs = () => [...element.querySelectorAll('input[type="date"]')];
  cleanup = mountPackaged(element, { initialPayload: datePayload(revision, []), transport: {
    action: async action => { actions.push(action); return datePayload(++revision, action.value); },
  } });
  await waitFor(() => inputs().length === 2);
  assert.equal(inputs()[1].disabled, true);
  await changeInput(inputs()[0], "2026-10-06");
  await waitFor(() => actions.length === 1 && !inputs()[1].disabled);
  await changeInput(inputs()[1], "2026-10-07");
  await waitFor(() => actions.length === 2 && inputs()[1].value === "2026-10-07");
  assert.deepEqual(actions.map(action => action.value), [["2026-10-06"], ["2026-10-06", "2026-10-07"]]);
});

test("option groups name each radio independently and preserve Python selections", async () => {
  for (const kind of ["radio", "pills", "segmented_control"]) {
    let revision = 1;
    const actions = [];
    const selection = value => node("mode", kind, { label: "Analysis mode", key: "mode", value,
      options: [0, 1], option_labels: ["Coordinates", "Curves"], help: "Choose a view" });
    const element = await mount(payload(revision, [selection(0)]), {
      action: async action => { actions.push(action); return payload(++revision, [selection(action.value)]); },
    });
    const group = element.querySelector('[role="radiogroup"]');
    assert.equal(group.getAttribute("aria-label"), "Analysis mode");
    assert.equal(document.getElementById(group.getAttribute("aria-describedby")).textContent, "Choose a view");
    const options = [...group.querySelectorAll('input[type="radio"]')];
    assert.deepEqual(options.map(input => input.getAttribute("aria-label")), ["Coordinates", "Curves"]);
    assert.equal(group.querySelector("label label"), null);
    await act(() => options[1].click());
    assert.equal(actions.at(-1).value, 1);
    assert.deepEqual([...group.querySelectorAll("input")].map(input => input.checked), [false, true]);
    await act(() => cleanup()); cleanup = null;
    element.remove();
  }
});

test("multi-select options expose their own names and start from an empty selection", async () => {
  const choices = value => node("features", "segmented_control", { label: "Features", key: "features", value,
    selection_mode: "multi", options: [0, 1], option_labels: ["Speed", "Altitude"] });
  const actions = [];
  const element = await mount(payload(1, [choices(null)]), {
    action: async action => { actions.push(action); return payload(2, [choices(action.value)]); },
  });
  const group = element.querySelector('[role="group"]');
  assert.equal(group.getAttribute("aria-label"), "Features");
  const options = [...group.querySelectorAll('input[type="checkbox"]')];
  assert.deepEqual(options.map(input => input.getAttribute("aria-label")), ["Speed", "Altitude"]);
  await act(() => options[1].click());
  assert.deepEqual(actions.at(-1).value, [1]);
});

function dependentForm(pattern = "(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", flags = "i", sourceKey = "variable_name") {
  const form = node("settings", "form");
  const additions = node("new-variable", "expander", { label: "Add variable", expanded: true });
  additions.children = [
    node("name", "text_input", { label: "Variable name", key: "variable_name", value: "", form: "settings" }),
    node("value", "text_input", { label: "Variable value", key: "variable_value", value: "", form: "settings",
      type_dependency: { key: sourceKey, pattern, flags } }),
  ];
  const savedSection = node("saved-section", "expander", { label: "Existing settings", expanded: false });
  savedSection.children = [node("existing", "text_input", { label: "Existing value", key: "existing_value", value: "saved", form: "settings" })];
  form.children = [additions, savedSection, node("save", "form_submit_button", { label: "Save settings", form: "settings" })];
  return payload(1, [form]);
}

test("sensitive form drafts mask before submission and collapsed field edits still submit", async () => {
  const actions = [];
  const element = await mount(dependentForm(), { action: async action => { actions.push(action); return dependentForm(); } });
  const name = element.querySelector("#name"), value = element.querySelector("#value");
  await changeInput(name, "AGILAB_UX_SYNTHETIC_SECRET", "input");
  assert.equal(value.type, "password");
  await changeInput(value, "synthetic-value", "input");
  assert.equal(value.value, "synthetic-value");
  assert.equal(actions.length, 0, "A form draft must not make a server roundtrip.");
  const section = element.querySelector('[data-widget-kind="expander"] + [data-widget-kind="expander"]');
  section.open = true;
  await changeInput(element.querySelector("#existing"), "changed", "input");
  section.open = false;
  assert.equal(element.querySelector("#existing").value, "changed");
  await changeInput(name, "PUBLIC_SETTING", "input");
  assert.equal(value.type, "text");
  assert.equal(value.value, "synthetic-value");
  await changeInput(name, "private_api_token", "input");
  assert.equal(value.type, "password");
  await act(async () => {element.querySelector('button[type="submit"]').click();});
  assert.deepEqual(actions[0].form_values, { name: "private_api_token", value: "synthetic-value", existing: "changed" });
});

test("missing or malformed masking dependencies keep the value concealed", async () => {
  const missingFields = dependentForm();
  missingFields.nodes.main[0].children[0].children[1].props.type_dependency = {};
  for (const fixture of [dependentForm("["), dependentForm("SECRET", "invalid"), dependentForm("SECRET", "i", "missing"), missingFields]) {
    const element = await mount(fixture);
    assert.equal(element.querySelector("#value").type, "password");
    await act(() => cleanup()); cleanup = null;
    element.remove();
  }
});

test("initial sensitive form values remain masked and survive a draft name change", async () => {
  const fixture = dependentForm();
  const fields = fixture.nodes.main[0].children[0].children;
  fields[0].props.value = "saved_api_key";
  fields[1].props.value = "initial-synthetic-value";
  const element = await mount(fixture);
  const value = element.querySelector("#value");
  assert.equal(value.type, "password");
  assert.equal(value.value, "initial-synthetic-value");
  await changeInput(element.querySelector("#name"), "PUBLIC_SETTING", "input");
  assert.equal(value.type, "text");
  assert.equal(value.value, "initial-synthetic-value");
});

test("image descriptions and stretch widths reach the rendered plot", async () => {
  const element = await mount(payload(1, [
    node("plot", "image", { urls: ["https://agilab-test.invalid/plot.png"], alt: "Iris features grouped by species", width: "stretch", caption: "Iris measurements" }),
    node("captioned", "image", { urls: ["https://agilab-test.invalid/chart.png"], caption: "Flight altitude over time", width: 600 }),
    node("decorative", "image", { urls: ["https://agilab-test.invalid/decoration.png"], alt: "" }),
    node("undescribed", "image", { urls: ["https://agilab-test.invalid/no-description.png"], caption: "" }),
  ]));
  const images = [...element.querySelectorAll("img")];
  assert.equal(images[0].alt, "Iris features grouped by species");
  assert.equal(images[0].style.width, "100%");
  assert.equal(images[0].style.height, "auto");
  assert.equal(images[1].alt, "Flight altitude over time");
  assert.equal(images[1].style.width, "600px");
  assert.equal(images[2].getAttribute("alt"), "", "Only an explicit decorative alt may be empty.");
  assert.equal(images[3].hasAttribute("alt"), false, "An empty caption must not mark an undescribed plot decorative.");
});


test("file popovers retain controls during rerenders and close with Escape or outside interaction", async () => {
  const disclosure = revision => {
    const item = node("dataset-picker", "popover", {
      label: revision === 1 ? "Choose dataset" : "Dataset selected",
      help: "Choose a CSV under the project", width: "stretch",
    });
    item.children = [
      node("dataset-filter", "text_input", { label: "Filter files", value: "input", key: "filter" }),
      node("dataset-select", "button", { label: "Select dataset", key: "choose" }),
    ];
    return item;
  };
  const actions = [];
  const element = await mount(payload(1, [disclosure(1)]), {
    action: async action => { actions.push(action); return payload(2, [disclosure(2)]); },
  });
  const trigger = element.querySelector(".py-popover-trigger");
  const panel = element.querySelector(".py-popover-panel");
  const input = element.querySelector("#dataset-filter");
  assert.equal(trigger.tagName, "BUTTON", "Use native keyboard activation.");
  assert.equal(trigger.getAttribute("aria-expanded"), "false");
  assert.equal(trigger.getAttribute("aria-controls"), panel.id);
  assert.equal(panel.getAttribute("role"), "dialog");
  assert.equal(panel.hidden, true);
  assert.equal(element.querySelector(".py-popover").style.width, "100%");
  await act(() => trigger.click());
  assert.equal(panel.hidden, false);
  assert.equal(trigger.getAttribute("aria-expanded"), "true");
  assert.equal(actions.length, 0, "Opening a disclosure needs no server roundtrip.");
  input.focus();
  await act(() => input.dispatchEvent(new Event("pointerdown", { bubbles: true })));
  assert.equal(panel.hidden, false);
  await act(() => input.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
  assert.equal(panel.hidden, true);
  assert.equal(document.activeElement, trigger);
  await act(() => trigger.click());
  await act(async () => element.querySelector("#dataset-select").click());
  assert.equal(actions.length, 1);
  assert.equal(actions[0].id, "dataset-select");
  assert.equal(element.querySelector(".py-popover-trigger"), trigger);
  assert.equal(trigger.textContent, "Dataset selected");
  assert.equal(panel.hidden, false);
  assert.equal(element.querySelector("#dataset-filter"), input);
  assert.equal(input.value, "input");
  const outside = document.createElement("button");
  document.body.append(outside);
  await act(() => outside.focus());
  assert.equal(panel.hidden, true, "Leaving the popover by keyboard closes it.");
  await act(() => trigger.click());
  assert.equal(panel.hidden, false);
  await act(() => outside.dispatchEvent(new Event("pointerdown", { bubbles: true })));
  assert.equal(panel.hidden, true);
  assert.equal(document.activeElement, outside, "Closing outside must not steal focus.");
});

test("disabled popovers keep their child controls hidden", async () => {
  const item = node("disabled-picker", "popover", { label: "Unavailable", disabled: true });
  item.children = [node("disabled-child", "text_input", { label: "Hidden child", value: "" })];
  const element = await mount(payload(1, [item]), { action: async () => assert.fail("Unexpected server action") });
  const trigger = element.querySelector(".py-popover-trigger");
  assert.equal(trigger.disabled, true);
  await act(() => trigger.click());
  assert.equal(trigger.getAttribute("aria-expanded"), "false");
  assert.equal(element.querySelector(".py-popover-panel").hidden, true);
});


test("the packaged production bundle renders an interactive file popover", async () => {
  const packaged = new URL("../src/agi_web/react_python_host_assets/agilab_react_python_host.js", import.meta.url);
  const module = path.join(scratch, "agilab_native_packaged_popover_host_exact_bytes.mjs");
  await copyFile(packaged, module);
  assert.deepEqual(await readFile(module), await readFile(packaged));
  const { mountPythonView: mountPackaged } = await import(pathToFileURL(module).href);
  const item = node("packaged-picker", "popover", { label: "Choose CSV", width: "stretch" });
  item.children = [node("packaged-filter", "text_input", { label: "Filter files", value: "" })];
  const element = document.createElement("div"); document.body.append(element);
  cleanup = mountPackaged(element, { initialPayload: payload(1, [item]), transport: {
    action: async () => assert.fail("Popover interactions must stay local"),
  } });
  const waitFor = async predicate => {
    for (let attempt = 0; attempt < 100; attempt++) {
      if (predicate()) return;
      await new Promise(resolve => setTimeout(resolve, 1));
    }
    assert.fail("The packaged popover did not reach its expected state.");
  };
  await waitFor(() => element.querySelector(".py-popover-trigger"));
  const trigger = element.querySelector(".py-popover-trigger");
  const panel = element.querySelector(".py-popover-panel");
  assert.equal(panel.hidden, true);
  trigger.click();
  await waitFor(() => !panel.hidden);
  const input = element.querySelector("#packaged-filter");
  input.focus();
  input.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  await waitFor(() => panel.hidden);
  assert.equal(document.activeElement, trigger);
});


test("packaged nested popovers retain state on rerender and Escape closes only the deepest panel", async () => {
  const packaged = new URL("../src/agi_web/react_python_host_assets/agilab_react_python_host.js", import.meta.url);
  const module = path.join(scratch, "agilab_native_packaged_nested_popover_host_exact_bytes.mjs");
  await copyFile(packaged, module);
  assert.deepEqual(await readFile(module), await readFile(packaged));
  const { mountPythonView: mountPackaged } = await import(pathToFileURL(module).href);
  const nested = revision => {
    const parent = node("outer-picker", "popover", { label: revision === 1 ? "Choose dataset" : "Dataset selected" });
    const child = node("inner-picker", "popover", { label: "Advanced" });
    child.children = [
      node("inner-filter", "text_input", { label: "Filter files", value: "input" }),
      node("inner-apply", "button", { label: "Apply filter" }),
    ];
    parent.children = [child];
    return payload(revision, [parent]);
  };
  const element = document.createElement("div"); document.body.append(element);
  const actions = [];
  cleanup = mountPackaged(element, { initialPayload: nested(1), transport: {
    action: async action => { actions.push(action); return nested(2); },
  } });
  const waitFor = async predicate => {
    for (let attempt = 0; attempt < 100; attempt++) {
      if (predicate()) return;
      await new Promise(resolve => setTimeout(resolve, 1));
    }
    assert.fail("The packaged nested popovers did not reach their expected state.");
  };
  await waitFor(() => element.querySelector("#outer-picker-popover"));
  const parentPanel = element.querySelector("#outer-picker-popover");
  const childPanel = element.querySelector("#inner-picker-popover");
  const parentTrigger = element.querySelector('[aria-controls="outer-picker-popover"]');
  const childTrigger = element.querySelector('[aria-controls="inner-picker-popover"]');
  parentTrigger.focus();
  parentTrigger.click();
  await waitFor(() => !parentPanel.hidden);
  childTrigger.focus();
  childTrigger.click();
  await waitFor(() => !childPanel.hidden);
  const input = element.querySelector("#inner-filter");
  input.focus();
  element.querySelector("#inner-apply").click();
  await waitFor(() => parentTrigger.textContent === "Dataset selected");
  assert.equal(actions.length, 1);
  assert.equal(element.querySelector("#inner-filter"), input);
  assert.equal(document.activeElement, input);
  assert.equal(childPanel.hidden, false, "The nested panel stays open across the Python rerender.");
  input.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  await waitFor(() => childPanel.hidden);
  assert.equal(parentPanel.hidden, false, "Escape first closes only the deepest panel.");
  assert.equal(document.activeElement, childTrigger);
  assert.equal(parentTrigger.getAttribute("aria-expanded"), "true");
  assert.equal(childTrigger.getAttribute("aria-expanded"), "false");
  childTrigger.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  await waitFor(() => parentPanel.hidden);
  assert.equal(document.activeElement, parentTrigger);
  assert.equal(parentTrigger.getAttribute("aria-expanded"), "false");
});
