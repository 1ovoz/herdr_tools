import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const ids = new Map(), overlays = [], closed = [], jobs = [], shared = new Map(), bindings = [];
const splits = [], tasks = [], copied = [], opened = [];
const destinations = [], listed = [], listings = new Map();
let focusedPane = null;
let propsValue = {}, bridgeResult = {ok:true,path:'/download'}, stopped = 0, tid = 0, paints = 0, zoom = 1;
function element() {
  const handlers = {}, styles = {}, children = [];
  const proxy = new Proxy({handlers, styles, children}, {get(target, key) {
    if (key === 'handlers' || key === 'styles') return target[key];
    if (key === 'contents') return children;
    if (key === 'child') return value => { children.push(value); return proxy; };
    if (key === 'when') return (condition, build) => { if (condition) build(proxy); return proxy; };
    if (key === 'id') return id => { ids.set(id,proxy); return proxy; };
    if (key === 'key_context') return name => { handlers.context = name; return proxy; };
    if (key.startsWith('on_')) return (...args) => {
      const keyed = ['on_action','on_mouse_down','on_mouse_up'].includes(key);
      handlers[key + (keyed ? ':' + args[0] : '')] = args.at(-1);
      return proxy;
    };
    return (...args) => { styles[key] = args; return proxy; };
  }});
  return proxy;
}

const cx = {
  stop_propagation: () => stopped++, notify: () => paints++, spawn: fn => tasks.push(fn),
  timer: {every() {}, after() {}}, bind_keys: rows => bindings.push(...rows),
  write_to_clipboard: value => copied.push(value),
  focus_handle: () => ({focus() {}, is_focused: () => true})
};
const context = {
  console, Map, Set, Math, JSON, Date, Error, View:class {}, DocumentView:class {},
  ...vm.runInNewContext(fs.readFileSync(new URL('./document-drag.js',import.meta.url),'utf8')
    .replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,'') + '\n;({fileDocument,movement})'),
  openDocument: (doc,_cx,pane) => { opened.push(doc.source); destinations.push(pane); },
  startDocumentDrag: (doc,side) => splits.push({doc,side}),
  div:element, svg:element, h_flex:element, v_flex:element,
  props: () => propsValue, checking: () => true, theme: () => new Proxy({}, {get: (_, token) => token}), settings: () => ({zoom}),
  shared: key => shared.get(key), setShared: (key,value) => shared.set(key,value),
  bridge: async q => { jobs.push(q); return bridgeResult; }, jobId: () => 'id-' + ++tid,
  openOverlay: q => overlays.push(q), closeOverlay: id => closed.push(id),
  uploadRequests: (paths,directory,on) => paths.map(source => ({action:'upload',source,directory,on})),
  InputState: {new: ({value}) => ({value:() => value, set_value(next) { value = next; }, on() {}, focus() {}, set_selected_range() {}})},
  Button: {new: id => element().id(id)}, Input: {new:element}, EditorState:{}, Editor:{}, notify() {},
  spaces:() => [], panes:() => [], focused:() => focusedPane, window:() => ({platform:'windows'}),
  exec: async (program,args,options) => {
    if (program === 'git') return {code:1};
    assert.equal(program,'sh');
    const path = args.at(-1);
    listed.push([options.on,path]);
    const entries = listings.get(path);
    if (!entries) throw new Error('Missing folder ' + path);
    return {code:0,stdout:entries.map(e => (e.dir?'d':'f') + '\0' + e.name + '\0').join('')};
  }
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
function click(id, count = 1) {
  assert.ok(ids.has(id), 'Missing control ' + id);
  ids.get(id).handlers.on_click({click_count:count},cx);
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
  Object.assign(file,{root,on,context:{key:JSON.stringify({cwd:root,on,space:'pinned'}),cwd:root,on},entries:new Map([
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

// The dismissal and confirmation stay together in a fixed, right-aligned footer.
function checkFooter(dialog, ...buttonIds) {
  const footer = dialog.contents.at(-1);
  assert.ok('justify_end' in footer.styles && 'flex_none' in footer.styles,
    'Long dialog messages must leave space for the action row');
  assert.deepEqual(footer.contents.map(button => buttonIds.find(id => ids.get(id) === button)), buttonIds);
  const [first, second] = footer.contents;
  assert.ok(first.styles.h?.[0] >= 30, 'A modal action must have a visible click target');
  if (second) {
    assert.deepEqual(first.styles.h, second.styles.h, 'Dismissal and confirmation share a height');
    assert.notEqual(first.styles.border_color?.[0], second.styles.border_color?.[0],
      'The confirmation must be distinguishable from the dismissal before hovering');
  }
  return second || first;
}
const target = {source:'/project/a.pdf',name:'a.pdf',on:'lab',dir:false};
for (const mode of ['rename','delete']) {
  const p = {mode,target,transfer:true,overlay:'edit'};
  const instance = view(p);
  instance.error = 'A long error message. '.repeat(40);
  const confirm = checkFooter(render(instance,p),'cancel-change','confirm-' + mode);
  assert.equal(confirm.styles.border_color[0], mode === 'delete' ? 'ansi1' : 'solid');
}
const uploadProps = {mode:'job',overlay:'job',transfer:true,requests:[{action:'upload',source:'a.pdf',directory:'/project',job:'upload'}]};
const uploadJob = view(uploadProps);
bridgeResult = {ok:false,error:'Connection failed'};
uploadJob.work(cx);
assert.equal(checkFooter(render(uploadJob,uploadProps),'close-job').styles.disabled[0],true);
await finish();
checkFooter(render(uploadJob,uploadProps),'close-job','retry-file');
bridgeResult = {ok:false,code:'exists',error:'File exists'}; click('retry-file'); await finish();
const replace = checkFooter(render(uploadJob,uploadProps),'close-job','replace-file');
assert.equal(replace.styles.border_color[0],'ansi1');
bridgeResult = {ok:true,path:'/project/a.pdf'}; click('replace-file'); await finish();
assert.equal(jobs.at(-1).overwrite,true);
checkFooter(render(uploadJob,uploadProps),'close-job');

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

// Deliver row events, then the bubbled panel event in its own coordinate space.
const drag = panel();
drag.file.entries.get('').push({name:'archive',dir:true});
const panelBox = {x:200,y:50,width:480,height:600};
function pointer(id, type, x, y) {
  const bounds = {x:208,y:y-10,width:450,height:40};
  const event = box => ({position:{x,y},local_position:{x:x-box.x,y:y-box.y},bounds:box});
  const initial = stopped;
  if (id !== 'files') ids.get(id).handlers[type]?.(event(bounds),cx);
  if (stopped === initial) ids.get('files').handlers[type]?.(event(panelBox),cx);
}
function drawDrag() { render(drag.file,drag.props); return ids.get('file-drag-label'); }
function highlighted(id) { return ids.get(id).styles.border_color?.[0] === 'accent'; }
const down = 'on_mouse_down:left', up = 'on_mouse_up:left', move = 'on_mouse_move';
zoom = 2;
drawDrag();
pointer('file-folder/한글.txt',down,250,270);
pointer('files',move,252,270);
assert.ok(!drawDrag(), 'An ordinary click has no drag label');
pointer('file-archive',move,280,310);
let label = drawDrag();
assert.ok(label, 'Dragging a file renders its basename near the pointer');
assert.ok(label.contents.includes('한글.txt'));
assert.ok(highlighted('file-archive'));
const [left] = label.styles.left, [top] = label.styles.top;
assert.ok(left > 40 && left < 70 && top > 130 && top < 160, 'Label uses panel coordinates and app zoom');
const priorPaint = paints;
pointer('file-archive',move,292,318);
assert.ok(paints > priorPaint, 'Motion within one destination repaints the label');
label = drawDrag();
assert.equal(label.styles.left[0]-left,6);
assert.equal(label.styles.top[0]-top,4);
pointer('file-folder',move,270,235);
drawDrag();
assert.ok(!highlighted('file-folder') && !highlighted('file-archive'), 'Same parent is ineligible');
pointer('upload-root',move,322,120);
drawDrag();
assert.ok(highlighted('upload-root'));
pointer('files',move,670,640);
label = drawDrag();
assert.ok(label.styles.right[0] > 5 && label.styles.bottom[0] > 5, 'Panel edges keep the label inside');
assert.ok(!highlighted('upload-root'), 'Empty panel space clears the previous destination');
pointer('upload-root',move,322,120);
drawDrag();
pointer('upload-root',up,322,120);
assert.ok(!drawDrag() && !highlighted('upload-root'));
await finish();
assert.equal(jobs.at(-1).action,'move');
assert.equal(jobs.at(-1).source,'/project/folder/한글.txt');
assert.equal(jobs.at(-1).directory,'/project');

const beforeCancel = jobs.length, beforeSplit = splits.length;
pointer('file-a.pdf',down,255,275);
pointer('file-archive',move,290,310);
drawDrag();
ids.get('files').handlers.on_key_down({key:'escape'},cx);
assert.ok(!drawDrag() && !highlighted('file-archive'));
pointer('file-archive',up,290,310);
ids.get('file-a.pdf').handlers.on_click({},cx);
assert.equal(opened.length,0,'Releasing a cancelled drag does not open the file');
ids.get('files').handlers.on_hover(false,cx);
await finish();
assert.equal(jobs.length,beforeCancel);
assert.equal(splits.length,beforeSplit);
pointer('file-a.pdf',down,255,275);
pointer('file-archive',move,290,310);
drawDrag();
ids.get('files').handlers.on_hover(false,cx);
assert.ok(!drawDrag() && !highlighted('file-archive'));
assert.equal(splits.at(-1).doc.source,'/project/a.pdf','Leaving the panel retains split drag');
pointer('file-a.pdf',down,255,275);
pointer('file-a.pdf',up,255,275);
click('file-a.pdf');
assert.equal(opened.length,0,'A single click selects a PDF and keeps the tree active');
render(drag.file,drag.props);
assert.equal(ids.get('file-a.pdf').styles.bg[0],'selected');
runKey(ids.get('files-tree'),'delete');
assert.equal(overlays.at(-1).props.mode,'delete');
assert.equal(overlays.at(-1).props.target.source,'/project/a.pdf');
assert.equal(jobs.length,beforeCancel,'Del only opens the confirmation');
pointer('file-folder/한글.txt',down,255,275);
runKey(ids.get('files-tree'),'delete');
assert.equal(overlays.at(-1).props.target.source,'/project/folder/한글.txt','A key arriving before repaint acts on the latest selection');
pointer('file-folder',down,255,275);
const beforeFolderKey = overlays.length;
runKey(ids.get('files-tree'),'delete');
assert.equal(overlays.length,beforeFolderKey,'A stale file binding cannot open deletion on a folder');
focusedPane = {pane:'pane-right',tab:'tab-1'};
render(drag.file,drag.props);
pointer('file-a.pdf',down,255,275);
pointer('file-a.pdf',up,255,275);
focusedPane = null;
click('file-a.pdf',2);
assert.equal(opened.at(-1),'/project/a.pdf','Double-click opens the selected PDF');
assert.equal(destinations.at(-1),'pane-right');
focusedPane = {pane:'pane-left',tab:'tab-1'};
pointer('file-folder/한글.txt',down,255,275);
pointer('file-folder/한글.txt',up,255,275);
click('file-folder/한글.txt');
focusedPane = null;
render(drag.file,drag.props);
assert.equal(drag.file.file ?? null,null,'Selecting text keeps it in the tree');
ids.get('files-tree').handlers.on_key_down({key:'enter',keystroke:'enter'},cx);
assert.equal(opened.at(-1),'/project/folder/한글.txt');
assert.equal(destinations.at(-1),'pane-left');
zoom = 1;

const refresh = panel();
render(refresh.file,refresh.props);
pointer('file-folder/한글.txt',down,255,275);
pointer('file-folder/한글.txt',up,255,275);
listings.set('/project',[{name:'folder',dir:true},{name:'new.txt',dir:false}]);
listings.set('/project/folder',[{name:'new-child.txt',dir:false}]);
click('files-refresh');
click('files-refresh');
click('files-refresh');
await finish();
render(refresh.file,refresh.props);
assert.deepEqual(listed,[
  ['lab','/project'],['lab','/project/folder'],
  ['lab','/project'],['lab','/project/folder']
],'Repeated refresh during a scan queues one more scan on the same machine');
assert.ok(ids.has('file-new.txt') && ids.has('file-folder/new-child.txt') && !ids.has('file-a.pdf'));
assert.equal(refresh.file.selected,null,'A file removed outside the app cannot be targeted by Del');
listings.set('/project',[]);
ids.get('files-tree').handlers.on_key_down({key:'f5',keystroke:'f5'},cx);
await finish();
render(refresh.file,refresh.props);
assert.ok(!ids.has('file-folder') && !refresh.file.folders.has('folder'));
assert.equal(refresh.file.error,null,'An externally removed expanded folder is skipped');
assert.equal(listed.length,5);

const windows = panel('C:\\project\\',null);
render(windows.file,windows.props);
pointer('file-a.pdf',down,255,275);
pointer('files',move,285,295);
ids.get('files').handlers.on_hover(false,cx);
assert.equal(splits.at(-1).doc.source,'C:\\project\\a.pdf','Dragging and opening use the same path at a Windows root');

if (staged) {
  popup = menuAt(panel('/project','lab',{pdf:true}),'file-a.pdf');
  assert.ok(ids.has('open-side') && !ids.has('cut') && !ids.has('download'));
  const transfer = panel('/project','lab',{transfer:true});
  popup = menuAt(transfer,'file-a.pdf');
  assert.ok(ids.has('cut') && !ids.has('open-side'));
  render(transfer.file,transfer.props);
  pointer('file-a.pdf',down,255,275);
  pointer('file-folder',move,290,310);
  render(transfer.file,transfer.props);
  assert.ok(ids.has('file-drag-label') && highlighted('file-folder'));
  const splitCount = splits.length;
  ids.get('files').handlers.on_hover(false,cx);
  render(transfer.file,transfer.props);
  assert.ok(!ids.has('file-drag-label') && !highlighted('file-folder'));
  assert.equal(splits.length,splitCount,'Transfer alone does not start a document split');
  const disabled = panel('/project','lab',{});
  render(disabled.file,disabled.props);
  assert.ok(!ids.get('file-a.pdf').handlers['on_mouse_down:right']);
  assert.ok(!ids.has('upload-root'));
  assert.ok(ids.has('files-refresh'),'Refresh also works without transfer or document features');
  pointer('file-a.pdf',down,255,275);
  click('file-a.pdf',2);
  assert.equal(disabled.file.file,'a.pdf','With PDF disabled, opening retains the built-in inline preview');
}
console.log('Files UI checks passed', staged ? '(staged)' : '(source)');
