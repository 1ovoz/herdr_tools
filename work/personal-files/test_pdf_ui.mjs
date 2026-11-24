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
console.log('PDF scrolling, pointer-anchored Ctrl+wheel zoom, raster sizing and text selection passed');
