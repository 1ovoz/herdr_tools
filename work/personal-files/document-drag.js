import { openOverlay, shared, spaces, focused, panes, run, setShared, notify } from "herdr";
import { jobId } from "./actions.js";

const TAB_DOCS = "personal-files.document-tabs";
const PANE_DOCS = "personal-files.document-panes";
const DOCUMENTS_AT_PANE = "personal-files.pane-documents";

export function fileDocument(source,on) {
  return {source,on,mode:/\.pdf$/i.test(source)?"pdf":"document",name:source.split(/[\\/]/).pop()};
}

export function documentsByTab() { return shared(TAB_DOCS) || {}; }
export function documentPane(id) { return id ? shared(PANE_DOCS)?.[id] : null; }

function remember(key,id,value) {
  const entries=Object.entries(shared(key)||{}).filter(([name])=>name!==id).slice(-99);
  setShared(key,Object.fromEntries([...entries,[id,value]]));
}

export function registerDocument(doc, tab, pane, anchorTab) {
  if (doc?.id) remember(PANE_DOCS,doc.id,pane);
  if (doc?.source && pane) remember(DOCUMENTS_AT_PANE,pane,{...doc,anchorTab,tab});
  if (!doc?.split && doc?.source && tab) remember(TAB_DOCS,tab,{...doc,anchorTab,tab});
}

export function saveDocumentPosition(tab, pane, id, position) {
  const placed=shared(DOCUMENTS_AT_PANE)?.[pane];
  if (placed && (placed.id??null)===(id??null)) remember(DOCUMENTS_AT_PANE,pane,{...placed,position});
  const entry=documentsByTab()[tab];
  if (entry && (entry.id??null)===(id??null)) remember(TAB_DOCS,tab,{...entry,position});
}

async function newDocumentTab(doc,space,anchorTab,cx) {
  const before=new Set(space.tabs.map(tab=>tab.id));
  const id=jobId();
  const next={source:doc.source,on:doc.on,mode:doc.mode,name:doc.name,position:doc.position,id,anchorTab};
  run("tab.new",{name:doc.name,space:space.id,mod:"personal-files",props:next});
  for(let retry=0;retry<40;retry++) {
    const shown=spaces().find(s=>s.id===space.id);
    if (!shown) return false;
    const tab=shown.tabs.find(t=>!before.has(t.id) && t.name===doc.name && t.active);
    const pane=panes().find(p=>p.tab===tab?.id && p.mod==="personal-files");
    if (pane) {
      registerDocument(next,tab.id,pane.pane,anchorTab);
      return true;
    }
    await cx.sleep(50);
  }
  return false;
}

export function openDocument(doc,cx) {
  const space=spaces().find(s=>s.active);
  if (space) cx.spawn(task=>newDocumentTab(doc,space,focused()?.tab,task));
}

export async function liftPane(paneId,cx) {
  const layoutPanes=panes();
  const source=layoutPanes.find(p=>p.pane===paneId);
  const space=spaces().find(s=>s.active);
  if (!source || !space?.tabs.some(tab=>tab.id===source.tab) ||
      layoutPanes.filter(p=>p.tab===source.tab).length<2) return false;

  if (source.mod==="personal-files") {
    const doc=shared(DOCUMENTS_AT_PANE)?.[paneId];
    if (!doc || !await newDocumentTab(doc,space,source.tab,cx)) return false;
    if (panes().some(p=>p.pane===paneId && p.tab===source.tab)) run("pane.close",{pane:paneId});
    return true;
  }

  const terminal=source.terminal;
  if (!terminal) return false;
  run("terminal.park",{terminal});
  for (let attempt=0;attempt<100 && panes().some(p=>p.terminal===terminal);attempt++) await cx.sleep(100);
  if (panes().some(p=>p.terminal===terminal)) return false;
  if (!spaces().some(s=>s.id===space.id && s.active)) run("space.select",{id:space.id});
  run("terminal.keep",{terminal,place:"tab"});
  for (let attempt=0;attempt<100;attempt++) {
    const moved=panes().find(p=>p.terminal===terminal && p.tab!==source.tab);
    if (moved) {
      if (source.name) run("tab.rename",{id:moved.tab,name:source.name});
      return true;
    }
    await cx.sleep(100);
  }
  throw new Error("The terminal is still running. Open it from Agents and choose Keep as tab.");
}

export function startDocumentDrag(doc, side) {
  openOverlay({mod:"personal-files",kind:"window",key:"personal-files-drag",frame:"none",
    width:1,height:1,at:{x:0,y:0},props:{mode:"drop",drag:doc,side}});
}

export function movement(start,event) {
  return Math.hypot(event.position.x-start.x,event.position.y-start.y)>5;
}

export async function splitDocument(doc,side,cx) {
  const space=spaces().find(s=>s.active);
  if (!space) return false;
  const sourcePanes=doc.tab?panes().filter(p=>p.tab===doc.tab):[];
  const canMove=sourcePanes.length===1 && sourcePanes[0].mod==="personal-files";
  const listed=space.tabs.filter(tab=>tab.id!==doc.tab);
  const target=listed.find(tab=>tab.active)||listed.find(tab=>tab.id===doc.anchorTab)||[...listed].reverse().find(tab=>panes().some(p=>p.tab===tab.id && p.terminal))||listed.at(-1);
  if (!target) {
    notify({title:"Open a workspace tab to split beside",level:"info"});
    return false;
  }
  if (!target.active) run("tab.select",{id:target.id});
  for(let retry=0;retry<20 && focused()?.tab!==target.id;retry++) await cx.sleep(40);
  const current=focused();
  const list=panes().filter(p=>p.tab===target.id);
  const anchor=side==="left"?list[0]:list.at(-1);
  if (!anchor || current?.tab!==target.id) return false;
  const seen=new Set(list.map(p=>p.pane));
  const next={source:doc.source,on:doc.on,mode:doc.mode,name:doc.name,split:true,id:jobId(),position:doc.position};
  run("pane.split",{pane:anchor.pane,direction:"right",mod:"personal-files",props:next});
  let created;
  for(let retry=0;retry<45;retry++) {
    created=panes().find(p=>p.tab===target.id && !seen.has(p.pane) && p.mod==="personal-files");
    if (created) break;
    await cx.sleep(55);
  }
  if (!created) return false;
  registerDocument(next,target.id,created.pane,null);
  if (side==="left") run("pane.swap",{pane:created.pane,target:anchor.pane});
  const remaining=canMove?panes().filter(p=>p.tab===doc.tab):[];
  if (remaining.length===1 && remaining[0].pane===sourcePanes[0].pane && remaining[0].mod==="personal-files") {
    run("tab.close",{id:doc.tab,confirmed:true});
  }
  run("pane.focus",{pane:created.pane});
  return true;
}
