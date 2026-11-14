// Preserve pydeck's own converter, accessors, tooltip and provider implementation.
export {createDeck as createDeckJS, addCustomLibraries, jsonConverter} from "@deck.gl/jupyter-widget/src/playground/create-deck.js";
export {setMaplibreWorkerUrl} from "./agilab_pydeck_maplibre.js";
import * as deckExports from "@deck.gl/jupyter-widget/src/deck-bundle.js";
import * as lumaExports from "@deck.gl/core/scripting/lumagl";
import * as loadersExports from "@deck.gl/core/scripting/loadersgl";
Object.assign(globalThis.deck ||= {}, deckExports);
Object.assign(globalThis.luma ||= {}, lumaExports);
Object.assign(globalThis.loaders ||= {}, loadersExports);
