// ES modules require CORS from the opaque-origin html_frame sandbox.
export function mountPydeck(options) {
  const status = document.getElementById("agilab-pydeck-status");
  const container = document.getElementById("deck-container");
  const fail = message => {
    status.hidden = false;
    status.setAttribute("role", "alert");
    status.textContent = message;
    container.hidden = true;
    globalThis.agilabPydeckState = "unavailable";
  };
  if (!globalThis.agilabPydeck?.createDeckJS) {
    fail("Pydeck renderer is unavailable. Rebuild agi-web frontend assets and reinstall its wheel.");
    return;
  }
  let phase = "webgl";
  try {
    const probe = document.createElement("canvas").getContext("webgl2");
    if (!probe) {
      fail("Pydeck requires WebGL 2. Enable hardware acceleration or use a browser with WebGL 2 support.");
      return;
    }
    probe.getExtension("WEBGL_lose_context")?.loseContext();
    // Pydeck configuration is a documented JavaScript expression. It stays in
    // the opaque-origin sandbox and never enters HTML parsing or host state.
    phase = "configuration";
    if (typeof options.configuration === "string") {
      options.configuration = Function("return (" + options.configuration + ")")();
    }
    if (options.configuration) globalThis.agilabPydeck.jsonConverter.mergeConfiguration(options.configuration);
    phase = "custom-libraries";
    const libraries = options.customLibraries || [];
    if (libraries.some(library => !globalThis[library.libraryName])) {
      fail("Pydeck custom library could not load. Rebuild its packaged frontend assets.");
      return;
    }
    globalThis.agilabPydeck.addCustomLibraries(libraries, () => {});
    for (const key of ["layers", "views", "widgets"]) {
      if ((options.jsonInput[key] || []).some(item => item?.["@@type"] && !globalThis.agilabPydeck.jsonConverter.configuration.getProps().classes[item["@@type"]])) {
        fail("A pydeck layer, view or widget is unavailable. Package its custom library and rebuild agi-web.");
        return;
      }
    }
    phase = "layer-resolution";
    const props = globalThis.agilabPydeck.jsonConverter.convert(options.jsonInput);
    for (const key of ["layers", "views", "widgets"]) {
      if ((options.jsonInput[key] || []).filter(Boolean).length !== (props[key] || []).filter(Boolean).length) {
        fail("A pydeck layer, view or widget is unavailable. Package its custom library and rebuild agi-web.");
        return;
      }
    }
    const reportError = () => fail("Pydeck could not render this visualization. Check layer inputs, browser WebGL support and explicitly configured imagery resources.");
    phase = "renderer";
    if (options.jsonInput.mapProvider === "maplibre") {
      globalThis.agilabPydeck.setMaplibreWorkerUrl(new URL(options.maplibreWorkerUrl, document.baseURI).href);
    }
    const instance = globalThis.agilabPydeck.createDeckJS({...options, container, showError: false});
    if (!instance) { reportError(); return; }
    if (instance.setProps) instance.setProps({onError: reportError});
    globalThis.agilabDeckInstance = instance;
    globalThis.agilabPydeckState = "initialized";
    status.hidden = true;
    setTimeout(() => {
      if (globalThis.agilabPydeckState === "initialized" && !container.querySelector("canvas")) reportError();
    }, 15000);
  } catch (error) {
    globalThis.agilabPydeckDiagnostic = {phase, type: ["Error", "TypeError", "ReferenceError", "SyntaxError"].includes(error.name) ? error.name : "Error"};
    fail("Pydeck could not initialize. Check layer inputs, custom library configuration and browser WebGL 2 support.");
  }
}
