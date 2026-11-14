// Qualified for pinned MapLibre 6.4.1: upstream pydeck imports the v5 namespace as a default.
// MapLibre 6 exposes that API through named exports. No provider selection changes.
import * as maplibre from "./node_modules/maplibre-gl/dist/maplibre-gl.mjs";
export function setMaplibreWorkerUrl(url) { maplibre.setWorkerUrl(url); }
export default maplibre;
