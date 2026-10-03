import React, { useId } from "react";
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
      <p className="agilab-notebook-note">Notebook exports keep the same analysis charts and coordinate views.</p>
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
    <p className="agilab-notebook-note">Export from Analysis to keep your maps and curves in Jupyter.</p>
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
  const View = data.view === "project_workspace" ? ProjectWorkspace : MainInterface;
  entry.root.render(<View data={data} onAction={action => setTriggerValue("action", action)}/>);
  return () => { entry.root.unmount(); entry.element.remove(); roots.delete(parentElement); };
}
