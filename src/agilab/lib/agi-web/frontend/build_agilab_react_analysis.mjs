import { build } from "esbuild";
import { mkdir, copyFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
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
