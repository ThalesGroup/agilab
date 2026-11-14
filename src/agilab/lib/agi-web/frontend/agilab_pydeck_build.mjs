import {build} from "esbuild";
import {access, mkdir, readFile, readdir, writeFile} from "node:fs/promises";
import {createHash} from "node:crypto";
import {fileURLToPath} from "node:url";

export async function buildPydeckAssets() {
  const directory = new URL("../src/agi_web/pydeck_assets/", import.meta.url);
  await mkdir(directory, {recursive: true});
  const metadata = JSON.parse(await readFile(new URL("package.json", import.meta.url), "utf8"));
  const lock = JSON.parse(await readFile(new URL("package-lock.json", import.meta.url), "utf8"));
  const configured = metadata.agilabPydeckCustomLibraries || [];
  if (!Array.isArray(configured)) throw new Error("agilabPydeckCustomLibraries must be an array.");
  const customLibraries = {};
  const builds = [];
  if (lock.packages["node_modules/maplibre-gl"].version !== "6.4.1") throw new Error("Requalify the MapLibre 6 namespace adapter before changing its pin.");
  const alias = { "maplibre-gl": fileURLToPath(new URL("agilab_pydeck_maplibre.js", import.meta.url)),
    ...Object.fromEntries(["deckgl", "lumagl", "loadersgl"].map(name =>
      ["@deck.gl/core/scripting/" + name, fileURLToPath(new URL("node_modules/@deck.gl/core/src/scripting/" + name + ".ts", import.meta.url))]))};
  const scripting = fileURLToPath(new URL("node_modules/@deck.gl/core/src/scripting/", import.meta.url));
  const coreSource = fileURLToPath(new URL("node_modules/@deck.gl/core/src/", import.meta.url));
  const coreCompiled = fileURLToPath(new URL("node_modules/@deck.gl/core/dist/", import.meta.url));
  // The npm tarball exposes the scripting adapter as TS only. Bind its internal
  // core imports to the same compiled modules used by every deck.gl dependency.
  const plugins = [{name: "pydeck-single-core-identity", setup(builder) {
    builder.onResolve({filter: /^\.\.\//}, async args => {
      if (!args.importer.startsWith(scripting)) return;
      const source = fileURLToPath(new URL(args.path, "file://" + args.importer));
      const target = source.replace(coreSource, coreCompiled).replace(/\.ts$/, "") + ".js";
      await access(target);
      return {path: target};
    });
  }}];
  const shared = {alias, plugins, bundle: true, minify: true, target: "es2020", legalComments: "eof", metafile: true,
    define: {"process.env.NODE_ENV": '"production"'},
    loader: {".woff": "dataurl", ".woff2": "dataurl", ".ttf": "dataurl", ".svg": "dataurl", ".png": "dataurl"}};
  for (const [source, format, globalName] of [
    ["agilab_pydeck.js", "iife", "agilabPydeck"],
    ["agilab_pydeck_bootstrap.js", "esm", undefined],
    ["agilab_pydeck_maplibre_worker.js", "esm", undefined],
    ["agilab_pydeck.css", undefined, undefined],
  ]) {
    builds.push(await build({...shared, entryPoints: [fileURLToPath(new URL(source, import.meta.url))],
      outfile: fileURLToPath(new URL(source, directory)),
      // The upstream worker module is an executable entrypoint despite its package sideEffects list.
      ...(source === "agilab_pydeck_maplibre_worker.js" ? {ignoreAnnotations: true} : {}),
      ...(format ? {format} : {}), ...(globalName ? {globalName} : {})}));
  }
  for (const item of configured) {
    if (!/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(item.libraryName) ||
        typeof item.entryPoint !== "string" || !item.entryPoint.startsWith("node_modules/") ||
        item.entryPoint.split("/").includes("..") || customLibraries[item.libraryName]) {
      throw new Error("Custom pydeck libraries need a unique JavaScript name and a pinned node_modules entryPoint.");
    }
    const output = "agilab_pydeck_custom_" + item.libraryName + ".js";
    builds.push(await build({...shared, entryPoints: [fileURLToPath(new URL(item.entryPoint, import.meta.url))],
      outfile: fileURLToPath(new URL(output, directory)), format: "iife", globalName: item.libraryName}));
    customLibraries[item.libraryName] = output;
  }
  const packages = new Set();
  for (const result of builds) for (const input of Object.keys(result.metafile.inputs)) {
    if (input.includes("node_modules/@deck.gl/core/src/") && !input.includes("/src/scripting/")) {
      throw new Error("Mixed deck.gl core identities: " + input);
    }
    if (!input.includes("node_modules/")) continue;
    const offset = input.lastIndexOf("node_modules/") + "node_modules/".length;
    const parts = input.slice(offset).split("/");
    packages.add(input.slice(0, offset) + parts.slice(0, parts[0].startsWith("@") ? 2 : 1).join("/"));
  }
  const licenses = ["AGILAB pydeck renderer: upstream npm inputs pinned by package-lock.json.\n"];
  const versions = {};
  for (const packagePath of [...packages].sort()) {
    const input = new URL(packagePath + "/", import.meta.url);
    const data = JSON.parse(await readFile(new URL("package.json", input), "utf8"));
    const locked = lock.packages[packagePath];
    if (!locked || locked.version !== data.version || !locked.integrity) throw new Error("Unpinned pydeck input: " + packagePath);
    versions[data.name] = data.version;
    const names = (await readdir(input)).filter(name => /^(licen[cs]e|copying)(\.[\w.-]+)?$/i.test(name)).sort();
    if (!names.length) {
      if (data.name !== "@nodable/entities" || data.version !== "3.1.0") throw new Error("Missing license for " + data.name);
      licenses.push(await readFile(new URL("agilab_pydeck_nodable_entities.LICENSE.txt", import.meta.url), "utf8"));
    }
    licenses.push("\n=== " + data.name + "@" + data.version + " (" + data.license + ") ===\n");
    for (const name of names) licenses.push(await readFile(new URL(name, input), "utf8"));
  }
  await writeFile(new URL("agilab_pydeck.LICENSE.txt", directory), licenses.join("\n"));
  const assets = {};
  for (const name of ["agilab_pydeck.js", "agilab_pydeck_bootstrap.js", "agilab_pydeck_maplibre_worker.js", "agilab_pydeck.css", "agilab_pydeck.LICENSE.txt", ...Object.values(customLibraries)].sort()) {
    const content = await readFile(new URL(name, directory));
    assets[name] = {sha256: createHash("sha256").update(content).digest("hex"), bytes: content.length,
      mime: name.endsWith(".js") ? "text/javascript" : name.endsWith(".css") ? "text/css" : "text/plain"};
  }
  const inputs = {};
  for (const name of ["package.json", "package-lock.json", "build_agilab_react_analysis.mjs", "agilab_pydeck_build.mjs", "agilab_pydeck_maplibre.js", "agilab_pydeck_maplibre_worker.js", "agilab_pydeck_nodable_entities.LICENSE.txt", "agilab_pydeck.js", "agilab_pydeck_bootstrap.js", "agilab_pydeck.css"]) {
    inputs[name] = createHash("sha256").update(await readFile(new URL(name, import.meta.url))).digest("hex");
  }
  await writeFile(new URL("agilab_pydeck_manifest.json", directory),
    JSON.stringify({schema: "agilab.pydeck_assets.v1", inputs, versions, custom_libraries: customLibraries, assets}, null, 2) + "\n");
}
