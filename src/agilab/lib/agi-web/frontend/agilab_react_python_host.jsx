import React, {createContext, useCallback, useContext, useEffect, useId, useRef, useState} from "react";
import {createRoot} from "react-dom/client";
import {markdownHTML, mathHTML, sanitizeHTML} from "./agilab_python_view_markup.js";
import {PythonLinkAction, safeURL} from "./agilab_python_link_action.jsx";
import "./agilab_react_python_host.css";

const View = createContext(null);

function Markup({body}) {
  return <div dangerouslySetInnerHTML={{__html: sanitizeHTML(body)}}/>;
}

function Markdown({body}) {
  return <div className="py-markdown" dangerouslySetInnerHTML={{__html: markdownHTML(body)}}/>;
}

function Island({node}) {
  const {send, toolsPanel} = useContext(View), element = useRef(null), module = useRef(null), dispose = useRef(null), latest = useRef(null);
  latest.current = {node, toolsPanel};
  const paint = () => {
    const {node: current, toolsPanel: controls} = latest.current;
    if (!module.current) return;
    dispose.current = module.current.default({
      parentElement: element.current._parent, data: current.props.data, toolsPanel: controls,
      setStateValue: (field, value) => send(current, value, {field}),
      setTriggerValue: (field, value) => send(current, value, {field, trigger: true}),
    });
  };
  useEffect(() => {
    let cancelled = false;
    const parent = node.props.isolate_styles ? element.current.attachShadow({mode: "open"}) : element.current;
    const style = document.createElement("link"); style.rel = "stylesheet"; style.href = node.props.css; parent.appendChild(style);
    element.current._parent = parent;
    import(node.props.js).then(value => {if (!cancelled) {module.current = value; paint();}});
    return () => {cancelled = true; dispose.current?.(); module.current = null;};
  }, [node.props.js, node.props.css]);
  useEffect(paint, [node.props.data, toolsPanel.available, toolsPanel.open]);
  return <div className="py-island" ref={element}/>;
}

const plotlyLibraries = new Map();
function Plot({node}) {
  const element = useRef(null);
  useEffect(() => {
    let cancelled = false, observer;
    if (!plotlyLibraries.has(node.props.library)) plotlyLibraries.set(node.props.library, new Promise((resolve, reject) => {
      const script = document.createElement("script"); script.src = node.props.library;
      script.onload = resolve; script.onerror = reject; document.head.appendChild(script);
    }));
    plotlyLibraries.get(node.props.library).then(() => {
      if (cancelled) return;
      const figure = node.props.figure;
      window.Plotly.react(element.current, figure.data, {...figure.layout, autosize: true}, {responsive: true, displaylogo: false});
      observer = new ResizeObserver(() => window.Plotly.Plots.resize(element.current)); observer.observe(element.current);
    });
    return () => {cancelled = true; observer?.disconnect(); if (element.current && window.Plotly) window.Plotly.purge(element.current);};
  }, [node.props.figure, node.props.library]);
  return <div className="py-plot" ref={element}/>;
}

function Graph({node}) {
  const element = useRef(null), [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    setError("");
    import(node.props.library).then(module => {if (!cancelled) return module.renderGraph(element.current, node.props.source);}).catch(failure => {if (!cancelled) setError(failure.message);});
    return () => {cancelled = true;};
  }, [node.props.library, node.props.source]);
  return <div className="py-graph">{error && <div role="alert" className="py-alert py-error">{error}</div>}<div ref={element}/></div>;
}

function Vega({node}) {
  const element = useRef(null), [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false, dispose;
    setError("");
    import(node.props.library).then(module => {
      if (!cancelled) return module.renderVega(element.current, node.props.spec, {width: node.props.width});
    }).then(cleanup => {
      if (cancelled) cleanup?.(); else dispose = cleanup;
    }).catch(failure => {if (!cancelled) setError(failure.message);});
    return () => {cancelled = true; dispose?.();};
  }, [node.props.library, node.props.spec, node.props.width]);
  return <div className="py-vega" data-widget-kind="altair_chart" data-widget-key={node.props.key} style={{width: "100%", minWidth: 0}}>
    {error && <div role="alert" className="py-alert py-error">{error}</div>}<div ref={element} style={{width: "100%"}}/>
  </div>;
}

function Control({node}) {
  const view = useContext(View), p = node.props;
  const [draft, setDraft] = useState(p.value);
  useEffect(() => setDraft(p.value), [p.value]);
  const value = p.form && Object.hasOwn(view.forms, node.id) ? view.forms[node.id] : draft;
  const change = (next, commit = true) => {
    setDraft(next);
    if (p.form) view.setForms(previous => ({...previous, [node.id]: next}));
    else if (commit) view.send(node, next);
  };
  const commit = next => {if (!p.form && next !== p.value) view.send(node, next);};
  const disabled = p.disabled || (view.busy && (!['button', 'form_submit_button'].includes(node.kind) || !view.buttonsReady));
  const label = p.label_visibility === "collapsed" ? null : <span>{p.label}</span>;
  const common = {disabled, "aria-label": p.label, title: p.help, id: node.id};
  let control;
  if (["checkbox", "toggle"].includes(node.kind)) return <label className="py-check"><input {...common} type="checkbox" checked={Boolean(value)} onChange={event => change(event.target.checked)}/>{label}</label>;
  if (["button", "form_submit_button"].includes(node.kind)) return <button {...common} className={p.type === "primary" ? "py-primary" : ""} type={node.kind === "form_submit_button" ? "submit" : "button"} onClick={event => {
    if (node.kind === "button") {event.preventDefault(); view.send(node, true);}
  }}>{p.label}</button>;
  if (["text_input", "text_area", "number_input"].includes(node.kind)) {
    const numeric = node.kind === "number_input";
    const properties = {...common, value: value ?? "", placeholder: p.placeholder, maxLength: p.max_chars,
      onChange: event => change(numeric && event.target.value !== "" ? Number(event.target.value) : event.target.value, false),
      onBlur: () => {if (value !== "" || !numeric) commit(value);},
      onKeyDown: event => {if (event.key === "Enter" && node.kind !== "text_area" && !p.form) {event.preventDefault(); commit(value);}}};
    control = node.kind === "text_area" ? <textarea {...properties} style={{height: p.height || 120}}/> : <input {...properties} type={numeric ? "number" : p.type === "password" ? "password" : "text"} min={p.min_value} max={p.max_value} step={p.step}/>;
  } else if (["selectbox", "radio", "pills", "segmented_control", "select_slider", "multiselect"].includes(node.kind)) {
    const multiple = node.kind === "multiselect" || p.selection_mode === "multi";
    if (["radio", "pills", "segmented_control"].includes(node.kind)) control = <div className="py-options">{p.options.map((option, index) => <label key={option}><input {...common} id={`${node.id}-${option}`} type={multiple ? "checkbox" : "radio"} name={node.id} checked={multiple ? (value || []).includes(option) : value === option} onChange={event => change(multiple ? event.target.checked ? [...value, option] : value.filter(item => item !== option) : option)}/>{p.option_labels[index]}</label>)}</div>;
    else control = <select {...common} multiple={multiple} value={multiple ? (value || []).map(String) : value ?? ""} onChange={event => change(multiple ? [...event.target.selectedOptions].map(option => Number(option.value)) : event.target.value === "" ? null : Number(event.target.value))}>
      {!multiple && <option value="" disabled={!p.allow_none}>Choose an option</option>}
      {p.options.map((option, index) => <option key={option} value={option}>{p.option_labels[index]}</option>)}
    </select>;
  } else if (node.kind === "slider") {
    const values = p.range ? value : [value];
    control = <div>{values.map((item, index) => <input {...common} key={index} id={`${node.id}-${index}`} type="range" value={item} min={p.min_value} max={p.max_value} step={p.step}
      onChange={event => {const next = Number(event.target.value); change(p.range ? values.map((v, i) => i === index ? next : v) : next, false);}}
      onPointerUp={() => commit(value)} onKeyUp={() => commit(value)}/>)}<output>{values.join(" – ")}</output></div>;
  } else if (node.kind === "date_input") {
    const values = p.range ? value : [value];
    control = <div>{values.map((item, index) => <input {...common} key={index} type="date" value={item || ""} min={p.min_value} max={p.max_value} onChange={event => change(p.range ? values.map((v, i) => i === index ? event.target.value : v) : event.target.value)}/>)}</div>;
  } else if (node.kind === "file_uploader") control = <input {...common} type="file" multiple={p.multiple} accept={p.extensions.map(extension => `.${extension.replace(/^\./, "")}`).join(",")} onChange={async event => {
    const files = await Promise.all([...event.target.files].map(file => new Promise((resolve, reject) => {
      const reader = new FileReader(); reader.onload = () => resolve({name: file.name, type: file.type, data: reader.result.split(",")[1]}); reader.onerror = reject; reader.readAsDataURL(file);
    }))); change(files);
  }}/>;
  return <label className="py-control" htmlFor={node.id}>{label}{control}{p.help && <small>{p.help}</small>}</label>;
}

function DataTable({node}) {
  const view = useContext(View), p = node.props, selected = p.value?.rows || [];
  return <div className="py-table" data-widget-kind="dataframe" data-widget-key={p.key}><table><thead><tr>{p.selection_mode && <th>Select</th>}{p.columns.map((column, index) => <th key={index}>{column}</th>)}</tr></thead><tbody>{p.rows.map((row, index) => <tr key={index}>
    {p.selection_mode && <td><input aria-label={`Select row ${index + 1}`} type="checkbox" checked={selected.includes(index)} disabled={view.busy} onChange={event => view.send(node, {rows: event.target.checked ? p.selection_mode === "single-row" ? [index] : [...selected, index] : selected.filter(item => item !== index)})}/></td>}
    {row.map((cell, cellIndex) => <td key={cellIndex}>{typeof cell === "object" ? JSON.stringify(cell) : String(cell ?? "")}</td>)}
  </tr>)}</tbody></table></div>;
}

function Tabs({node}) {
  const [selected, setSelected] = useState(0);
  return <div className="py-tabs"><div role="tablist">{node.props.labels.map((label, index) => <button key={index} role="tab" aria-selected={selected === index} onClick={() => setSelected(index)}>{label}</button>)}</div>{node.children.map((child, index) => <div key={child.id} role="tabpanel" hidden={selected !== index}><Nodes nodes={child.children}/></div>)}</div>;
}

const controls = new Set(["button", "form_submit_button", "checkbox", "toggle", "text_input", "text_area", "number_input", "slider", "selectbox", "radio", "pills", "segmented_control", "select_slider", "multiselect", "date_input", "file_uploader"]);
function Node({node}) {
  const view = useContext(View), p = node.props, content = <Nodes nodes={node.children}/>;
  if (controls.has(node.kind)) return <div data-widget-kind={node.kind} data-widget-key={p.key}><Control node={node}/></div>;
  if (node.kind === "component") return <Island node={node}/>;
  if (node.kind === "columns") return <div className="py-columns" style={{gridTemplateColumns: p.weights.map(weight => `${weight}fr`).join(" ")}}>{content}</div>;
  if (node.kind === "tabs") return <Tabs node={node}/>;
  if (node.kind === "expander" || node.kind === "status") return <details className="py-expander" data-widget-kind={node.kind} data-widget-key={p.key} data-state={p.state} open={p.expanded}><summary>{p.label}</summary>{content}</details>;
  if (node.kind === "form") return <form className="py-form" data-form={node.id} onSubmit={event => {
    event.preventDefault();
    const submitted = view.widgets[event.nativeEvent.submitter?.id];
    const button = submitted?.props.form === node.id ? submitted : Object.values(view.widgets).find(widget => widget.kind === "form_submit_button" && widget.props.form === node.id && !widget.props.disabled);
    if (button) view.send(button, true, {form_values: Object.fromEntries(Object.entries(view.forms).filter(([id]) => view.widgets[id]?.props.form === node.id))});
  }}>{content}</form>;
  if (node.kind === "dialog") return <div className="py-dialog-backdrop"><section role="dialog" aria-modal="true" aria-label={p.title}><h2>{p.title}</h2>{content}</section></div>;
  if (node.kind === "container" || node.kind === "tab") return <div className={`py-container ${p.border ? "py-border" : ""}`} style={p.height && typeof p.height === "number" ? {maxHeight: p.height, overflow: "auto"} : {}}>{content}</div>;
  if (["title", "header", "subheader"].includes(node.kind)) return React.createElement({title: "h1", header: "h2", subheader: "h3"}[node.kind], null, p.body);
  if (node.kind === "caption") return <p className="py-caption">{p.body}</p>;
  if (node.kind === "markdown") return <Markdown body={p.body}/>;
  if (node.kind === "html") return <Markup body={p.body}/>;
  if (node.kind === "latex") return <div className="py-latex" dangerouslySetInnerHTML={{__html: sanitizeHTML(mathHTML(p.body))}}/>;
  if (["text", "code", "json"].includes(node.kind)) return <pre className={`py-${node.kind}`}><code>{p.body}</code></pre>;
  if (["error", "warning", "info", "success", "exception"].includes(node.kind)) return <div className={`py-alert py-${node.kind}`} role={node.kind === "error" || node.kind === "exception" ? "alert" : "status"}>{p.body || p.message}</div>;
  if (node.kind === "metric") return <div className="py-metric"><span>{p.label}</span><strong>{p.value}</strong>{p.delta && <small>{p.delta}</small>}</div>;
  if (node.kind === "divider") return <hr/>;
  if (node.kind === "dataframe") return <DataTable node={node}/>;
  if (node.kind === "image") return <figure>{p.urls.map((url, index) => <img key={index} src={safeURL(url)} style={{maxWidth: "100%"}}/>)}{p.caption && <figcaption>{p.caption}</figcaption>}</figure>;
  if (node.kind === "progress") return <div data-widget-kind="progress" data-widget-key={p.key}><progress value={p.value} max="1"/>{p.text && <span>{p.text}</span>}</div>;
  if (node.kind === "plotly_chart") return <Plot node={node}/>;
  if (node.kind === "graphviz_chart") return <Graph node={node}/>;
  if (node.kind === "altair_chart") return <Vega node={node}/>;
  if (node.kind === "html_frame") return <iframe className="py-frame" sandbox="allow-scripts allow-downloads" srcDoc={p.body} style={{height: p.height || 450}} title="Embedded view"/>;
  if (node.kind === "iframe") return <iframe className="py-frame" src={safeURL(p.src)} style={{height: p.height || 450}} title="Embedded view"/>;
  if (["download_button", "link_button", "page_link"].includes(node.kind)) return <PythonLinkAction node={node} view={view}/>;
  return <div role="alert">Unsupported view element: {node.kind}</div>;
}

function Nodes({nodes}) {return nodes.map(node => <Node key={node.id} node={node}/>);}
function widgetMap(nodes, result = {}) {for (const node of nodes) {result[node.id] = node; widgetMap(node.children, result);} return result;}

export function PythonViewApp({transport = null, initialPayload = null} = {}) {
  const [payload, setPayload] = useState(initialPayload), [error, setError] = useState(""), [busy, setBusy] = useState(false), [forms, setForms] = useState({}), [showSidebar, setShowSidebar] = useState(false);
  const current = useRef(initialPayload), working = useRef(false), operations = useRef(Promise.resolve()), pending = useRef(0), operationEpoch = useRef(0);
  const [busyKind, setBusyKind] = useState(null);
  const toolsId = useId(), toolsTrigger = useRef(null);
  const setToolsOpen = useCallback((open, trigger = null) => {
    if (trigger) toolsTrigger.current = trigger;
    setShowSidebar(open);
    if (!open) toolsTrigger.current?.focus();
  }, []);
  const toggleTools = useCallback(trigger => {
    toolsTrigger.current = trigger;
    setShowSidebar(open => !open);
  }, []);
  const runOperation = (kind, job) => {
    const epoch = operationEpoch.current;
    pending.current += 1;
    if (!working.current) {working.current = true; setBusy(true); setBusyKind(kind);}
    const next = operations.current.then(async () => {
      try {
        if (epoch !== operationEpoch.current) return;
        setBusyKind(kind);
        await job();
      } catch (failure) {operationEpoch.current += 1; setError(failure.message);}
      finally {pending.current -= 1; if (!pending.current) {working.current = false; setBusy(false); setBusyKind(null);}}
    });
    operations.current = next;
    return next;
  };
  const accept = (next, replace = false) => {
    if (current.current?.path !== next.path) setShowSidebar(false);
    current.current = next; setPayload(next); setError("");
    if (transport) return;
    document.title = next.config.page_title || "AGILAB";
    const url = new URL(next.path, location.origin);
    Object.entries(next.query).forEach(([key, values]) => (Array.isArray(values) ? values : [values]).forEach(value => url.searchParams.append(key, value)));
    if (url.pathname + url.search !== location.pathname + location.search) history[replace ? "replaceState" : "pushState"]({}, "", url);
  };
  const load = (target = null, replace = false) => runOperation("navigation", async () => {
      const base = transport ? new URL(current.current?.path || "/", "https://agi-web.invalid") : new URL(location.href);
      const url = target == null ? base : target instanceof URL ? target : new URL(target, base);
      let next;
      if (transport) {
        const query = {...(current.current?.query || {})};
        if (target != null) for (const key of new Set(url.searchParams.keys())) {
          const values = url.searchParams.getAll(key); query[key] = values.length === 1 ? values[0] : values;
        }
        next = await transport.render({path: url.pathname, query});
      }
      else {
        if (typeof target === "string") for (const key of new Set(base.searchParams.keys())) {
          if (!url.searchParams.has(key)) for (const value of base.searchParams.getAll(key)) url.searchParams.append(key, value);
        }
        const parameters = new URLSearchParams(url.search); parameters.set("path", url.pathname);
        const response = await fetch(`/api/view?${parameters}`);
        next = await response.json(); if (!response.ok) throw new Error(next.error);
      }
      setForms({}); accept(next, replace);
  });
  const send = (node, value, extra = {}) => {
    const context = JSON.stringify([current.current.path, current.current.query]);
    return runOperation(node.kind, async () => {
    if (context !== JSON.stringify([current.current.path, current.current.query])) throw new Error("The view changed while this action was waiting. Try again.");
    const registered = widgetMap([...current.current.nodes.main, ...current.current.nodes.sidebar])[node.id];
    if (!registered || registered.kind !== node.kind) throw new Error("This control is no longer registered. Refresh the view.");
    const progress = transport ? null : setInterval(async () => {
      try {
        const response = await fetch("/api/progress");
        if (response.ok) {const snapshot = await response.json(); if (working.current && snapshot.running) setPayload(snapshot);}
      } catch { /* The action response reports any transport failure. */ }
    }, 350);
    try {
      const action = {id: node.id, value, revision: current.current.revision, csrf_token: current.current.csrf_token, ...extra};
      let next;
      if (transport) next = await transport.action(action);
      else {
        const response = await fetch("/api/action", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(action)});
        next = await response.json(); if (!response.ok) throw new Error(next.error);
      }
      if (node.kind === "form_submit_button") setForms(previous => Object.fromEntries(Object.entries(previous).filter(([id]) => widgetMap([...current.current.nodes.main, ...current.current.nodes.sidebar])[id]?.props.form !== node.props.form)));
      accept(next);
    } finally {clearInterval(progress);}
    });
  };
  useEffect(() => {
    if (!initialPayload) load(undefined, true);
    if (transport) return;
    const back = () => load(new URL(location.href), true); window.addEventListener("popstate", back); return () => window.removeEventListener("popstate", back);
  }, []);
  useEffect(() => {
    if (!payload?.auto_refresh) return;
    const interval = setInterval(() => {if (!working.current && !Object.keys(forms).length && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) load();}, Math.max(1, payload.auto_refresh) * 1000);
    return () => clearInterval(interval);
  }, [payload?.auto_refresh, forms]);
  if (!payload) return <main className="py-loading">{error || "Opening AGILAB…"}</main>;
  const hasSidebar = payload.nodes.sidebar.length > 0;
  const sidebarOpen = hasSidebar && showSidebar;
  const widgets = widgetMap([...payload.nodes.main, ...payload.nodes.sidebar]);
  const hasWorkspaceTools = Object.values(widgets).some(node =>
    node.kind === "component" && node.props.name === "agilab_react_main_interface" && Array.isArray(node.props.data?.routes));
  const toolsPanel = {available: hasSidebar, open: sidebarOpen, setOpen: setToolsOpen};
  const value = {send, navigate: load, busy, buttonsReady: ["text_input", "text_area", "number_input"].includes(busyKind), forms, setForms, widgets, toolsPanel};
  return <View.Provider value={value}><div className={`py-app ${sidebarOpen ? "py-with-sidebar" : ""}`} aria-busy={busy} data-operation={busyKind}
    onKeyDown={event => {
      if (event.key === "Escape" && sidebarOpen && !event.defaultPrevented) {
        event.preventDefault(); setToolsOpen(false);
      }
    }}>
    {busy && <div className="py-working" role="status">Working…</div>}
    {hasSidebar && <aside id={toolsId} data-region="sidebar" aria-label="Contextual tools" hidden={!sidebarOpen}>
      <div className="py-tools-heading"><h2>Tools</h2>
        <button type="button" onClick={() => setToolsOpen(false)}>Close tools</button></div>
      <Nodes nodes={payload.nodes.sidebar}/>
    </aside>}
    <main>{hasSidebar && !hasWorkspaceTools && <button type="button" className="py-sidebar-toggle"
      onClick={event => toggleTools(event.currentTarget)} aria-expanded={sidebarOpen} aria-controls={toolsId}>Tools</button>}
      {error && <div role="alert" className="py-alert py-error">{error}</div>}<Nodes nodes={payload.nodes.main}/></main>
  </div></View.Provider>;
}

export function mountPythonView(element, options = {}) {
  const root = createRoot(element); root.render(<PythonViewApp {...options}/>);
  return () => root.unmount();
}

const entry = document.getElementById("agilab-python-root");
if (entry) mountPythonView(entry);
