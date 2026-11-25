import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(process.argv[2] || new URL("./main.js", import.meta.url), "utf8");
const staged = source.includes("herdr-kit-pdf");
const tabsMod = staged ? "herdr-kit-tabs" : "personal-tabs";
const documentMod = staged ? "herdr-kit-pdf" : "personal-files";
const ids = new Map(), calls = [], overlays = [], registered = [];
const element = () => {
  const handlers = {};
  const el = new Proxy(handlers, { get(target, key) {
    if (key in target) return target[key];
    if (key === "id") return id => { ids.set(id, el); return el; };
    if (key === "when") return (enabled, fn) => { if (enabled) fn(el); return el; };
    if (key.startsWith("on_")) return (...args) => { target[key + "Handler"] = args.at(-1); return el; };
    return () => el;
  } });
  return el;
};

const tab = { id: "lab/t1", active: true, name: "Editor" };
const panes = [
  { pane: "lab/p1", tab: tab.id, terminal: "lab/shell" },
  { pane: "lab/p2", tab: tab.id, mod: documentMod, focused: true }
];
const files = { id: "files", content: { mod: staged ? "herdr-kit-files" : "personal-files",
  props: { pdf: true, transfer: true } } };
const layout = { children: [{ id: "tabs", content: { mod: tabsMod } }, files] };
let props = {};
const cx = { focus_handle: () => ({focus() {}}), stop_propagation() {}, notify() {} };
const context = {
  View: class {}, div: element, svg: element, h_flex: element, v_flex: element,
  ScrollHandle: { new: () => ({ scroll_to_item() {} }) },
  localStorage: { getItem: () => null }, spaces: () => [{ id: "lab/s1", active: true, tabs: [tab] }],
  theme: () => ({}), window: () => ({}), layout: () => layout, panes: () => panes,
  props: () => props, shared: () => null,
  closeOverlay: id => { assert.equal(id, "popup"); }, openOverlay: spec => overlays.push(spec),
  jobId: () => "group-" + (registered.length + 1),
  attachGroup: (props, pane) => registered.push({props, pane}),
  run: (name, args) => {
    calls.push({ name, args: { ...args } });
    if (name === "pane.split" && args.mod) panes.push({pane: "lab/new", tab: tab.id, mod: args.mod});
  }
};
const Tabs = vm.runInNewContext(source.replace(/^import .*;\r?\n/gm, "").replace("export default class Tabs", "class Tabs") + "\nTabs", context);
const toolbar = new Tabs();
toolbar.init(props, cx);
function popup() {
  props = {}; ids.clear(); toolbar.render(cx);
  assert.ok(ids.has("pane-layout"), "Layout chooser in the main toolbar");
  ids.get("pane-layout").on_clickHandler({}, cx);
  assert.equal(overlays.at(-1).mod, tabsMod);
  props = { ...overlays.at(-1).props, overlay: "popup" };
  const menu = new Tabs(); menu.init(props, cx); ids.clear(); menu.render(cx);
}
function choose(id) {
  assert.ok(ids.has(id), "Missing " + id);
  ids.get(id).on_clickHandler({}, cx);
}

popup(); choose("layout-right");
assert.equal(calls.length, 1);
const right = calls.pop();
assert.deepEqual([right.name, right.args.pane, right.args.direction, right.args.mod],
  ["pane.split", "lab/p2", "right", documentMod]);
assert.equal(right.args.props.mode, "group");
assert.ok(right.args.props.groupId);
assert.equal(right.args.props.transfer, true);
assert.equal(registered.length, 1, "The new editor must be registered before focus can move again");
assert.equal(registered[0].pane, panes.pop());
assert.equal(registered[0].props.groupId, right.args.props.groupId);
assert.equal(right.args.props.anchorPane, undefined, "Editor-to-editor splits have independent file groups");

panes[1].focused = false;
files.content.props.transfer = false;
popup(); choose("layout-down");
const down = calls.pop();
assert.equal(down.args.pane, "lab/p2", "Retain the chosen pane when toolbar or Files takes focus");
assert.equal(down.args.direction, "down"); assert.equal(down.args.props.transfer, false);
assert.notEqual(down.args.props.groupId, right.args.props.groupId);
assert.equal(registered[1].pane, panes.pop());

panes[0].focused = true;
popup(); choose("layout-right");
assert.equal(calls.pop().args.props.anchorPane, undefined, "An explicitly split right-hand editor does not own later opens from the left terminal");
assert.equal(registered[2].pane, panes.pop());
panes[0].focused = false; panes[1].focused = true;

popup(); choose("layout-single");
assert.deepEqual(calls.pop(), { name: "pane.zoom", args: { pane: "lab/p2" } });
panes[1].zoomed = true;
popup(); choose("layout-restore");
assert.deepEqual(calls.pop(), { name: "pane.zoom", args: { pane: "lab/p2" } });

files.content.props.pdf = false;
popup(); choose("layout-right");
assert.deepEqual(calls.splice(0), [
  { name: "pane.zoom", args: { pane: "lab/p2" } },
  { name: "pane.split", args: { pane: "lab/p2", direction: "right" } }
], "Reveal the existing panes before splitting; use a native terminal when PDF is disabled");

panes[1].zoomed = false;
popup(); tab.active = false; choose("layout-right");
assert.equal(calls.length, 0, "A menu from another tab must not change the current layout");
tab.active = true;
popup(); panes.pop(); choose("layout-down");
assert.equal(calls.length, 0, "A closed pane cannot be replaced with a different target");
popup(); choose("layout-single");
assert.equal(calls.length, 0, "An already single-pane tab stays as it is");
console.log("Layout chooser preserves panes, targets the selected pane and honors installed features.");
