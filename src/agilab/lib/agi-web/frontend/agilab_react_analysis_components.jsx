import React, { memo, useCallback, useState, useMemo, useEffect, useRef, useId } from "react";

const colors = ["#2563eb", "#f97316", "#059669", "#9333ea", "#dc2626", "#0891b2"];
const W = 760, H = 340, pad = 52;
const finite = (value) => typeof value === "number" && Number.isFinite(value);
function extent(values, singleMargin) {
  let lo = Infinity, hi = -Infinity;
  for (const value of values) { if (value < lo) lo = value; if (value > hi) hi = value; }
  if (!finite(lo)) return [0, 1];
  const margin = lo === hi ? (singleMargin ?? Math.max(Math.abs(lo) * .01, 1)) : (hi - lo) * .06;
  return [lo - margin, hi + margin];
}
function formatNumber(value, step) {
  const digits = Math.max(3, Math.ceil(Math.log10(Math.max(Math.abs(value), step) / step)) + 1);
  return Number(value.toPrecision(Math.min(digits, 15))).toString();
}
function formatDate(value, step) {
  const whole = Math.floor(value), date = new Date(whole), iso = date.toISOString();
  if (step >= 86400000) return iso.slice(0, 10);
  if (step >= 60000) return iso.slice(5, 16).replace("T", " ");
  if (step >= 1000) return iso.slice(5, 19).replace("T", " ");
  if (step >= 1) return iso.slice(5, 23).replace("T", " ");
  const micros = date.getUTCMilliseconds() * 1000 + Math.floor((value - whole) * 1000);
  return `${iso.slice(5, 19).replace("T", " ")}.${String(micros).padStart(6, "0")}`;
}
function scaleGeometry(xs, ys, zoom, xSingleMargin) {
  const [xa, xb] = extent(xs, xSingleMargin), [ya, yb] = extent(ys);
  const xm = (xa + xb) / 2, ym = (ya + yb) / 2;
  const x0 = xm - (xb - xa) / (2 * zoom), x1 = xm + (xb - xa) / (2 * zoom);
  const y0 = ym - (yb - ya) / (2 * zoom), y1 = ym + (yb - ya) / (2 * zoom);
  const x = (v) => pad + (v - x0) / (x1 - x0) * (W - pad * 2);
  const y = (v) => H - pad - (v - y0) / (y1 - y0) * (H - pad * 2);
  return {x0, x1, y0, y1, x, y};
}
function Scale({ children, xs, ys, xLabel, yLabel, zoom = 1, xSingleMargin, formatX = formatNumber }) {
  const clipId = useId();
  const {x0, x1, y0, y1, x, y} = useMemo(() => scaleGeometry(xs, ys, zoom, xSingleMargin),
    [xs, ys, zoom, xSingleMargin]);
  return <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${yLabel} against ${xLabel}`}>
    {Array.from({length: 5}, (_, i) => {
      const xv = x0 + (x1 - x0) * i / 4, yv = y0 + (y1 - y0) * i / 4;
      return <g key={i}><line className="agilab-grid" x1={pad} x2={W-pad} y1={y(yv)} y2={y(yv)}/>
        <text x={x(xv)} y={H-pad+21} textAnchor="middle">{formatX(xv, (x1 - x0) / 4)}</text>
        <text x={pad-8} y={y(yv)+4} textAnchor="end">{formatNumber(yv, (y1 - y0) / 4)}</text></g>;
    })}
    <text x={W/2} y={H-6} textAnchor="middle">{xLabel}</text>
    <text transform={`translate(14 ${H/2}) rotate(-90)`} textAnchor="middle">{yLabel}</text>
    <defs><clipPath id={clipId}><rect x={pad} y={pad} width={W-pad*2} height={H-pad*2}/></clipPath></defs>
    <g clipPath={`url(#${clipId})`}>{children({x, y})}</g>
  </svg>;
}
function Selection({ point }) {
  return <output className="agilab-selection" aria-live="polite">
    {point ? point.label : "Select a point to inspect its recorded values."}
  </output>;
}
function Range({ first, last, start, end, setStart, setEnd, format }) {
  return <div className="agilab-range">
    <label>From <input aria-label="Range start" type="range" min={first} max={last}
      value={start} onChange={e => setStart(Math.min(+e.target.value, end))}/><span>{format(start)}</span></label>
    <label>To <input aria-label="Range end" type="range" min={first} max={last}
      value={end} onChange={e => setEnd(Math.max(+e.target.value, start))}/><span>{format(end)}</span></label>
  </div>;
}
const MapMarker = memo(function MapMarker({point, cx, cy, radius, color, selected, onChoose}) {
  return <circle cx={cx} cy={cy} r={radius} fill={color} stroke={selected ? "currentColor" : "none"}
    tabIndex="0" role="button" aria-label={`Position ${point.label}`}
    onClick={() => onChoose(point)}
    onKeyDown={e => {if(e.key === "Enter" || e.key === " "){e.preventDefault(); onChoose(point);}}}>
    <title>{`${point.label}: ${point.latitude}, ${point.longitude}`}</title></circle>;
});
const MapMarkers = memo(function MapMarkers({points, x, y, zoom, groupColors, selectedRow, onChoose}) {
  const positions = useMemo(() => points.map(point => ({point, row: point.row,
    cx: x(point.longitude), cy: y(point.latitude), color: groupColors.get(point.group)})),
  [points, x, y, groupColors]);
  const radius = 4 / Math.sqrt(zoom);
  return <g>{positions.map(position => <MapMarker key={position.row} point={position.point}
    cx={position.cx} cy={position.cy} radius={radius} color={position.color}
    selected={selectedRow === position.row} onChoose={onChoose}/>)}</g>;
});
export function CoordinateMap({ payload, payloadKey, onSelection }) {
  const groups = useMemo(() => [...new Set(payload.points.map(p => p.group))], [payload, payloadKey]);
  const groupColors = useMemo(() => new Map(groups.map((g, i) => [g, colors[i % colors.length]])), [groups]);
  const [group, setGroup] = useState(""), [selected, setSelected] = useState(null);
  const [zoom, setZoom] = useState(1);
  const previousKey = useRef(payloadKey);
  useEffect(() => { if (previousKey.current === payloadKey) return;
    previousKey.current = payloadKey; setGroup(""); setSelected(null); setZoom(1); onSelection({});
  }, [payloadKey]);
  const clearSelection = () => { if (selected) onSelection({}); setSelected(null); };
  const points = useMemo(() => payload.points.filter(p => group === "" || p.group === groups[Number(group)]),
    [payload, payloadKey, group, groups]);
  const {xs, ys} = useMemo(() => ({xs: points.map(p => p.longitude), ys: points.map(p => p.latitude)}), [points]);
  const choose = useCallback((point) => {
    setSelected(point);
    onSelection({row: point.row, label: point.label, latitude: point.latitude, longitude: point.longitude});
  }, [onSelection]);
  return <>
    <div className="agilab-toolbar">
      <label>Group <select aria-label="Map group" value={group} onChange={e => {setGroup(e.target.value); clearSelection();}}>
        <option value="">All groups</option>{groups.map((g, i) => <option key={g} value={i}>{g || "(empty)"}</option>)}</select></label>
      <label>Zoom <input aria-label="Map zoom" type="range" min="1" max="5" step=".25"
        value={zoom} onChange={e => setZoom(+e.target.value)}/></label>
      <button onClick={() => {setGroup(""); setZoom(1); setSelected(null); onSelection({});}}>Reset view</button>
    </div>
    <p className="agilab-hint">Longitude/latitude coordinates. {points.length} positions; no basemap required.</p>
    {points.length ? <Scale xs={xs} ys={ys} zoom={zoom} xLabel="Longitude (degrees)" yLabel="Latitude (degrees)">
      {({x, y}) => <MapMarkers points={points} x={x} y={y} zoom={zoom} groupColors={groupColors}
        selectedRow={selected?.row} onChoose={choose}/>}
    </Scale> : <p>No valid coordinates in this selection.</p>}
    <Selection point={selected && {...selected, label: `${selected.label}: latitude ${selected.latitude}, longitude ${selected.longitude}`}}/>
  </>;
}
const CurvesPlot = memo(function CurvesPlot({rows, active, xs, ys, payload, onChoose}) {
  const formatX = payload.x_type === "datetime" ? formatDate : formatNumber;
  return <Scale xs={xs} ys={ys}
    xLabel={payload.x_type === "datetime" ? `${payload.x_label} (UTC)` : payload.x_label}
    yLabel={payload.y_label} formatX={formatX} xSingleMargin={payload.x_type === "datetime" ? 43200000 : undefined}>
    {({x, y}) => active.map(({series: s, color}) => {
      let penDown = false;
      const d = rows.map(r => {const v = r.values[s.id]; if (!finite(v)){penDown=false; return "";}
        const command = penDown ? "L" : "M"; penDown=true; return `${command}${x(r.x)},${y(v)}`;}).join(" ");
      return <g key={s.id}><path d={d} fill="none" stroke={color} strokeWidth="2"/>
        {rows.map(r => {
          if (!finite(r.values[s.id])) return false;
          const choose = () => onChoose({row:r.row, series:s.id, x:r.x, y:r.values[s.id],
            label:`${s.label} — ${r.label}: ${r.values[s.id]}`});
          return <circle key={r.row} cx={x(r.x)} cy={y(r.values[s.id])} r="4"
            fill={color} tabIndex="0" role="button" aria-label={`${s.label} ${r.label}`}
            onClick={choose} onKeyDown={e => {if(e.key==="Enter"){e.preventDefault(); choose();}}}>
            <title>{`${s.label} — ${r.label}: ${r.values[s.id]}`}</title></circle>;
        })}</g>;
    })}
  </Scale>;
});
export function AnalysisCurves({ payload, payloadKey, onSelection }) {
  const [visible, setVisible] = useState(payload.series.map(s => s.id));
  const [start, setStart] = useState(0), [end, setEnd] = useState(Math.max(payload.rows.length - 1, 0));
  const [selected, setSelected] = useState(null);
  const previousKey = useRef(payloadKey);
  useEffect(() => { if (previousKey.current === payloadKey) return;
    previousKey.current = payloadKey; setVisible(payload.series.map(s => s.id)); setStart(0);
    setEnd(Math.max(payload.rows.length - 1, 0)); setSelected(null); onSelection({});
  }, [payloadKey]);
  const clearSelection = () => { if (selected) onSelection({}); setSelected(null); };
  const {rows, ids, active, xs, ys} = useMemo(() => {
    const rows = payload.rows.slice(start, end+1), ids = new Set(visible);
    const active = payload.series.flatMap((series, index) => ids.has(series.id)
      ? [{series, color: colors[index % colors.length]}] : []);
    return {rows, ids, active, xs: rows.map(r => r.x),
      ys: rows.flatMap(r => active.map(({series}) => r.values[series.id]).filter(finite))};
  }, [payload, payloadKey, start, end, visible]);
  const choose = useCallback(value => {setSelected(value); onSelection(value);}, [onSelection]);
  return <>
    <fieldset className="agilab-series"><legend>Series</legend>{payload.series.map((s, i) =>
      <label key={s.id} style={{color: colors[i%colors.length]}}><input type="checkbox" checked={ids.has(s.id)}
        onChange={e => {setVisible(e.target.checked ? [...visible, s.id] : visible.filter(id => id !== s.id)); clearSelection();}}/>{s.label}</label>)}</fieldset>
    {payload.rows.length > 1 && <Range first={0} last={payload.rows.length-1} start={start} end={end}
      setStart={value => {setStart(value); clearSelection();}}
      setEnd={value => {setEnd(value); clearSelection();}} format={i => payload.rows[i]?.label ?? ""}/>}
    {rows.length > 0 && active.length > 0 ? <CurvesPlot rows={rows} active={active} xs={xs} ys={ys}
      payload={payload} onChoose={choose}/> : <p>No series selected or no data in the range.</p>}
    <Selection point={selected}/>
    <button onClick={() => {setVisible(payload.series.map(s => s.id));setStart(0);setEnd(Math.max(payload.rows.length-1,0));
      setSelected(null);onSelection({});}}>Reset view</button>
  </>;
}
export function AnalysisComponent({ component, onSelection }) {
  const payloadKey = `${component.component_id}:${component.evidence.payload_hash}`;
  return <section className="agilab-react-analysis" data-component-id={component.component_id}
    onKeyDown={event => event.stopPropagation()}>
    <h3>{component.title}</h3>
    {component.payload.kind === "coordinate_map"
      ? <CoordinateMap payload={component.payload} payloadKey={payloadKey} onSelection={onSelection}/>
      : <AnalysisCurves payload={component.payload} payloadKey={payloadKey} onSelection={onSelection}/>}
    {component.payload.invalid_rows > 0 && <p>{component.payload.invalid_rows} invalid rows excluded from this chart.</p>}
    {component.payload.omitted_rows > 0 && <p>{component.payload.omitted_rows} rows omitted from this chart; full data remains in the artifact.</p>}
  </section>;
}
