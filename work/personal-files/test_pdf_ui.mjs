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
// Drive the HTML tab through its layout callback, capture, revision poll and toolbar.
{
  let revision='1', clock=1_000_000, textError=false;
  const requests=[], timers=new Set(), jobs=new Set(), captures=[];
  const node=(kind, value)=>{
    const data={kind,value,children:[],calls:{}};
    const el=new Proxy(data,{get(target,key) {
      if (key in target) return target[key];
      return (...args)=>{
        if (key==='when') { if (args[0]) args[1](el); }
        else if (key==='child') data.children.push(args[0]);
        else data.calls[key]=args;
        return el;
      };
    }});
    return el;
  };
  const walk=(el,predicate)=>{
    if (!el || typeof el!=='object') return;
    if (predicate(el)) return el;
    for (const child of el.children) { const found=walk(child,predicate); if(found) return found; }
  };
  const byId=(tree,id)=>walk(tree,el=>el.calls.id?.[0]===id);
  const byKind=(tree,kind)=>walk(tree,el=>el.kind===kind);
  const bridge=async q=>{
    requests.push(q);
    switch(q.action) {
      case 'revision': return {ok:true,revision:[revision]};
      case 'text':
        if (textError) throw Error('Cannot decode text');
        return {ok:true,revision:[revision],text:'<h1 class="hero">'+revision+'</h1>',html:'<h1>'+revision+'</h1>'};
      case 'html-preview': return new Promise(resolve=>captures.push(resolve));
      case 'html-open': return {ok:true};
      default: throw Error('Unexpected request '+q.action);
    }
  };
  const Viewer=vm.runInNewContext(source+'\nGroupPage',{
    View:class {}, checking:()=>false, focused:()=>({tab:'work'}),groupState:()=>({active:'doc'}),
    theme:()=>({}),settings:()=>({zoom:1.25}),jobId:()=>'job',bridge,pageAt,pageFlow,
    Date:{now:()=>clock},v_flex:()=>node('column'),h_flex:()=>node('row'),div:()=>node('div'),
    image:path=>node('image',path),EditorState:{new:opts=>({...opts,release(){}})},
    Editor:{new:code=>node('editor',code.value)},TextView:{html:(_id,html)=>node('text',html)}
  });
  const cx={timer:{
    after(_delay,fn) { const timer={fn,cancel(){ timers.delete(timer); }}; timers.add(timer); return timer; },
    every(_delay,fn) { cx.poll=fn; }
  },spawn(fn) { const job=fn(cx); jobs.add(job); job.finally(()=>jobs.delete(job)); },
    notify(){},focus_handle(){return {};}};
  const runTimers=()=>{for(const timer of [...timers]){timer.cancel();timer.fn(cx);}};
  const doc=new Viewer();
  doc.initPage({id:'doc',groupId:'group',tab:'work',source:'/reports/보고서.HTM',on:'lab',mode:'document'},cx);
  const render=()=>doc.renderPage(cx);
  const resize=(width,height)=>byId(render(),'html-preview').calls.on_size_change[0]({width,height},cx);
  const click=id=>byId(render(),id).calls.on_click[0]({},cx);
  const captureCount=()=>requests.filter(q=>q.action==='html-preview').length;
  const png=(name,width,height,rev=revision,extra={})=>({ok:true,image:'data/files/'+name+'.png',width,height,revision:[rev],...extra});
  const finish=async reply=>{captures.shift()(reply);await Promise.all([...jobs]);};
  await Promise.all([...jobs]);
  assert.equal(doc.code.language,'html');
  assert.equal(requests.some(q=>q.action==='html-open'),false);
  assert.ok(byId(render(),'html-open'),'HTML tabs have an explicit browser action');
  resize(875,500); resize(750,450);
  runTimers();
  assert.equal(captureCount(),1,'Dragging the divider coalesces viewport measurements');
  const first=requests.find(q=>q.action==='html-preview');
  assert.deepEqual([first.source,first.on,first.width,first.height],['/reports/보고서.HTM','lab',600,360]);
  await finish(png('wide',600,1200));
  const image=byKind(render(),'image');
  assert.equal(image.value,'data/files/wide.png');
  assert.deepEqual([image.calls.w[0],image.calls.h[0]],[600,1200]);
  assert.ok(image.calls.flex_none && byId(render(),'html-preview').calls.overflow_y_scrollbar,
    'A tall page retains its aspect ratio and scrolls inside the tab');
  resize(650,450); runTimers();
  assert.equal(captureCount(),2);
  resize(500,450); runTimers();
  assert.equal(captureCount(),2,'Only one Edge capture runs at a time in this tab');
  assert.equal(byKind(render(),'image').value,'data/files/wide.png','The last good frame stays visible during resize');
  await finish(png('intermediate',520,400));
  assert.equal(byKind(render(),'image').value,'data/files/wide.png','A superseded layout never replaces the good frame');
  runTimers();
  assert.equal(captureCount(),3);
  await finish(png('narrow',400,1080));
  assert.equal(byKind(render(),'image').value,'data/files/narrow.png');
  for(let n=0;n<10;n++) { render(); runTimers(); }
  assert.equal(captureCount(),3,'An unchanged frame causes no extra captures');
  click('html-toggle');
  assert.equal(byKind(render(),'editor').value,'<h1 class="hero">1</h1>');
  revision='2'; clock+=20000; cx.poll(cx); await Promise.all([...jobs]); render(); runTimers();
  assert.equal(captureCount(),3);
  assert.equal(byKind(render(),'editor').value,'<h1 class="hero">2</h1>','Save updates Source while preview is hidden');
  click('html-toggle'); render(); resize(500,450); runTimers();
  assert.equal(captureCount(),4,'Returning to Preview picks up a save without another resize');
  await finish(png('saved',400,600));
  assert.equal(byKind(render(),'image').value,'data/files/saved.png');
  revision='3'; clock+=20000; cx.poll(cx); await Promise.all([...jobs]); render(); runTimers();
  assert.equal(captureCount(),5,'A visible preview refreshes on save at a fixed width');
  await finish({ok:false,error:'Edge unavailable'});
  assert.equal(byKind(render(),'text').value,'<h1>3</h1>','A failed browser render falls back to current readable HTML');
  for(let n=0;n<10;n++) { render(); runTimers(); }
  assert.equal(captureCount(),5,'A failed capture waits for a change or explicit retry');
  assert.equal(requests.some(q=>q.action==='html-open'),false);
  click('html-open'); await Promise.all([...jobs]);
  const opened=requests.filter(q=>q.action==='html-open');
  assert.deepEqual(opened.map(q=>[q.source,q.on]),[['/reports/보고서.HTM','lab']]);
  textError=true;
  revision='4'; clock+=20000; cx.poll(cx); await Promise.all([...jobs]); render(); runTimers();
  assert.equal(captureCount(),6,'Source decoding failure does not prevent a browser capture of the saved bytes');
  await finish(png('old',400,540,'3'));
  assert.equal(byKind(render(),'image'),undefined,'A bitmap from before the save cannot replace the current preview');
  revision='5'; clock+=20000; cx.poll(cx); await Promise.all([...jobs]); render(); runTimers();
  assert.equal(captureCount(),7);
  await finish(png('browser-decoded',400,4000,'5',{truncated:true}));
  const clipped=render();
  assert.equal(byKind(clipped,'image').value,'data/files/browser-decoded.png');
  assert.ok(walk(clipped,el=>el.children.some(child=>typeof child==='string' && /rest of this page/i.test(child))),
    'A clipped page explains how to read past the bitmap limit');
  console.log('HTML viewport capture, save refresh, Source, browser action and readable fallback passed');
}
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
