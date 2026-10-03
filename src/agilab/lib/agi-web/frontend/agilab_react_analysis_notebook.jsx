import React from "react";
import { createRoot } from "react-dom/client";
import { AnalysisComponent } from "./agilab_react_analysis_components.jsx";
export default {
  render({ model, el }) {
    const root = createRoot(el);
    const update = () => root.render(<AnalysisComponent component={model.get("component")}
      onSelection={value => { model.set("selection", value); model.save_changes(); }}/>);
    model.on("change:component", update); update();
    return () => { model.off("change:component", update); root.unmount(); };
  }
};
