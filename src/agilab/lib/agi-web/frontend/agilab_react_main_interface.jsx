import React, { useEffect, useId, useState } from "react";
import { createRoot } from "react-dom/client";

export function MainInterface({ data, onAction }) {
  const projectId = useId();
  const emit = (kind, value) => onAction({ kind, value, project: data.project, route: data.route });
  const navigate = id => emit("navigate", id);
  const routeButton = route => <button key={route.id} type="button"
    aria-current={data.route === route.id ? "page" : undefined}
    onClick={() => navigate(route.id)}>{route.label}</button>;
  return <section className="agilab-main-interface" aria-label="AGILAB workspace"
    onKeyDown={event => event.stopPropagation()}>
    <header className="agilab-workspace-header">
      <button className="agilab-brand" type="button" onClick={() => navigate("home")} aria-label="AGILAB home">
        <span className="agilab-brand-symbol" aria-hidden="true">A</span><strong>{data.brand}</strong>
      </button>
      <div className="agilab-project-picker">
        <label htmlFor={projectId}>Project</label>
        <select id={projectId} value={data.project || ""} disabled={!data.projects.length}
          onChange={event => emit("project", event.target.value)}>
          {!data.project && <option value="">Choose a project</option>}
          {data.projects.map(name => <option key={name} value={name}>{name}</option>)}
        </select>
        <button type="button" disabled={!data.project} onClick={() => navigate("project_editor")}>Edit project</button>
      </div>
      {data.version && <small className="agilab-version">{data.version}</small>}
    </header>
    <nav className="agilab-workspace-navigation" aria-label="Workspace navigation">
      {data.routes.filter(route => route.primary).map(routeButton)}
      <details className="agilab-workspace-tools">
        <summary>Tools</summary>
        <div>{data.routes.filter(route => !route.primary).map(routeButton)}</div>
      </details>
    </nav>
    {data.route === "home" && <div className="agilab-workspace-home">
      <div className="agilab-home-intro">
        <p className="agilab-eyebrow">Experiment workspace</p>
        <h1>{data.welcome_title}</h1>
        <p>Choose your project, run its pipeline, then explore and export the evidence.</p>
      </div>
      <div className="agilab-project-summary">
        <div><small>Active project</small><h2>{data.project || "No project selected"}</h2>
          <p>{data.projects.length} available project{data.projects.length === 1 ? "" : "s"}</p></div>
        <button type="button" disabled={!data.project} onClick={() => navigate("project")}>Open project</button>
      </div>
      <div className="agilab-home-cards">
        {data.routes.filter(route => route.description).map(route => <button type="button" key={route.id}
          onClick={() => navigate(route.id)}>
          <span className="agilab-card-title">{route.label}</span><span>{route.description}</span>
          <span className="agilab-card-link">Open workspace →</span>
        </button>)}
      </div>
      <p className="agilab-notebook-note">Export your app from Workflow to use its supported analysis charts and coordinate views in Jupyter.</p>
    </div>}
  </section>;
}

export function ProjectWorkspace({ data, onAction }) {
  const navigate = value => onAction({ kind: "navigate", value, project: data.project,
    project_path: data.project_path, route: data.route });
  return <section className="agilab-main-interface agilab-project-workspace" aria-label="Project workspace"
    onKeyDown={event => event.stopPropagation()}>
    <div className="agilab-home-intro">
      <p className="agilab-eyebrow">Project workspace</p>
      <h1>{data.project || "No project selected"}</h1>
      <p>Review your environment and data, then run the project or explore its results.</p>
    </div>
    <div className="agilab-project-health" aria-label="Environment health">
      {data.cards.map(card => <article key={card.label}
        className={`agilab-health-card agilab-health-card--${card.state}`}>
        <h2>{card.label}</h2><p className="agilab-health-value">{card.value}</p>
        <p className="agilab-health-caption">{card.caption}</p>
        <small>{card.state === "incomplete" ? "Needs attention" : "Ready"}</small>
      </article>)}
    </div>
    <nav className="agilab-home-cards" aria-label="Project actions">
      {data.actions.map(action => <button type="button" key={action.id} disabled={!data.project}
        onClick={() => navigate(action.id)}>
        <span className="agilab-card-title">{action.label}</span><span>{action.description}</span>
        <span className="agilab-card-link">Open workspace →</span>
      </button>)}
    </nav>
    <p className="agilab-notebook-note">Open Analysis to explore results and access the notebook export in Workflow.</p>
  </section>;
}

export function AnalysisWorkspace({ data, onAction }) {
  const [views, setViews] = useState(data.draft_views);
  const [notebooks, setNotebooks] = useState(data.draft_notebooks);
  useEffect(() => { setViews(data.draft_views); setNotebooks(data.draft_notebooks); }, [data.context]);
  const dirty = JSON.stringify(views) !== JSON.stringify(data.selected_views)
    || JSON.stringify(notebooks) !== JSON.stringify(data.selected_notebooks);
  const emit = action => onAction({ ...action, project: data.project, project_path: data.project_path,
    route: data.route, context: data.context });
  const toggle = (values, setValues, id, checked) => setValues(checked ? [...values, id] : values.filter(value => value !== id));
  const choices = (label, items, values, setValues, saved, kind) => <fieldset className="agilab-analysis-choices">
    <legend>{label}</legend>
    {!items.length && <p>No {label.toLowerCase()} found in this project.</p>}
    {items.map(item => <div className="agilab-analysis-choice" key={item.id}>
      <label><input type="checkbox" checked={values.includes(item.id)}
        onChange={event => toggle(values, setValues, item.id, event.target.checked)}/><span>{item.label}</span></label>
      <button type="button" disabled={dirty || !saved.includes(item.id) || !item.available}
        aria-label={`Open ${item.label}`} onClick={() => emit({ kind, value: item.id })}>Open</button>
    </div>)}
  </fieldset>;
  return <section className="agilab-main-interface agilab-analysis-workspace" aria-label="Analysis workspace"
    onKeyDown={event => event.stopPropagation()}>
    <div className="agilab-home-intro"><p className="agilab-eyebrow">Analysis workspace</p>
      <h1>Explore {data.project || "your project"}</h1>
      <p>Choose your result views and notebooks. Save the selection, then open a view to explore it.</p></div>
    <div className="agilab-project-health" aria-label="Analysis summary">
      {data.overview.cards.map(card => <article key={card.label} className="agilab-health-card">
        <h2>{card.label}</h2><p className="agilab-health-value">{card.value}</p>
        <p className="agilab-health-caption">{card.caption}</p></article>)}
    </div>
    {data.overview.evidence && <p className="agilab-analysis-evidence">{data.overview.evidence}</p>}
    {data.overview.message && <p className="agilab-notebook-note">{data.overview.message}</p>}
    <form onSubmit={event => { event.preventDefault(); emit({ kind: "select", views, notebooks }); }}>
      <div className="agilab-analysis-selection">
        {choices("Analysis views", data.views, views, setViews, data.selected_views, "open_view")}
        {choices("Notebooks", data.notebooks, notebooks, setNotebooks, data.selected_notebooks, "open_notebook")}
      </div>
      <div className="agilab-analysis-save"><button type="submit" disabled={!dirty}>Save selection</button>
        {(dirty || data.save_error) && <button type="button" onClick={() => {
          setViews(data.selected_views); setNotebooks(data.selected_notebooks); emit({ kind: "discard" });
        }}>Discard changes</button>}
        <span role="status">{data.save_error || (dirty ? "Unsaved selection" : "Selection saved")}</span></div>
    </form>
    <aside className="agilab-analysis-export" aria-label="Notebook export">
      <div><h2>Use your app in Jupyter</h2>
        <p>Workflow exports your pipeline as a notebook. Supported maps and curves render directly in Jupyter.</p></div>
      <button type="button" disabled={!data.project || !data.export_available}
        onClick={() => emit({ kind: "export_notebook" })}>Export app to notebook</button>
    </aside>
  </section>;
}

const roots = new WeakMap();
export default function({ parentElement, data, setTriggerValue }) {
  let entry = roots.get(parentElement);
  if (!entry) {
    const element = document.createElement("div");
    parentElement.appendChild(element);
    entry = { element, root: createRoot(element) };
    roots.set(parentElement, entry);
  }
  const View = data.view === "project_workspace" ? ProjectWorkspace
    : data.view === "analysis_workspace" ? AnalysisWorkspace : MainInterface;
  entry.root.render(<View data={data} onAction={action => setTriggerValue("action", action)}/>);
  return () => { entry.root.unmount(); entry.element.remove(); roots.delete(parentElement); };
}
