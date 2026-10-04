import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import path from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import { renderToStaticMarkup } from "react-dom/server";
import { build } from "esbuild";

const directory = path.dirname(fileURLToPath(import.meta.url));
let scratch;
let PythonLinkAction;
before(async () => {
  scratch = await mkdtemp(path.join(directory, ".agilab-link-action-test-"));
  const output = path.join(scratch, "agilab_python_link_action_render.mjs");
  await build({
    entryPoints: [path.join(directory, "agilab_python_link_action.jsx")],
    outfile: output, bundle: true, format: "esm", platform: "node", packages: "external",
  });
  ({ PythonLinkAction } = await import(pathToFileURL(output).href));
});
after(async () => { if (scratch) await rm(scratch, { recursive: true, force: true }); });

function action(kind, props = {}, navigate = () => assert.fail("A normal link must not use SPA navigation")) {
  return PythonLinkAction({
    node: { kind, props: { label: "Prepare demo", url: "/ORCHESTRATE?first_proof_action=install", ...props } },
    view: { navigate },
  });
}

test("link buttons open a separate tab with opener protection by default", () => {
  const element = action("link_button");
  assert.equal(element.props.target, "_blank");
  assert.equal(element.props.rel, "noopener");
  assert.equal(element.props.onClick, undefined);
  const html = renderToStaticMarkup(element);
  assert.match(html, /href="\/ORCHESTRATE\?first_proof_action=install"/);
  assert.match(html, /target="_blank"/);
  assert.match(html, /rel="noopener"/);
});

for (const target of ["_self", "_parent", "report-window", ""]) {
  test(`link buttons preserve the explicit target ${JSON.stringify(target)}`, () => {
    assert.equal(action("link_button", { target }).props.target, target);
  });
}

test("disabled link buttons cannot open or navigate even when clicked programmatically", () => {
  const element = action("link_button", { disabled: true, target: "_self" });
  let prevented = false;
  element.props.onClick({ preventDefault: () => { prevented = true; } });
  assert.ok(prevented);
  assert.equal(element.props.href, undefined);
  assert.equal(element.props.target, undefined);
  assert.equal(element.props["aria-disabled"], true);
  assert.equal(element.props.tabIndex, -1);
  const html = renderToStaticMarkup(element);
  assert.doesNotMatch(html, /href=|target=/);
  assert.match(html, /aria-disabled="true"/);
});

test("internal page links retain current-tab native navigation", () => {
  const navigations = [];
  const element = action("page_link", { url: "/WORKFLOW?active_app=custom_project" }, url => navigations.push(url));
  let prevented = false;
  element.props.onClick({ preventDefault: () => { prevented = true; } });
  assert.ok(prevented);
  assert.deepEqual(navigations, ["/WORKFLOW?active_app=custom_project"]);
  assert.equal(element.props.target, undefined);
  assert.equal(element.props.rel, undefined);
});

test("downloads retain their filename and do not start a new tab", () => {
  const element = action("download_button", { filename: "flight_telemetry_pipeline.ipynb", url: "/assets/notebook" });
  assert.equal(element.props.download, "flight_telemetry_pipeline.ipynb");
  assert.equal(element.props.href, "/assets/notebook");
  assert.equal(element.props.target, undefined);
  assert.equal(element.props.onClick, undefined);
});

test("external page links keep browser navigation and unsafe schemes remain blocked", () => {
  const element = action("page_link", { url: "https://example.com/docs" });
  assert.equal(element.props.onClick, undefined);
  assert.equal(element.props.target, undefined);
  assert.equal(action("link_button", { url: "javascript:alert(1)" }).props.href, "#");
});
