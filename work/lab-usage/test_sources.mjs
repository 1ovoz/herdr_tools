import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const staged = process.argv[2];
const mod = staged ? "herdr-kit-usage" : "lab-weekly-usage";
const code = fs.readFileSync(staged || new URL("./main.js", import.meta.url), "utf8")
  .replace(/^import .*;\r?\n/gm, "").replace("export default class LabUsage", "globalThis.Usage = class LabUsage");
const config = {machine: staged ? null : "lab", python: "C:/installed/python.exe"};
const store = new Map(), calls = [], overlays = [], logs = [], messages = [];
let machines = [{name:null, layout:"ready"}, {name:"lab", layout:"ready"}, {name:"office", layout:"ready"}];
let now = 1800000000000;
class Clock extends Date { static now() { return now; } }

function element() {
  const el = {childrenList:[]};
  const proxy = new Proxy(el, {get(target,key) {
    if (key in target) return target[key];
    if (key === "child") return child => { el.childrenList.push(child); return proxy; };
    if (key === "children") return children => { el.childrenList.push(...children); return proxy; };
    if (key === "when") return (condition, build) => { if (condition) build(proxy); return proxy; };
    if (key === "id") return id => { el.control = id; return proxy; };
    if (key === "on_click") return click => { el.click = click; return proxy; };
    return () => proxy;
  }});
  return proxy;
}

function start(props = {}) {
  const tree = {timers:[], controls:new Map()};
  const cx = {
    timer:{every:(ms, fn) => tree.timers.push([ms,fn])},
    spawn: fn => fn(cx),
    notify() {}
  };
  const context = {
    View:class {}, Date:Clock, console:{error: message => messages.push(message)}, div:element, svg:element, h_flex:element, v_flex:element,
    appHome:() => "/app", checking:() => false, props:() => props, theme:() => ({}), machines:() => machines,
    shared:key => structuredClone(store.get(key)), setShared:(key,value) => store.set(key, structuredClone(value)),
    openOverlay: spec => overlays.push(structuredClone(spec)), closeOverlay() {},
    readTextFile: async path => path.endsWith("/runtime.json") ? JSON.stringify(config) : "collector fixture",
    exec: async (command,args,{on}) => {
      if (!args.includes("-c")) { logs.push(args.slice(-2)); return {code:0}; }
      return new Promise(resolve => calls.push({host:on, command, providers:Array.from(args.slice(args.indexOf("-c")+2)),
        reply: value => resolve({code:0,stdout:JSON.stringify(value)}), fail: () => resolve({code:1,stdout:""})}));
    }
  };
  vm.runInNewContext(code,context);
  const view = new context.Usage();
  view.init(props, cx);
  tree.render = () => {
    tree.controls.clear();
    const strings = [];
    function walk(node) {
      if (typeof node === "string") { strings.push(node); return; }
      if (!node?.childrenList) return;
      if (typeof node.control === "string") tree.controls.set(node.control,node);
      node.childrenList.forEach(walk);
    }
    walk(view.render(cx));
    return strings.join(" | ");
  };
  tree.click = id => {
    tree.render();
    assert.ok(tree.controls.has(id), "Missing control " + id);
    tree.controls.get(id).click({},cx);
  };
  tree.poll = () => tree.timers.find(([ms]) => ms === 120000)[1](cx);
  return tree;
}

const tick = () => new Promise(resolve => setImmediate(resolve));
async function update(panel) { await tick(); panel.render(); await tick(); }

const panel = start();
await update(panel);
assert.equal(calls.length, 1, "Same-machine providers share one collector");
assert.equal(calls[0].host, config.machine);
assert.deepEqual(calls[0].providers, ["codex", "claude"]);
if (staged) assert.equal(calls[0].command, config.python);
calls[0].reply({at:now/1000,codex:{used:12},claude:{used:35,fable:{used:5}}});
await update(panel);
panel.click("weekly-claude");
assert.deepEqual(overlays.at(-1).props,{details:true});
const details = start(overlays.at(-1).props);
await tick();
details.click("details-sources");
assert.equal(overlays.at(-1).mod, mod);
assert.equal(overlays.at(-1).kind, "popup");
const sources = start(overlays.at(-1).props);
await tick();
assert.match(sources.render(),/Install default/);
sources.click("source-codex-1"); // explicit local
sources.click("source-claude-2"); // registered lab
await update(panel);
const split = calls.at(-1);
assert.equal(calls.length, 2, "Changing one effective host only fetches the affected provider");
assert.equal(split.host, staged ? "lab" : null);
assert.deepEqual(split.providers, staged ? ["claude"] : ["codex"]);
assert.doesNotMatch(details.render(),staged ? /35% used/ : /12% used/, "Old host's reading must disappear immediately");
split.reply({[split.providers[0]]:{used:41}});
await update(panel);
assert.match(details.render(), /41% used/);

// New mod instances read the saved choices, including a previously selected offline machine.
machines = [{name:null,layout:"ready"}];
const reopened = start({sources:true});
await tick();
assert.match(reopened.render(),/lab/);
assert.match(reopened.render(), /unavailable/i);
assert.doesNotMatch(reopened.render(),/office/);
machines = [{name:null,layout:"ready"},{name:"lab",layout:"ready"},{name:"office",layout:"ready"}];

// Two hosts can complete independently. A late response cannot replace the selected host's reading.
now += 600000;
panel.poll();
await update(panel);
const [local,lab] = calls.slice(-2);
assert.equal(local.host,null); assert.equal(lab.host,"lab");
assert.deepEqual(local.providers,["codex"]); assert.deepEqual(lab.providers,["claude"]);
if (staged) { assert.equal(local.command,config.python); assert.equal(lab.command,"python3"); }
local.reply({codex:{used:18}});
await update(panel);
assert.match(details.render(), /18% used/);
sources.click("source-claude-3");
await update(panel);
assert.equal(calls.at(-1).host,"office");
calls.at(-1).reply({claude:{used:67,fable:{used:9}}});
await update(panel);
lab.reply({claude:{used:99}});
await update(panel);
assert.match(details.render(), /67% used/);
assert.doesNotMatch(details.render(), /99% used/);

now += 600000;
panel.poll(); await update(panel);
calls.at(-2).fail();
calls.at(-1).reply({claude:{error:"Rate limited",status:429,retry_after:1400}});
await update(panel);
assert.match(details.render(), /Check usage host/);
assert.match(details.render(), /Rate limited/);
assert.match(details.render(), /67% used/);
assert.match(details.render(), /Fable 9%/);
if (staged) assert.ok(logs.some(entry => entry[0] === "codex" && entry[1] === "collector_unreachable"));
now += 900000;
const beforeRetry = calls.length;
panel.poll(); await update(panel);
assert.equal(calls.length,beforeRetry+1);
assert.deepEqual(calls.at(-1).providers,["codex"]);
calls.at(-1).reply({codex:{used:24}});
await update(panel);
sources.click("source-claude-0");
await update(panel);
assert.equal(calls.at(-1).host, config.machine, "Reset uses the installer or standalone default");
assert.deepEqual(calls.at(-1).providers, ["claude"]);
calls.at(-1).reply({claude:{used:29}});
await update(panel);
assert.match(details.render(), /29% used/);
assert.doesNotMatch(details.render(), /67% used/);
if (staged) {
  // Changing only runtime.json must still take effect in the running Windows installation.
  config.machine = "updated-default";
  now += 600000;
  panel.poll();
  await update(panel);
  const [codex, claude] = calls.slice(-2);
  assert.equal(claude.host, "updated-default");
  assert.deepEqual(claude.providers, ["claude"]);
  assert.equal(codex.host, null, "Explicit local remains local when the install default changes");
  codex.reply({codex:{used:2}});
  claude.reply({claude:{used:3}});
  await update(panel);
}
// Same-host batches also isolate malformed provider results. A manual refresh respects Codex Retry-After.
sources.click("source-claude-1");
await update(panel);
if (calls.at(-1).providers.join() === "claude") calls.at(-1).reply({claude:{used:15}});
await update(panel);
now += 600000;
panel.poll();
await update(panel);
const batch = calls.at(-1);
assert.equal(batch.host, null);
assert.deepEqual(batch.providers, ["codex", "claude"]);
batch.reply({codex:{error:"Rate limited",status:429,retry_after:1400},claude:{unexpected:true}});
await update(panel);
assert.match(details.render(), /Rate limited/);
assert.match(details.render(), /Check usage host/);
if (!staged) assert.ok(messages.some(message => message.includes("claude collector_unreachable")));
now += 800000;
const beforeManual = calls.length;
details.click("details-refresh");
await update(panel);
await update(panel);
assert.equal(calls.length, beforeManual + 1);
assert.deepEqual(calls.at(-1).providers, ["claude"]);
calls.at(-1).reply({claude:{used:7}});
await update(panel);
assert.match(details.render(), /7% used/);
console.log("Usage Sources passed for " + mod);
