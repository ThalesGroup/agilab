import {instance} from "@viz-js/viz";

let runtime;
export async function renderGraph(element, source) {
  runtime ||= instance();
  const viz = await runtime;
  const svg = viz.renderSVGElement(source);
  svg.querySelectorAll("script,foreignObject").forEach(node => node.remove());
  svg.querySelectorAll("*").forEach(node => [...node.attributes].forEach(attribute => {
    if (/^on/i.test(attribute.name) || (/href$/i.test(attribute.name) && !/^(https?:|\/[^/]|#)/i.test(attribute.value))) node.removeAttribute(attribute.name);
  }));
  svg.style.maxWidth = "100%";
  svg.style.height = "auto";
  element.replaceChildren(svg);
}
