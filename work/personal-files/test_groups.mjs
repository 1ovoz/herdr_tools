import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(process.argv[2] || new URL('./document-drag.js',import.meta.url),'utf8');
const mod=source.includes('herdr-kit-pdf')?'herdr-kit-pdf':'personal-files';
const store=new Map(), calls=[];
const tabs=[{id:'work',active:true},{id:'older',active:false}];
const panels=[{pane:'left',tab:'work',mod},{pane:'right',tab:'work',mod},
  {pane:'shell',tab:'work',terminal:'t1'},{pane:'old-pane',tab:'older',mod}];
let focus='left',seq=0;
const api=vm.runInNewContext(source.replace(/^import .*;$/gm,'').replace(/^export /gm,'')+
  '\n({routeDocument,attachGroup,groupState,choosePage,closePage,saveDocumentPosition,registerDocument})',{
  jobId:()=>String(++seq),shared:k=>store.get(k),setShared:(k,v)=>store.set(k,v),
  panes:()=>panels,spaces:()=>[{id:'s',active:true,tabs}],focused:()=>({space:'s',tab:tabs.find(t=>t.active).id,pane:focus}),
  run:(name,args)=>{
    calls.push([name,args]);
    if(name==='pane.focus') focus=args.pane;
    if(name==='tab.select') for(const t of tabs)t.active=t.id===args.id;
    if(name==='pane.split'){
      const p={pane:'created',tab:'work',mod}; panels.push(p); focus=p.pane;
    }
  }
});
const file=(source,on=null)=>({source,on,name:source.split(/[\\/]/).pop(),mode:'document'});
for(const pane of ['left','right']) api.attachGroup({groupId:pane},panels.find(p=>p.pane===pane));
api.routeDocument(file('C:\\work\\Readme.md'),'s','work','left');
api.routeDocument(file('/tmp/b.md','lab'),'s','work','right');
api.routeDocument(file('/tmp/c.md','lab'),'s','work','right');
assert.equal(api.groupState('right').docs.length,2);
assert.equal(api.groupState('left').docs.length,1);
api.routeDocument(file('c:/work/./README.md'),'s','work','right');
assert.equal(focus,'left');
assert.equal(calls.some(([n])=>n==='tab.new'||n==='pane.split'),false);
api.routeDocument(file('/tmp/B.md','lab'),'s','work','right');
api.routeDocument(file('/tmp/b.md','other'),'s','work','right');
const g=api.groupState('right');
assert.equal(g.docs.length,4);
const first=g.docs[0];
api.saveDocumentPosition('work','right',first.id,{zoom:1.5,anchor:[1,.3]});
api.choosePage('right',first.id);
assert.equal(api.groupState('right').active,first.id);
assert.equal(api.groupState('right').docs[0].position.zoom,1.5);
api.closePage('right',first.id);
assert.equal(api.groupState('right').docs.length,3);
assert.notEqual(api.groupState('right').active,first.id);
api.registerDocument({...file('/tmp/old.md','lab'),id:'legacy'},'older','old-pane',null);
api.routeDocument(file('/tmp/old.md','lab'),'s','work','left');
assert.equal(focus,'old-pane');
assert.equal(tabs[1].active,true);
api.routeDocument(file('/shell-a.txt'),'s','work','shell');
api.routeDocument(file('/shell-b.txt'),'s','work','shell');
assert.equal(calls.filter(([n])=>n==='pane.split').length,1);
assert.equal(calls.find(([n])=>n==='pane.split')[1].pane,'shell');
assert(!calls.some(([n])=>['terminal.kill','terminal.park','pane.close'].includes(n)));
const viewSource=readFileSync(process.argv[3] || new URL('./document-view.js',import.meta.url),'utf8');
function element() {
  const node=new Proxy({}, {get(_target,key){
    if (key==='when') return (condition,build)=>condition ? build(node) : node;
    return ()=>node;
  }});
  return node;
}
const DocumentView=vm.runInNewContext(viewSource.replace(/^import .*;$/gm,'')
  .replace('export default class DocumentView','class DocumentView').replace('export class DocumentView','class DocumentView')
  +'\nDocumentView',{View:class{},groupState:api.groupState,theme:()=>({}),checking:()=>false,
    h_flex:element,v_flex:element,div:element});
const view=new DocumentView();
Object.assign(view,{groupId:'right',openViews:new Map(),tabScroll:{scroll_to_item(){}}});
const released=[];
const cx={notify(){},new:(_view,doc)=>({id:doc.id,release(){released.push(doc.id);}})};
const [a,b]=api.groupState('right').docs;
// Herdr runs a spawned callback's synchronous prefix in the current phase.
// Creating a retained child is only legal after the render has returned.
const pending=[];
const renderPhase={
  new(){throw new Error('cx.new during render');},
  spawn(fn){fn(renderPhase);},
  timer:{after(_ms,fn){pending.push(fn);}},
};
view.renderDocument(renderPhase);
view.renderDocument(renderPhase);
assert.equal(pending.length,1);
api.choosePage('right',a.id);
pending.shift()(cx);
assert.equal(view.page.id,a.id);
view.renderDocument(renderPhase);
assert.equal(pending.length,0);
const original=view.page;
api.choosePage('right',b.id); view.syncOpenViews(cx);
api.choosePage('right',a.id); view.syncOpenViews(cx);
assert.equal(view.page,original);
api.closePage('right',b.id); view.syncOpenViews(cx);
assert.deepEqual(released,[b.id]);
for(let i=0;i<6;i++){
  api.routeDocument(file('/src/'+i+'.txt'),'s','work','right');
  view.syncOpenViews(cx);
}
assert.equal(view.openViews.size,4);
assert.ok(released.includes(a.id));
assert.ok(api.groupState('right').docs.some(d=>d.id===a.id));
console.log('Independent pane tabs, path identity, legacy focus and terminal preservation passed');
