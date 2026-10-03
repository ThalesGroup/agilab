import { build } from "esbuild";
import { mkdir, copyFile, readFile, readdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
// Keep the packaged standard-library policy byte-identical to its canonical source.
await copyFile(new URL("../../../security/ui_public_bind_guard.py", import.meta.url),
               new URL("../src/agi_web/public_bind_guard.py", import.meta.url));
const assets = new URL("../src/agi_web/react_analysis_assets/", import.meta.url);
await mkdir(assets, { recursive: true });
for (const host of ["streamlit", "notebook"]) {
  await build({
    entryPoints: [fileURLToPath(new URL(`agilab_react_analysis_${host}.jsx`, import.meta.url))],
    outfile: fileURLToPath(new URL(`agilab_react_analysis_${host}.js`, assets)),
    bundle: true, minify: true, format: "esm", target: "es2020",
    jsx: "automatic", define: { "process.env.NODE_ENV": '"production"' },
    legalComments: "eof",
  });
}
await copyFile(new URL("agilab_react_analysis.css", import.meta.url),
               new URL("agilab_react_analysis.css", assets));
await copyFile(new URL("node_modules/react/LICENSE", import.meta.url),
               new URL("agilab_react_analysis.LICENSE.txt", assets));

const mainAssets = new URL("../src/agi_web/react_main_interface_assets/", import.meta.url);
await mkdir(mainAssets, { recursive: true });
await build({
  entryPoints: [fileURLToPath(new URL("agilab_react_main_interface.jsx", import.meta.url))],
  outfile: fileURLToPath(new URL("agilab_react_main_interface.js", mainAssets)),
  bundle: true, minify: true, format: "esm", target: "es2020",
  jsx: "automatic", define: { "process.env.NODE_ENV": '"production"' },
  legalComments: "eof",
});
await copyFile(new URL("agilab_react_main_interface.css", import.meta.url),
               new URL("agilab_react_main_interface.css", mainAssets));
await copyFile(new URL("node_modules/react/LICENSE", import.meta.url),
               new URL("agilab_react_main_interface.LICENSE.txt", mainAssets));

const pythonAssets = new URL("../src/agi_web/react_python_host_assets/", import.meta.url);
await mkdir(pythonAssets, { recursive: true });
await build({
  entryPoints: [fileURLToPath(new URL("agilab_react_graphviz.js", import.meta.url))],
  outfile: fileURLToPath(new URL("agilab_react_graphviz.js", pythonAssets)),
  bundle: true, minify: true, format: "esm", target: "es2020", legalComments: "eof",
});
const vegaBuild = await build({
  entryPoints: [fileURLToPath(new URL("agilab_react_vega.js", import.meta.url))],
  outfile: fileURLToPath(new URL("agilab_react_vega.js", pythonAssets)),
  bundle: true, minify: true, format: "esm", target: "es2020", legalComments: "eof", metafile: true,
});
const vegaPackages = new Set(Object.keys(vegaBuild.metafile.inputs).filter(path => path.includes("node_modules/")).map(path => {
  const offset = path.lastIndexOf("node_modules/") + "node_modules/".length;
  const parts = path.slice(offset).split("/");
  return path.slice(0, offset) + parts.slice(0, parts[0].startsWith("@") ? 2 : 1).join("/");
}));
const vegaLicenses = ["AGILAB bundled Vega runtime: upstream npm packages, pinned by package-lock.json.\n"];
for (const packagePath of [...vegaPackages].sort()) {
  const directory = new URL(packagePath + "/", import.meta.url);
  const metadata = JSON.parse(await readFile(new URL("package.json", directory), "utf8"));
  const licenseFiles = (await readdir(directory)).filter(name => /^(licen[cs]e|copying)(\.[\w.-]+)?$/i.test(name)).sort();
  if (!licenseFiles.length) throw new Error(`Bundled package ${metadata.name} has no license file.`);
  vegaLicenses.push(`\n=== ${metadata.name}@${metadata.version} (${metadata.license}) ===\nSource: ${metadata.repository?.url || metadata.repository || metadata.homepage || "https://registry.npmjs.org/" + metadata.name}\n`);
  for (const name of licenseFiles) vegaLicenses.push(await readFile(new URL(name, directory), "utf8"));
}
await writeFile(new URL("agilab_react_vega.LICENSE.txt", pythonAssets), vegaLicenses.join("\n"));
await build({
  entryPoints: [fileURLToPath(new URL("agilab_react_python_host.jsx", import.meta.url))],
  outfile: fileURLToPath(new URL("agilab_react_python_host.js", pythonAssets)),
  bundle: true, minify: true, format: "esm", target: "es2020", jsx: "automatic",
  define: { "process.env.NODE_ENV": '"production"' }, legalComments: "eof",
  loader: {".woff": "dataurl", ".woff2": "dataurl", ".ttf": "dataurl"},
});
await copyFile(new URL("node_modules/react/LICENSE", import.meta.url),
               new URL("agilab_react_python_host.LICENSE.txt", pythonAssets));
await copyFile(new URL("agilab_react_graphviz_third_party.LICENSE.txt", import.meta.url),
               new URL("agilab_react_graphviz.LICENSE.txt", pythonAssets));
for (const library of ["marked", "dompurify", "katex"]) {
  await copyFile(new URL(`node_modules/${library}/LICENSE`, import.meta.url),
                 new URL(`agilab_react_python_host_${library}.LICENSE.txt`, pythonAssets));
}
