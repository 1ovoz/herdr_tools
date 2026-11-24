import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const ids = new Map(), overlays = [], closed = [], jobs = [], shared = new Map(), bindings = [];
const splits = [], tasks = [], copied = [];
let propsValue = {}, bridgeResult = {ok:true,path:'/download'}, stopped = 0, tid = 0;
function element() {
  const handlers = {};
  const proxy = new Proxy({handlers}, {get(target, key) {
    if (key === 'handlers') return handlers;
    if (key === 'when') return (condition, build) => { if (condition) build(proxy); return proxy; };
    if (key === 'id') return id => { ids.set(id,proxy); return proxy; };
    if (key === 'key_context') return name => { handlers.context = name; return proxy; };
    if (key.startsWith('on_')) return (...args) => {
      const keyed = ['on_action','on_mouse_down','on_mouse_up'].includes(key);
      handlers[key + (keyed ? ':' + args[0] : '')] = args.at(-1);
      return proxy;
    };
    return () => proxy;
  }});
  return proxy;
}

const cx = {
  stop_propagation: () => stopped++, notify() {}, spawn: fn => tasks.push(fn),
  timer: {every() {}, after() {}}, bind_keys: rows => bindings.push(...rows),
  write_to_clipboard: value => copied.push(value),
  focus_handle: () => ({focus() {}, is_focused: () => true})
};
const context = {
  console, Map, Set, Math, JSON, Date, Error, View:class {}, DocumentView:class {},
  fileDocument: (source,on) => ({source,on}), openDocument() {},
  startDocumentDrag: (doc,side) => splits.push({doc,side}),
  div:element, svg:element, h_flex:element, v_flex:element,
  props: () => propsValue, checking: () => true, theme: () => ({}), settings: () => ({}),
  shared: key => shared.get(key), setShared: (key,value) => shared.set(key,value),
  bridge: async q => { jobs.push(q); return bridgeResult; }, jobId: () => 'id-' + ++tid,
  openOverlay: q => overlays.push(q), closeOverlay: id => closed.push(id),
  uploadRequests: (paths,directory,on) => paths.map(source => ({action:'upload',source,directory,on})),
  InputState: {new: ({value}) => ({value:() => value, set_value(next) { value = next; }, on() {}, focus() {}, set_selected_range() {}})},
  Input: {new:element}, EditorState:{}, Editor:{}, notify() {},
  spaces:() => [], panes:() => [], focused:() => null, window:() => ({platform:'windows'})
};
const staged = process.argv[2];
const source = fs.readFileSync(staged || new URL('./main.js',import.meta.url),'utf8')
  .replace(/^import .*;\r?\n/gm,'').replace('export default class Files','globalThis.Files = class Files');
vm.runInNewContext(source,context);
function view(p = {}) {
  propsValue = p;
  const instance = new context.Files();
  instance.init(p,cx);
  return instance;
}
function render(instance, p) {
  propsValue = p; ids.clear();
  return instance.render(cx);
}
function click(id) {
  assert.ok(ids.has(id), 'Missing control ' + id);
  ids.get(id).handlers.on_click({},cx);
}
function runKey(el, keys) {
  const row = bindings.find(b => b.keystroke === keys && b.context === el.handlers.context);
  assert.ok(row, 'Missing scoped binding ' + keys);
  const handler = el.handlers['on_action:' + row.action];
  assert.ok(handler, 'No handler for ' + keys);
  handler({},cx);
}
async function finish() {
  while (tasks.length) await tasks.shift()(cx);
}
const both = {transfer:true, pdf:true};
function panel(root = '/project', on = 'lab', features = both) {
  const props = {folder:root,on,...features}, file = view(props);
  Object.assign(file,{root,on,entries:new Map([
    ['',[{name:'folder',dir:true},{name:'a.pdf',dir:false}]], ['folder',[{name:'한글.txt',dir:false}]]
  ]),folders:new Set(['folder']),marks:{}});
  return {file,props};
}
function menuAt(host,id) {
  render(host.file,host.props);
  const right = ids.get(id)?.handlers['on_mouse_down:right'];
  assert.ok(right, 'Missing context menu on ' + id);
  right({},cx);
  const p = {...overlays.at(-1).props,overlay:'menu'};
  const menu = view(p), el = render(menu,p);
  return {p,menu,el};
}
function openDialog() {
  const p = {...overlays.at(-1).props,overlay:'dialog'};
  const instance = view(p);
  render(instance,p);
  return {instance,p};
}
function fileJob() {
  const p = {...overlays.at(-1).props,overlay:'job'};
  const worker = view(p);
  worker.work(cx); worker.work(cx);
  assert.equal(tasks.length,1,'A double click must start one request');
  return {p,worker};
}
const host = panel();
render(host.file,host.props);
ids.get('file-folder').handlers.on_drop({paths:['C:/local/a.txt']},cx);
assert.equal(overlays.at(-1).props.requests[0].directory,'/project/folder');
assert.equal(overlays.at(-1).props.requests[0].on,'lab');
assert.equal(stopped,1);
const oldRow = ids.get('file-a.pdf');
host.file.root = '/changed'; host.file.on = 'other';
oldRow.handlers['on_mouse_down:right']({},cx);
const snapshot = {...overlays.at(-1).props,overlay:'menu'};
const itemMenu = view(snapshot);
render(itemMenu,snapshot);
click('download');
const download = overlays.at(-1).props.requests[0];
assert.equal(download.source,'/project/a.pdf');
assert.equal(download.on,'lab');
assert.equal(download.choose,true,'Download… must ask where to save');
bridgeResult = {ok:true,cancelled:true};
const cancelled = fileJob();
await finish();
assert.equal(cancelled.worker.busy,false);
assert.equal([...shared.keys()].some(k => k.endsWith('.changed')),false);
cancelled.worker.work(cx);
assert.equal(tasks.length,0);
bridgeResult = {ok:true,path:'/download'};

const files = panel();
let popup = menuAt(files,'file-folder/한글.txt');
runKey(popup.el,'ctrl-enter');
assert.equal(splits.at(-1).side,'right');
assert.equal(splits.at(-1).doc.source,'/project/folder/한글.txt');
popup = menuAt(files,'file-folder/한글.txt');
runKey(popup.el,'alt-shift-c');
assert.equal(copied.at(-1),'/project/folder/한글.txt');
popup = menuAt(files,'file-folder/한글.txt');
runKey(popup.el,'ctrl-k ctrl-shift-c');
assert.equal(copied.at(-1),'folder/한글.txt');
popup = menuAt(panel('C:\\repo\\',null),'file-folder/한글.txt');
click('copy-path'); assert.equal(copied.at(-1),'C:\\repo\\folder\\한글.txt');
popup = menuAt(panel('C:/my/repo',null),'file-folder/한글.txt');
click('copy-path'); assert.equal(copied.at(-1),'C:\\my\\repo\\folder\\한글.txt');
popup = menuAt(panel('//share/work',null),'file-a.pdf');
click('copy-path'); assert.equal(copied.at(-1),'\\\\share\\work\\a.pdf');
popup = menuAt(panel('/'),'file-a.pdf');
click('copy-path'); assert.equal(copied.at(-1),'/a.pdf');

// Copy and cut transfer the selected file and never replace a collision.
popup = menuAt(files,'file-a.pdf'); runKey(popup.el,'ctrl-c');
popup = menuAt(files,'file-folder'); runKey(popup.el,'ctrl-v');
let work = fileJob(); await finish();
assert.equal(jobs.at(-1).action,'copy');
assert.equal(jobs.at(-1).directory,'/project/folder');
assert.equal(jobs.at(-1).source,'/project/a.pdf');
popup = menuAt(files,'file-folder/한글.txt'); runKey(popup.el,'ctrl-x');
const other = panel('/project','other');
popup = menuAt(other,'upload-root');
const before = overlays.length; click('paste'); assert.equal(overlays.length,before);
popup = menuAt(files,'files-tree'); click('paste');
bridgeResult = {ok:false,code:'exists',error:'File exists'};
work = fileJob(); await finish(); render(work.worker,work.p);
assert.equal(jobs.at(-1).action,'move'); assert.equal(jobs.at(-1).directory,'/project');
assert.ok(!ids.has('replace-file'));
bridgeResult = {ok:true,path:'/project/한글.txt'};
popup = menuAt(files,'upload-root'); click('paste');
work = fileJob(); await finish();
popup = menuAt(files,'upload-root');
const afterMove = overlays.length; click('paste'); assert.equal(overlays.length,afterMove);

popup = menuAt(files,'file-a.pdf'); runKey(popup.el,'f2');
let dialog = openDialog(); const beforeRename = jobs.length;
assert.equal(jobs.length,beforeRename);
dialog.instance.nameInput.set_value('b.pdf');
click('confirm-rename'); click('confirm-rename'); await finish();
assert.equal(jobs.length,beforeRename+1);
assert.equal(jobs.at(-1).action,'rename'); assert.equal(jobs.at(-1).name,'b.pdf');
popup = menuAt(files,'file-a.pdf'); runKey(popup.el,'delete');
const beforeDelete = jobs.length;
dialog = openDialog(); click('cancel-change'); await finish();
assert.equal(jobs.length,beforeDelete);
popup = menuAt(files,'file-a.pdf'); click('delete');
dialog = openDialog(); click('confirm-delete'); click('confirm-delete'); await finish();
assert.equal(jobs.length,beforeDelete+1);
assert.equal(jobs.at(-1).source,'/project/a.pdf');
assert.equal(jobs.at(-1).confirmed,true);
popup = menuAt(files,'file-folder');
assert.ok(!ids.has('delete') && !ids.has('rename') && !ids.has('cut'));

if (staged) {
  popup = menuAt(panel('/project','lab',{pdf:true}),'file-a.pdf');
  assert.ok(ids.has('open-side') && !ids.has('cut') && !ids.has('download'));
  const transfer = panel('/project','lab',{transfer:true});
  popup = menuAt(transfer,'file-a.pdf');
  assert.ok(ids.has('cut') && !ids.has('open-side'));
  const disabled = panel('/project','lab',{});
  render(disabled.file,disabled.props);
  assert.ok(!ids.get('file-a.pdf').handlers['on_mouse_down:right']);
  assert.ok(!ids.has('upload-root'));
}
console.log('Files UI checks passed', staged ? '(staged)' : '(source)');
