import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { pageAt, pageFlow, restorePosition } from './document-flow.js';
import { geometry, wheelPosition, hitChar, selectedText, selectionRects } from './pdf-geometry.js';
const g=geometry({width:1200,height:900,appZoom:1.2,zoom:1,pdf:{width:600,height:1000}});
assert.equal(g.width,970);
assert.equal(g.viewportHeight,644);
assert.ok(g.maxY>0);
let pos=wheelPosition({x:0,y:0},{delta:{x:0,y:-120}},g,1.2);
assert.equal(pos.y,100);
pos=wheelPosition(pos,{delta:{x:0,y:10000}},g,1.2);assert.equal(pos.y,0);
pos=wheelPosition(pos,{delta_lines:{x:0,y:-10000},delta:{x:0,y:-100}},g,1.2);assert.equal(pos.y,g.maxY);
const chars=[{t:'A',r:[0.1,0.1,0.2,0.15]},{t:'B',r:[0.2,0.1,0.3,0.15]},{t:'\n',r:null},{t:'한',r:[0.1,0.2,0.2,0.25]}];
assert.equal(hitChar(chars,.15,.12),0);
assert.equal(hitChar(chars,.15,.22),3);
assert.equal(selectedText(chars,0,3),'AB\n한');
assert.equal(selectedText(chars,3,0),'AB\n한');
assert.equal(selectionRects(chars,0,3).length,2);
// Exercise the viewer itself with the wheel event shapes delivered by GPUI.
const source = readFileSync(process.argv[2] || new URL('./document-view.js', import.meta.url), 'utf8')
  .replace(/^import .*;\r?\n/gm, '').replace(/export (?:default )?class DocumentView/, 'class DocumentView');
const appZoom = 1.25;
const blocks=vm.runInNewContext(source+'\nmarkdownBlocks',{View:class{}});
assert.deepEqual([...blocks('# title\n\n![alt](pic.png)\n<img src=x>')],['# title\n\n&#33;[alt](pic.png)\n&lt;img src=x>']);
assert.deepEqual([...blocks('~~~js\nconst x="<img>";\n~~~')],['~~~js\nconst x="<img>";\n~~~']);
const DocumentView = vm.runInNewContext(source + '\nDocumentView', {
  View: class {}, settings: () => ({zoom: appZoom}), pageAt, pageFlow, restorePosition
});
const viewer = new DocumentView();
Object.assign(viewer, {width:1000, height:600, zoom:1, scroll:{x:0,y:1200},
  sizes:[[600,900],[600,900],[900,600]], queuePages() {}});
let stopped = 0;
const cx = {notify() {}, stop_propagation() { stopped++; }};
const cursor = {x:375,y:150};
const scroll = (dy, modifiers, lines) => viewer.wheel({
  delta:{x:0,y:dy}, delta_lines:lines, local_position:cursor, modifiers
}, cx);
function underCursor() {
  const flow = viewer.flow();
  const y = viewer.scroll.y + cursor.y/appZoom;
  const page = flow.pages[pageAt(flow, y)];
  return [(viewer.scroll.x + cursor.x/appZoom - 12)/page.width, (y-page.top)/page.height];
}
const before = underCursor();
scroll(84,{control:true},{x:0,y:3});
assert.equal(viewer.zoom,1.25);
assert.ok(underCursor().every((v,i)=>Math.abs(v-before[i])<1e-8));
scroll(-80,{control:true});
assert.equal(viewer.zoom,1);
for (let i=0;i<8;i++) scroll(84,{control:true},{x:0,y:3});
assert.equal(viewer.zoom,2);
const yBefore = viewer.scroll.y;
scroll(-25,{});
assert.equal(viewer.scroll.y,yBefore+20);
const xBefore = viewer.scroll.x;
scroll(-25,{shift:true});
assert.equal(viewer.scroll.x,xBefore+20);
assert.equal(viewer.scroll.y,yBefore+20);
for (let i=0;i<12;i++) scroll(-84,{control:true},{x:0,y:-3});
assert.equal(viewer.zoom,0.5);
scroll(0,{control:true});
assert.equal(viewer.zoom,0.5);
assert.equal(stopped,25);

viewer.zoom = 1;
const raster = viewer.rasterWidth();
assert.ok(raster >= viewer.flow().pages[0].width*appZoom*2);
viewer.width = 1750;
assert.ok(viewer.rasterWidth() > raster);
viewer.zoom = 2;
assert.equal(viewer.rasterWidth(),4096);
// Page loading: one helper run per screenful, pages kept for scrolling back, and bounded retries.
const flowApi = await import('./document-flow.js');
// Values made inside the viewer's context compare by content.
const plain = value => JSON.parse(JSON.stringify(value));
function loader(pageCount, charsPerPage = 1) {
  const state = {requests:[], timers:[], pending:[], fail:new Set(), clock:1_000_000, revision:'1'};
  const Viewer = vm.runInNewContext(source + '\nDocumentView', {
    View: class {}, settings: () => ({zoom:1}), ...flowApi, jobId: () => 'job', Date: {now: () => state.clock},
    groupState: () => ({active:'doc'}), focused: () => ({tab:'tab'}),
    bridge: async request => {
      state.requests.push(request);
      if (request.pages.some(page => state.fail.has(page))) return {ok:false,code:'pdf',error:'render failed'};
      return {ok:true,revision:[state.revision],rendered:request.pages.map((page,i) => ({page,image:`page-${page}-${request.width}.png`,
        width:request.width,height:1,chars:request.chars[i] ? Array(charsPerPage).fill({t:'a',r:[0,0,1,1]}) : []}))};
    },
  });
  const view = new Viewer();
  Object.assign(view,{document:{source:'C:/docs/a.pdf',on:null,mode:'pdf'},cachedPdf:'C:/docs/a.pdf',revision:'1',
    width:1000,height:1900,zoom:1,scroll:{x:0,y:0},sizes:Array.from({length:pageCount},() => [600,800]),
    pages:new Map(),requestVersion:1,renderingPage:false,groupId:'group',documentId:'doc',viewerTab:'tab'});
  const cx = {notify() {}, stop_propagation() {}, spawn: fn => state.pending.push(fn(cx)),
    timer:{after: (ms,fn) => { state.timers.push({ms,fn}); return {cancel() {}}; }}};
  const settle = async () => { while (state.pending.length) await state.pending.shift(); };
  return {state,view,cx,settle};
}
{
  const {state,view,cx,settle} = loader(30);
  const flow = view.flow(), shown = flowApi.visiblePages(flow,0);
  assert.deepEqual(shown,[0,1],'This fixture shows two pages at the top');
  view.queuePages(cx); view.queuePages(cx);
  await settle();
  assert.deepEqual(plain(state.requests.map(r => r.pages)),[[0,1],[2],[3]],
    'Missing visible pages share one helper run, then two pages are read ahead one at a time');
  assert.deepEqual(plain(state.requests[0].chars),[true,true]);
  assert.equal(state.requests[0].action,'preview');
  view.moveTo(0,flow.pages[2].top,cx);
  await settle();
  assert.deepEqual(plain(state.requests.slice(3).map(r => r.pages)),[[4],[5]],'Pages read ahead are not rendered again on arrival');
  const before = state.requests.length;
  view.moveTo(0,0,cx);
  await settle();
  assert.equal(state.requests.length,before,'Scrolling back to kept pages starts no helper');
  assert.ok(view.pages.get(0).chars.length,'Kept pages still carry their text for selection');
  view.zoom = 2;
  view.queuePages(cx);
  await settle();
  const sharper = state.requests.slice(before);
  assert.deepEqual(plain(sharper[0].pages),[0]);
  assert.deepEqual(plain(sharper[0].chars),[false],'A sharper bitmap reuses the text already extracted');
  assert.ok(view.pages.get(0).chars.length);
  view.zoom = 1;
  for (let page = 0; page < 30; page++) { view.moveTo(0,flow.pages[page].top,cx); await settle(); }
  assert.ok(view.pages.size <= 12 + 3,'Only nearby pages are kept: ' + view.pages.size);
  assert.ok(view.pages.has(29) && !view.pages.has(0));
  const calm = state.requests.length;
  state.clock += 9*60*1000;
  view.queuePages(cx);
  await settle();
  assert.ok(state.requests.slice(calm).some(r => r.pages.includes(29)),'A page shown past its cache protection is asked for again');
}
{
  const {state,view,cx,settle} = loader(30);
  for (let page = 0; page < 30; page++) state.fail.add(page);
  view.queuePages(cx);
  await settle();
  assert.deepEqual(plain(state.requests.map(r => r.pages)),[[0,1],[2],[3]],'A broken helper is tried once per page, not in a loop');
  assert.equal(state.timers.length,1);
  const waits = [];
  while (state.timers.length) {
    const {ms,fn} = state.timers.shift();
    waits.push(ms);
    state.clock += ms;
    fn(cx);
    await settle();
  }
  assert.deepEqual(waits,[2000,8000,30000],'Visible pages are retried further apart, then left alone');
  const stopped = state.requests.length;
  assert.ok(stopped <= 3 + 3*3,'Retries stay bounded: ' + stopped);
  state.clock += 3600*1000;
  view.queuePages(cx);
  await settle();
  assert.equal(state.requests.filter(r => r.pages.includes(0)).length,4,'After the last retry a visible page waits for the person');
  state.fail.clear();
  view.startSelection({},cx);
  await settle();
  assert.ok(view.pages.has(0) && view.pages.has(1),'A click on the page loads it again');
}
{
  const {state,view,cx,settle} = loader(10,50000);
  // Cap this fixture's helper launches so a recurring prefetch fails promptly.
  cx.spawn = fn => { if (state.requests.length < 8) state.pending.push(fn(cx)); };
  view.queuePages(cx);
  await settle();
  assert.deepEqual(plain(state.requests.map(r => r.pages)),[[0,1],[2],[3]],
    'A dense prefetched page evicted by the character budget is requested once per viewport');
  assert.ok(!view.pages.has(3));
  view.moveTo(0,view.flow().pages[3].top,cx);
  await settle();
  assert.ok(view.pages.has(3),'An evicted page is loaded when it becomes visible');
}
{
  const {state,view,cx,settle} = loader(4);
  state.revision = '2';
  view.queuePages(cx);
  await settle();
  assert.equal(view.pages.size,0,'A bitmap of a file that changed meanwhile is not shown');
  assert.equal(state.timers.length,1,'It is retried, and the change poll reloads the document');
}
console.log('PDF scrolling, pointer-anchored Ctrl+wheel zoom, raster sizing, text selection and page loading passed');
