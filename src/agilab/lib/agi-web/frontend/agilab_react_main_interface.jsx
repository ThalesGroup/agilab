import React, { useEffect, useId, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";

const WORKBENCH_LAYOUT_VERSION = 1;
export const workbenchLayoutKey = project => `agilab.operator-workbench.layout.v1:${encodeURIComponent(project || "")}`;

export function normalizeWorkbenchLayout(candidate, workbench) {
  const profiles = workbench.profiles || [], panes = workbench.panes || [];
  const saved = candidate?.version === WORKBENCH_LAYOUT_VERSION ? candidate : {};
  const profile = profiles.find(item => item.id === saved.profile_id) || profiles[0];
  const pane = panes.find(item => item.id === saved.pane_id) ||
    panes.find(item => item.id === profile?.pane_id) || panes[0];
  return { version: WORKBENCH_LAYOUT_VERSION, profile_id: profile?.id || "", split: saved.split === true,
    pane_id: pane?.id || "" };
}

function readWorkbenchLayout(project, workbench) {
  try {
    const text = window.localStorage.getItem(workbenchLayoutKey(project));
    return normalizeWorkbenchLayout(text && text.length <= 4096 ? JSON.parse(text) : null, workbench);
  } catch { return normalizeWorkbenchLayout(null, workbench); }
}

function WorkbenchPane({ pane, profile, data, commands, onCommand }) {
  const workbench = data.workbench;
  return <aside className="agilab-workbench-pane" aria-label={pane.label}>
    <h2>{pane.label}</h2>
    {pane.description && <p>{pane.description}</p>}
    {pane.kind === "diagnostics" ? <dl className="agilab-workbench-diagnostics">
      {(workbench.diagnostics || []).map(item => <div key={item.id || item.label}>
        <dt>{item.label}</dt><dd>{item.value ?? "Unavailable"}</dd>
      </div>)}
    </dl> : pane.kind === "commands" ? <div className="agilab-workbench-pane-commands">
      {commands.filter(item => !item.profile_ids || item.profile_ids.includes(profile.id)).map(command =>
        <button key={command.id} type="button" disabled={command.disabled}
          title={command.reason || command.description} onClick={() => onCommand(command)}>{command.label}</button>)}
    </div> : pane.kind === "activity" ? <p>{workbench.activity || "Commands open an existing workspace. Execution and its evidence remain in that workspace."}</p> :
      <dl className="agilab-workbench-diagnostics">
        <div><dt>Project</dt><dd>{data.project || "No project selected"}</dd></div>
        <div><dt>Profile</dt><dd>{profile.label}</dd></div>
        <div><dt>Current workspace</dt><dd>{data.routes.find(item => item.id === data.route)?.label || data.route}</dd></div>
      </dl>}
  </aside>;
}

export function OperatorWorkbench({ data, onAction }) {
  const workbench = data.workbench;
  const profiles = workbench.profiles, panes = workbench.panes;
  const commands = useMemo(() => (workbench.commands || []).filter(item => typeof item.id === "string"), [workbench.commands]);
  const [layout, setLayout] = useState(() => readWorkbenchLayout(data.project, workbench));
  const selected = normalizeWorkbenchLayout(layout, workbench);
  const profile = profiles.find(item => item.id === selected.profile_id), pane = panes.find(item => item.id === selected.pane_id);
  const [open, setOpen] = useState(false), [query, setQuery] = useState(""), [active, setActive] = useState(0);
  const [review, setReview] = useState(null), [message, setMessage] = useState("");
  const dialog = useRef(null), search = useRef(null), previousFocus = useRef(null);
  const profileSelectId = useId(), paneSelectId = useId(), dialogTitleId = useId(), listId = useId();
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return commands.filter(item => `${item.label} ${item.description || ""}`.toLocaleLowerCase().includes(needle));
  }, [commands, query]);
  const safeActive = filtered[active] && !filtered[active].disabled ? active : filtered.findIndex(item => !item.disabled);
  useEffect(() => {
    try { window.localStorage.setItem(workbenchLayoutKey(data.project), JSON.stringify(selected)); } catch { /* Storage can be disabled. */ }
  }, [data.project, selected.profile_id, selected.split, selected.pane_id]);
  useEffect(() => {
    const shortcut = event => {
      if (event.defaultPrevented || event.repeat || event.altKey || !(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "k") return;
      event.preventDefault(); setOpen(true); setReview(null); setQuery(""); setActive(0); setMessage("");
    };
    document.addEventListener("keydown", shortcut, true);
    return () => document.removeEventListener("keydown", shortcut, true);
  }, []);
  useEffect(() => {
    if (!open) return;
    let focused = document.activeElement;
    while (focused?.shadowRoot?.activeElement) focused = focused.shadowRoot.activeElement;
    previousFocus.current = focused;
    const node = dialog.current;
    node.showModal(); search.current?.focus();
    return () => { node.close(); if (previousFocus.current?.isConnected) previousFocus.current.focus(); };
  }, [open]);
  useEffect(() => {
    if (open && review) dialog.current?.querySelector("button")?.focus();
    else if (open) search.current?.focus();
  }, [review, open]);
  useEffect(() => {
    if (open && !review && safeActive >= 0) dialog.current?.querySelectorAll("[role=option]")[safeActive]?.scrollIntoView?.({ block: "nearest" });
  }, [open, review, safeActive, query, listId]);
  const close = () => { setOpen(false); setReview(null); };
  const execute = command => {
    onAction({ kind: "workbench_command", value: command.id, project: data.project, route: data.route,
      ...(command.requires_review ? { reviewed: true } : {}) });
    close();
  };
  const choose = command => {
    if (command.disabled) return;
    if (command.requires_review) {
      setReview({ id: command.id, kind: command.kind, value: command.value, project: data.project }); setOpen(true); setMessage("");
    } else execute(command);
  };
  const reviewedCommand = commands.find(item => item.id === review?.id);
  const reviewCurrent = reviewedCommand && !reviewedCommand.disabled && review.project === data.project &&
    review.kind === reviewedCommand.kind && review.value === reviewedCommand.value;
  const openPalette = () => { setReview(null); setQuery(""); setActive(0); setMessage(""); setOpen(true); };
  return <section className="agilab-operator-workbench" aria-label="Operator workbench">
    <div className="agilab-workbench-toolbar">
      <label htmlFor={profileSelectId}>Profile</label>
      <select id={profileSelectId} value={selected.profile_id} onChange={event => {
        const next = profiles.find(item => item.id === event.target.value);
        setLayout({ ...selected, profile_id: next.id, pane_id: panes.some(item => item.id === next.pane_id) ? next.pane_id : selected.pane_id });
      }}>
        {profiles.map(item => <option key={item.id} value={item.id} disabled={item.disabled}>{item.label}</option>)}
      </select>
      <button type="button" onClick={openPalette} aria-haspopup="dialog">Commands <kbd>⌘/Ctrl K</kbd></button>
      <button type="button" aria-pressed={selected.split} onClick={() => setLayout({ ...selected, split: !selected.split })}>
        {selected.split ? "Hide pane" : "Show pane"}</button>
      {selected.split && <><label htmlFor={paneSelectId}>Pane</label><select id={paneSelectId} value={selected.pane_id}
        onChange={event => setLayout({ ...selected, pane_id: event.target.value })}>
        {panes.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select></>}
    </div>
    <div className={`agilab-workbench-layout${selected.split && pane ? " agilab-workbench-layout--split" : ""}`}>
      <div className="agilab-workbench-intent">
        <p>{profile.description}</p>
        <button type="button" disabled={profile.disabled || !data.routes.some(item => item.id === profile.route)}
          title={profile.reason} onClick={() => onAction({ kind: "navigate", value: profile.route, project: data.project, route: data.route })}>
          Open {profile.label}</button>
      </div>
      {selected.split && pane && <WorkbenchPane pane={pane} profile={profile} data={data} commands={commands} onCommand={choose}/>}
    </div>
    <dialog ref={dialog} className="agilab-command-palette" aria-labelledby={dialogTitleId}
      onCancel={event => { event.preventDefault(); close(); }}
      onClose={event => { if (open && !event.currentTarget.open) close(); }}
      onKeyDown={event => { if (event.key === "Escape") { event.preventDefault(); close(); } event.stopPropagation(); }}>
      <div className="agilab-command-palette-heading"><h2 id={dialogTitleId}>{review ? "Review command" : "Workspace commands"}</h2>
        <button type="button" aria-label="Close commands" onClick={close}>Close</button></div>
      {review ? <div className="agilab-command-review">
        <h3>{reviewedCommand?.label || "Command unavailable"}</h3>
        <p>{reviewedCommand?.description}</p><p>Project: <strong>{review.project || "No project selected"}</strong></p>
        {!reviewCurrent && <p role="alert">The command or project changed. Select the command again before executing.</p>}
        <div className="agilab-command-review-actions">
          <button type="button" onClick={() => { setReview(null); setMessage(""); }}>Back to commands</button>
          <button type="button" className="agilab-primary-action" disabled={!reviewCurrent}
            onClick={() => reviewCurrent ? execute(reviewedCommand) : setMessage("Select the current command again.")}>Execute command</button>
        </div>
      </div> : <>
        <label htmlFor={`${listId}-search`}>Find a command</label>
        <input ref={search} id={`${listId}-search`} type="search" role="combobox" autoComplete="off" value={query}
          aria-expanded="true" aria-controls={listId} aria-autocomplete="list"
          aria-activedescendant={safeActive >= 0 ? `${listId}-${safeActive}` : undefined}
          onChange={event => { setQuery(event.target.value); setActive(0); }} onKeyDown={event => {
            if (event.key === "Enter" && !event.nativeEvent.isComposing && safeActive >= 0) {
              event.preventDefault(); choose(filtered[safeActive]);
            } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              const step = event.key === "ArrowDown" ? 1 : -1;
              for (let distance = 1; distance <= filtered.length; distance += 1) {
                const next = (Math.max(safeActive, 0) + step * distance + filtered.length) % filtered.length;
                if (!filtered[next].disabled) { setActive(next); break; }
              }
            }
          }}/>
        <ul id={listId} role="listbox" aria-label="Matching commands">
          {filtered.map((command, index) => <li key={command.id} id={`${listId}-${index}`} role="option"
            aria-selected={index === safeActive} aria-disabled={command.disabled || undefined}>
            <button type="button" disabled={command.disabled} onClick={() => choose(command)}>
              <strong>{command.label}</strong><span>{command.reason || command.description}</span>
              {command.requires_review && <small>Review required</small>}
            </button>
          </li>)}
        </ul>
        {!filtered.length && <p role="status">No matching commands.</p>}
        <p className="agilab-command-palette-help">Use ↑ ↓ and Enter. Escape closes this palette. Opening a workspace does not run a pipeline.</p>
      </>}
      {message && <p role="status">{message}</p>}
    </dialog>
  </section>;
}

export function MainInterface({ data, onAction, toolsPanel = null }) {
  const projectId = useId(), toolsSummary = useRef(null);
  const contextualTools = toolsPanel?.available ? toolsPanel : null;
  const emit = (kind, value) => onAction({ kind, value, project: data.project, route: data.route });
  const navigate = id => emit("navigate", id);
  const routeButton = route => <button key={route.id} type="button"
    aria-current={data.route === route.id ? "page" : undefined}
    onClick={() => navigate(route.id)}>{route.label}</button>;
  return <section className="agilab-main-interface" aria-label="AGILAB workspace"
    onKeyDown={event => {
      if (event.key === "Escape" && contextualTools?.open && !event.defaultPrevented) {
        event.preventDefault(); contextualTools.setOpen(false, toolsSummary.current);
      }
      event.stopPropagation();
    }}>
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
      <details className="agilab-workspace-tools" open={contextualTools?.open}
        onToggle={contextualTools ? event => contextualTools.setOpen(event.currentTarget.open, toolsSummary.current) : undefined}>
        <summary ref={toolsSummary} aria-expanded={contextualTools?.open}>Tools</summary>
        <div>{data.routes.filter(route => !route.primary).map(routeButton)}</div>
      </details>
    </nav>
    {data.workbench?.schema_version === 1 && data.workbench.profiles?.length && data.workbench.panes?.length ?
      <OperatorWorkbench key={data.project || ""} data={data} onAction={onAction}/> : null}
    {data.route === "home" && <div className="agilab-workspace-home">
      <div className="agilab-home-intro">
        <p className="agilab-eyebrow">Your workspace</p>
        <h1>{data.welcome_title}</h1>
        <p>Start with the guided demo below, or continue your selected project.</p>
      </div>
      <div className="agilab-project-summary">
        <div><small>Active project</small><h2>{data.project || "No project selected"}</h2>
          <p>Change projects using the selector above.</p></div>
        {data.project && data.project !== "flight_telemetry_project" &&
          data.routes.some(route => route.id === "workflow") &&
          <button className="agilab-primary-action" type="button" onClick={() => navigate("workflow")}>Continue this project</button>}
      </div>
      <details className="agilab-home-shortcuts">
        <summary>Workspace shortcuts and notebook export</summary>
        <div className="agilab-home-cards">
          {data.routes.filter(route => route.description).map(route => <button type="button" key={route.id}
            onClick={() => navigate(route.id)}>
            <span className="agilab-card-title">{route.label}</span><span>{route.description}</span>
            <span className="agilab-card-link">Open workspace →</span>
          </button>)}
        </div>
        <p className="agilab-notebook-note">Export your app from Workflow to use its supported maps and charts in Jupyter.</p>
      </details>
    </div>}
  </section>;
}

export function ProjectWorkspace({ data, onAction }) {
  const navigate = value => onAction({ kind: "navigate", value, project: data.project,
    project_path: data.project_path, route: data.route });
  return <section className="agilab-main-interface agilab-project-workspace" aria-label="Project workspace"
    onKeyDown={keepWorkspaceKeysLocal}>
    <div className="agilab-home-intro">
      <p className="agilab-eyebrow">Project workspace</p>
      <h1>{data.project || "No project selected"}</h1>
      <p>Review your environment and data, then run the project or explore its results.</p>
    </div>
    <div className="agilab-project-health" aria-label="Environment health">
      {data.cards.map(card => <article key={card.label}
        className={`agilab-health-card agilab-health-card--${card.display_state || card.state}`}>
        <h2>{card.label}</h2><p className="agilab-health-value">{card.value}</p>
        <p className="agilab-health-caption">{card.caption}</p>
        <small>{card.status_label || (card.state === "incomplete" ? "Needs attention" : "Ready")}</small>
      </article>)}
    </div>
    <nav className="agilab-home-cards agilab-project-actions" aria-label="Project actions">
      {data.actions.map(action => <button type="button" key={action.id} disabled={!data.project}
        onClick={() => navigate(action.id)}>
        <span className="agilab-card-title">{action.label}</span><span>{action.description}</span>
        <span className="agilab-card-link">Open workspace →</span>
      </button>)}
    </nav>
    <p className="agilab-notebook-note">Open Analysis to explore results and access the notebook export in Workflow.</p>
  </section>;
}

function keepWorkspaceKeysLocal(event) {
  // Escape belongs to the native host so contextual Tools can close and restore focus.
  if (event.key !== "Escape") event.stopPropagation();
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
    onKeyDown={keepWorkspaceKeysLocal}>
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
export default function({ parentElement, data, setTriggerValue, toolsPanel = null }) {
  let entry = roots.get(parentElement);
  if (!entry) {
    const element = document.createElement("div");
    parentElement.appendChild(element);
    entry = { element, root: createRoot(element) };
    roots.set(parentElement, entry);
  }
  const View = data.view === "project_workspace" ? ProjectWorkspace
    : data.view === "analysis_workspace" ? AnalysisWorkspace : MainInterface;
  entry.root.render(<View data={data} toolsPanel={toolsPanel} onAction={action => setTriggerValue("action", action)}/>);
  return () => { entry.root.unmount(); entry.element.remove(); roots.delete(parentElement); };
}
