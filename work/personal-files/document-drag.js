import { openOverlay, shared, spaces, focused, panes, run, setShared, notify } from "herdr";
import { jobId } from "./actions.js";

const TAB_DOCS = "personal-files.document-tabs";
const PANE_DOCS = "personal-files.document-panes";
const DOCUMENTS_AT_PANE = "personal-files.pane-documents";
const GROUPS = "personal-files.file-groups";

function groups() { return shared(GROUPS) || {}; }
export function groupState(id) { return groups()[id]; }

function writeGroup(id, group) {
  const all = {...groups()};
  // Keep groups on briefly disconnected machines. Reclaim old, closed entries first.
  const live = new Set(panes().map(p => p.pane));
  const stale = Object.keys(all).filter(key => key !== id && !live.has(all[key].pane));
  for (const key of stale.slice(0, Math.max(0,stale.length-64))) delete all[key];
  setShared(GROUPS, {...all,[id]:group});
}

function sameFile(a,b) {
  if (!a?.source || !b?.source || (a.on ?? null) !== (b.on ?? null)) return false;
  const path = value => {
    const windows=/^(?:[a-z]:[\\/]|\\\\|\/\/)/i.test(value);
    const normal=windows ? value.replace(/\\/g,"/").toLowerCase() : value;
    const prefix=normal.startsWith("//") ? "//" : normal.startsWith("/") ? "/" : "";
    return prefix + normal.split("/").filter(part=>part && part!==".").join("/");
  };
  return path(a.source) === path(b.source);
}

function publishActive(group) {
  if (!group.pane) return;
  const current = group.docs.find(doc => doc.id === group.active);
  const single = panes().filter(p => p.tab === group.tab).length === 1;
  if (current) registerDocument({...current,split:!single},group.tab,group.pane,current.anchorTab);
  else {
    remember(DOCUMENTS_AT_PANE,group.pane,null);
    if (single) remember(TAB_DOCS,group.tab,null);
  }
}

export function attachGroup(p, pane) {
  const id = p.groupId || p.id || (pane && "pane-"+pane.pane);
  if (!id) return null;
  let group = groupState(id);
  if (!group) {
    const seed = p.source ? {...fileDocument(p.source,p.on),...p,id:p.id || jobId()} : null;
    group = {docs:seed?[seed]:[],active:seed?.id ?? null,anchorPane:p.anchorPane,
      tab:p.anchorTab,created:Date.now()};
  } else if (!pane || group.pane === pane.pane && group.tab === pane.tab) return id;
  if (pane) group = {...group,pane:pane.pane,tab:pane.tab};
  writeGroup(id,group);
  publishActive(group);
  return id;
}

export function choosePage(id,page) {
  const group=groupState(id);
  if (!group || !group.docs.some(doc=>doc.id===page)) return;
  if (group.active!==page) {
    const next={...group,active:page};
    writeGroup(id,next);
    publishActive(next);
  }
}

export function closePage(id,page) {
  const group=groupState(id);
  if (!group) return;
  const index=group.docs.findIndex(doc=>doc.id===page);
  if (index<0) return;
  const docs=group.docs.filter(doc=>doc.id!==page);
  const active=group.active===page ? docs[Math.min(index,docs.length-1)]?.id ?? null : group.active;
  const next={...group,docs,active};
  writeGroup(id,next);
  publishActive(next);
}

export function groupPaneFor(p) {
  const all=groups(), list=panes().filter(entry=>entry.mod==="personal-files");
  const known=all[p.groupId || p.id]?.pane || documentPane(p.id);
  if (known) return list.find(entry=>entry.pane===known);
  // Old link-created tabs may have no document id. Prefer their persisted pane registration.
  const old=shared(DOCUMENTS_AT_PANE) || {};
  const matching=list.find(entry=>old[entry.pane] && sameFile(old[entry.pane],p) &&
    (!p.id || old[entry.pane].id===p.id));
  if (matching) return matching;
  const current=focused();
  return list.find(entry=>entry.pane===current?.pane && !Object.values(all).some(g=>g.pane===entry.pane));
}

export function routeDocument(doc,spaceId,tabId,paneId) {
  const space=spaces().find(s=>s.id===spaceId);
  if (!space || !doc?.source) return false;
  const tabs=new Set(space.tabs.map(t=>t.id));
  const live=panes().filter(p=>tabs.has(p.tab));
  const tab=tabs.has(tabId)?tabId:space.tabs.find(t=>t.active)?.id;
  const owner=live.find(p=>p.tab===tab && p.pane===paneId) ||
    live.find(p=>p.tab===tab && (p.focused || p.pane===focused()?.pane)) || live.find(p=>p.tab===tab);
  const all=Object.entries(groups());
  const assigned=p=>all.find(([,g])=>g.tab===p.tab && g.pane===p.pane);
  function focus(p) {
    if (!space.active) run("space.select",{id:space.id});
    if (focused()?.tab!==p.tab) run("tab.select",{id:p.tab});
    const zoomed=live.find(item=>item.tab===p.tab && item.zoomed && item.pane!==p.pane);
    if (zoomed) run("pane.zoom",{pane:zoomed.pane});
    run("pane.focus",{pane:p.pane});
  }
  const old=shared(DOCUMENTS_AT_PANE) || {};
  for (const p of [owner,...live]) {
    if (!p || p.mod!=="personal-files") continue;
    const entry=assigned(p);
    const hit=entry?.[1].docs.find(item=>sameFile(item,doc));
    if (hit || !entry && sameFile(old[p.pane],doc)) {
      if (hit) choosePage(entry[0],hit.id);
      focus(p);
      return true;
    }
  }
  let id=owner?.mod==="personal-files" ? assigned(owner)?.[0] : null;
  if (!id && owner?.mod==="personal-files" && old[owner.pane])
    id=attachGroup(old[owner.pane],owner);
  if (!id && owner) id=all.find(([,g])=>g.tab===tab && g.anchorPane===owner.pane &&
    (g.pane ? live.some(p=>p.pane===g.pane && p.mod==="personal-files") : Date.now()-g.created<3000))?.[0];
  const page={...doc,id:jobId()};
  if (id) {
    const group=groupState(id);
    const pending=group.docs.find(item=>sameFile(item,doc));
    if (pending) { choosePage(id,pending.id); return true; }
    const next={...group,docs:[...group.docs,page],active:page.id};
    writeGroup(id,next);
    publishActive(next);
    if (next.pane) focus(next);
    return true;
  }
  id=jobId();
  const p={...page,groupId:id,anchorPane:owner?.pane,anchorTab:tab};
  if (owner) {
    run("pane.split",{pane:owner.pane,direction:"right",mod:"personal-files",props:p});
  } else {
    run("tab.new",{space:space.id,name:doc.name,mod:"personal-files",props:p});
  }
  const before=new Set(live.map(item=>item.pane));
  const created=panes().find(item=>!before.has(item.pane) && item.mod==="personal-files" &&
    (owner ? item.tab===tab : spaces().find(s=>s.id===space.id)?.tabs.some(t=>t.id===item.tab)));
  attachGroup(p,created);
  return true;
}

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
  const location=Object.entries(groups()).find(([,g])=>g.pane===pane && g.docs.some(doc=>doc.id===id));
  if (location) {
    const [key,group]=location;
    writeGroup(key,{...group,docs:group.docs.map(doc=>doc.id===id ? {...doc,position} : doc)});
  }
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
      attachGroup(next,pane);
      return true;
    }
    await cx.sleep(50);
  }
  return false;
}

export function openDocument(doc,cx,paneId) {
  const space=spaces().find(s=>s.active);
  if (space) routeDocument(doc,space.id,focused()?.tab,paneId || focused()?.pane);
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
    const entry=Object.entries(groups()).find(([,group])=>group.pane===paneId);
    if (entry && entry[1].docs.length>1) closePage(entry[0],doc.id);
    else if (panes().some(p=>p.pane===paneId && p.tab===source.tab)) run("pane.close",{pane:paneId});
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
  attachGroup(next,created);
  if (side==="left") run("pane.swap",{pane:created.pane,target:anchor.pane});
  const remaining=canMove?panes().filter(p=>p.tab===doc.tab):[];
  if (remaining.length===1 && remaining[0].pane===sourcePanes[0].pane && remaining[0].mod==="personal-files") {
    const entry=Object.entries(groups()).find(([,g])=>g.pane===remaining[0].pane);
    if (entry && entry[1].docs.length>1) closePage(entry[0],doc.id);
    else run("tab.close",{id:doc.tab,confirmed:true});
  }
  run("pane.focus",{pane:created.pane});
  return true;
}
