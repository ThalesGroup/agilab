import test from "node:test";
import assert from "node:assert/strict";
import {mountPydeck} from "./agilab_pydeck_bootstrap.js";

function fixture(t) {
  const keys = ["document", "agilabPydeck", "agilabDeckInstance", "agilabPydeckState", "agilabPydeckDiagnostic", "setTimeout"];
  const before = Object.fromEntries(keys.map(key => [key, globalThis[key]]));
  t.after(() => {for (const key of keys) {if (before[key] === undefined) delete globalThis[key]; else globalThis[key] = before[key];}});
  const status = {hidden: false, textContent: "", setAttribute(key, value) {this[key] = value;}};
  const container = {hidden: false, querySelector() {return {};}};
  globalThis.document = {getElementById(id) {return id === "deck-container" ? container : status;},
    createElement() {return {getContext() {return {getExtension() {return {loseContext() {}};}};}};}};
  globalThis.setTimeout = () => 0;
  let calls = 0, conversionCalls = 0, received;
  const instance = {setProps() {}};
  globalThis.agilabPydeck = {
    jsonConverter: {configuration: {getProps() {return {classes: {ScatterplotLayer: function ScatterplotLayer() {}}};}},
      mergeConfiguration() {}, convert(input) {conversionCalls++; return input;}},
    addCustomLibraries(libraries, complete) {complete();},
    createDeckJS(options) {calls++; received = options; return instance;}
  };
  const options = {jsonInput: {layers: [{"@@type": "ScatterplotLayer", data: [{position: [1, 46]}]}]},
    tooltip: {text: "{name}"}, configuration: null, customLibraries: [], mapboxApiKey: "public-fixture"};
  return {status, container, options, instance, calls: () => calls, conversions: () => conversionCalls, received: () => received};
}

test("known pydeck class initializes through the pinned JSONConfiguration API", t => {
  const f = fixture(t);
  mountPydeck(f.options);
  assert.equal(f.calls(), 1);
  assert.equal(globalThis.agilabDeckInstance, f.instance);
  assert.equal(globalThis.agilabPydeckState, "initialized");
  assert.equal(f.status.hidden, true);
  assert.equal(f.received().jsonInput, f.options.jsonInput);
  assert.equal(f.received().tooltip, f.options.tooltip);
  assert.equal(f.received().mapboxApiKey, f.options.mapboxApiKey);
});

test("unknown class is diagnosed before conversion or renderer creation", t => {
  const f = fixture(t);
  f.options.jsonInput.layers[0]["@@type"] = "NeverPrintPrivateType";
  mountPydeck(f.options);
  assert.equal(f.calls(), 0);
  assert.equal(f.conversions(), 0);
  assert.equal(globalThis.agilabPydeckState, "unavailable");
  assert.match(f.status.textContent, /custom library/);
  assert.doesNotMatch(f.status.textContent, /NeverPrint/);
});

test("missing WebGL is visible before creating a deck instance", t => {
  const f = fixture(t);
  globalThis.document.createElement = () => ({getContext() {return null;}});
  mountPydeck(f.options);
  assert.equal(f.calls(), 0);
  assert.equal(f.status.role, "alert");
  assert.match(f.status.textContent, /WebGL 2/);
});

test("missing runtime and invalid configuration fail visibly without leaking input", t => {
  const f = fixture(t);
  f.options.configuration = "never-print invalid JS";
  mountPydeck(f.options);
  assert.equal(f.calls(), 0);
  assert.doesNotMatch(f.status.textContent, /never-print/);
  assert.deepEqual(globalThis.agilabPydeckDiagnostic, {phase: "configuration", type: "SyntaxError"});
  globalThis.agilabPydeck = undefined;
  mountPydeck(f.options);
  assert.equal(f.status.role, "alert");
  assert.match(f.status.textContent, /Rebuild agi-web/);
});
