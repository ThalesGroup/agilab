import React from "react";
import { createRoot } from "react-dom/client";
import { AnalysisComponent } from "./agilab_react_analysis_components.jsx";
const roots = new WeakMap();
export default function({ parentElement, data, setStateValue }) {
  let entry = roots.get(parentElement);
  if (!entry) { const element = document.createElement("div"); parentElement.appendChild(element);
    entry = {element, root: createRoot(element)}; roots.set(parentElement, entry); }
  const {root, element} = entry;
  element.style.width = data.render_width ?? "100%";
  element.style.maxWidth = "100%";
  root.render(<AnalysisComponent component={data} onSelection={value => setStateValue("selection", value)}/>);
  return () => { root.unmount(); element.remove(); roots.delete(parentElement); };
}
