import embed from "vega-embed";

/** Render a Python-owned Vega-Lite specification with the bundled local runtime. */
export async function renderVega(element, specification, {width = "stretch"} = {}) {
  const spec = structuredClone(specification);
  const responsive = width === "stretch" || width === "container" || width === true;
  const simple = !["concat", "hconcat", "vconcat", "facet", "repeat"].some(key => key in spec);
  if (simple && responsive) {
    spec.width = Math.max(100, element.parentElement.clientWidth || 640);
    spec.autosize = {type: "fit-x", contains: "padding", resize: true};
  } else if (typeof width === "number") spec.width = width;
  const result = await embed(element, spec, {
    mode: "vega-lite", renderer: "svg", actions: false, defaultStyle: true,
  });
  element.querySelector("svg")?.style.setProperty("max-width", "100%");
  let previousWidth = spec.width;
  const observer = simple && responsive ? new ResizeObserver(() => {
    const nextWidth = element.parentElement.clientWidth;
    if (nextWidth > 0 && nextWidth !== previousWidth) {
      previousWidth = nextWidth;
      result.view.width(nextWidth).resize().runAsync();
    }
  }) : null;
  observer?.observe(element.parentElement);
  return () => {observer?.disconnect(); result.finalize();};
}
