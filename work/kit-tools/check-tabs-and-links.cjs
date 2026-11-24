const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const profile = process.argv[2];
function load(file, exports, sandbox) {
  const source = fs.readFileSync(path.join(profile, 'mods', file), 'utf8')
    .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
  return vm.runInNewContext(source + '\n({' + exports.join(',') + '})', sandbox);
}

let activeLayout = 'herdr-mod-kit';
const calls = [];
const storage = new Map();
const before = { pane: 'p1', tab: 't1', terminal: 'lab/terminal-1' };
let documentPane = { pane: 'p2', tab: 't1', mod: 'herdr-kit-pdf' };
let panes = [before, documentPane];
const fakeSpace = { id: 's1', active: true, tabs: [{ id:'t1', name:'Work', active: true }] };
const sandbox = {
  exec: async (_program, _args, options) => {
    assert.equal(options.on, 'lab');
    return { code: 0, stdout: '"/tmp/check.pdf"' };
  },
  layout: () => ({ children: [{ id:'files', content:{ props:{ transfer:true } } }] }),
  shared: key => key === 'layout' ? activeLayout : storage.get(key),
  setShared: (key, value) => storage.set(key, value),
  spaces: () => [fakeSpace],
  panes: () => panes,
  jobId: () => 'fixture-id',
  notify: () => {},
  run: (name, args) => {
    calls.push({ name, args });
    if (name === 'tab.new' && args.props?.position) {
      fakeSpace.tabs.push({ id:'t2', name:args.name, active:true });
      panes.push({ pane:'p3', tab:'t2', mod:'herdr-kit-pdf' });
    }
    if (name === 'pane.close') panes = panes.filter(p => p.pane !== args.pane);
    if (name === 'terminal.park') panes = panes.filter(p => p.terminal !== args.terminal);
    if (name === 'terminal.keep') panes.push({ pane:'p4', tab:'t3', terminal:args.terminal });
  },
};

(async () => {
  const { handleLink } = load('herdr-kit-links/link.js', ['handleLink'], sandbox);
  const click = { link:{ kind:'file', raw:'file:///tmp/check.pdf', path:null }, source:{ machine:'lab', space:'s1', tab:'t1' } };
  assert.equal(await handleLink(click),'handled');
  assert.equal(calls.at(-1).args.mod,'herdr-kit-pdf');
  assert.equal(calls.at(-1).args.props.mode,'pdf');
  assert.equal(calls.at(-1).args.props.transfer,true);
  const previous=calls.length;
  const local={space:'s1',tab:'t1',machine:null};
  assert.equal(await handleLink({source:local,link:{kind:'file',raw:'file://files.example/document.pdf'}}),'handled');
  assert.equal(calls.length,previous);
  assert.equal(await handleLink({source:local,link:{kind:'file',raw:'file:///C:/docs/a.pdf',path:'C:/docs/a.pdf'}}),'handled');
  assert.equal(calls.at(-1).args.props.source,'C:/docs/a.pdf');
  activeLayout = 'other-layout';
  assert.equal(await handleLink(click),'pass');

  const { liftPane, registerDocument } = load('herdr-kit-files/document-drag.js', ['liftPane','registerDocument'], sandbox);
  const cx = { sleep: async () => {} };
  const view = { source:'/tmp/check.pdf', mode:'pdf', name:'check.pdf', split:true, id:'doc-1', transfer:true, position:{ anchor:[1,0], zoom:1 } };
  registerDocument(view,'t1','p2',null);
  assert.equal(await liftPane('p2',cx),true);
  assert.equal(calls.at(-1).name,'pane.close');
  assert.equal(calls.at(-2).args.props.position.anchor[0],1);
  assert.equal(calls.at(-2).args.props.transfer,true);
  documentPane = { pane:'p5', tab:'t1', mod:'herdr-kit-pdf' };
  panes.push(documentPane);
  assert.equal(await liftPane('p1',cx),true);
  assert.equal(calls.at(-1).args.terminal,before.terminal);
  assert.ok(panes.some(p => p.tab === 't3' && p.terminal === before.terminal));
  console.log('Packaged PDF link routing, layout scope, PDF page retention, and terminal ID preservation passed.');
})().catch(error => { console.error(error); process.exitCode=1; });
