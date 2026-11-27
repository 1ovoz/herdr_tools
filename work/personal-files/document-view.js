import { View, div, image } from "gpui-kit";
import { v_flex, h_flex, Editor, EditorState, TextView, ScrollHandle } from "gpui-base";
import { theme, settings, props, checking, focused, panes, run, notify, openOverlay } from "herdr";
import { bridge, jobId } from "./actions.js";
import { hitChar, selectedText, selectionRects } from "./pdf-geometry.js";
import { pageFlow, visiblePages, pageAt, restorePosition } from "./document-flow.js";
import { attachGroup, choosePage, closePage, groupState, groupPaneFor, saveDocumentPosition } from "./document-drag.js";

const modes = { ts:"js", tsx:"js", jsx:"js", ps1:"powershell", yml:"yaml", jsonc:"json", md:"markdown", htm:"html" };
const POLL_MS = 2000;
const MIN_ZOOM = 0.5, MAX_ZOOM = 2, ZOOM_STEP = 0.25;
const PAGE_LEFT = 12;
// Pages one helper run renders together, and how far it reads ahead once the screen is complete.
const PAGE_BATCH = 3, PAGE_AHEAD = 2;
// Rendered pages kept after they scroll away. The helper protects their bitmaps for ten minutes.
const PAGE_KEEP = 12, PAGE_KEEP_CHARS = 150000, PAGE_STALE_MS = 480000;
// A visible page that fails is asked again after these waits, then left until zoom, reload or a click.
const PAGE_RETRY_MS = [2000, 8000, 30000];

// Keep fenced code literal. Other blocks use native Markdown without embedded HTML or image requests.
function markdownBlocks(source) {
  const blocks=[], lines=[];
  let marker="", language="";
  function flush() {
    const body=lines.join("\n");
    lines.length=0;
    if (!body.trim()) return;
    if (marker) {
      const longest=(body.match(/~+/g)||[]).reduce((n,s)=>Math.max(n,s.length),2);
      const fence="~".repeat(longest+1);
      blocks.push(fence+language+"\n"+body+"\n"+fence);
    } else {
      blocks.push(body.replace(/</g,"&lt;").replace(/!(?=\[)/g,"&#33;"));
    }
  }
  for (const line of source.split(/\r?\n/)) {
    const match=/^ {0,3}(\x60{3,}|~{3,})(.*)$/.exec(line);
    if (match && !marker) {
      flush(); marker=match[1]; language=/^[\w.+-]+$/.test(match[2].trim())?match[2].trim():"";
    } else if (match && match[1][0]===marker[0] && match[1].length>=marker.length && !match[2].trim()) {
      flush(); marker="";
    } else lines.push(line);
    if (blocks.length>=256) return [...blocks,"Preview limit reached. Select Source to keep reading."];
  }
  flush();
  return blocks;
}

export class DocumentView extends View {
  initDocument(cx) {
    this.groupProps = props() || {};
    this.tabScroll = ScrollHandle.new();
    this.openViews = new Map();
    if (!checking()) this.groupId=attachGroup(this.groupProps,groupPaneFor(this.groupProps));
  }

  syncOpenViews(cx) {
    this.mountPending=false;
    if (!groupState(this.groupId)?.pane) {
      this.groupId=attachGroup(this.groupProps,groupPaneFor(this.groupProps));
    }
    const group=groupState(this.groupId);
    const index=group?.docs.findIndex(doc=>doc.id===group.active) ?? -1;
    const active=group?.docs[index];
    for (const [id,view] of this.openViews) {
      if (!group?.docs.some(doc=>doc.id===id)) {
        this.openViews.delete(id);
        view.release();
      }
    }
    if ((active?.id ?? null)===this.pageId) return;
    if (active) {
      this.page=this.openViews.get(active.id) ||
        cx.new(GroupPage,{...active,groupId:this.groupId,tab:group.tab,pane:group.pane});
      this.openViews.delete(active.id);
      this.openViews.set(active.id,this.page);
      this.tabScroll.scroll_to_item(index);
    } else this.page=null;
    this.pageId=active?.id ?? null;
    if (this.openViews.size>4) {
      const [oldest,view]=this.openViews.entries().next().value;
      this.openViews.delete(oldest);
      view.release();
    }
    cx.notify();
  }

  renderDocument(cx) {
    const t=theme();
    const group=this.groupId && groupState(this.groupId);
    const active=group?.docs.find(doc=>doc.id===group.active);
    const closed=[...(this.openViews?.keys() || [])].some(id=>!group?.docs.some(doc=>doc.id===id));
    if (!checking() && !this.mountPending && (!group?.pane || closed || (active?.id ?? null)!==this.pageId)) {
      this.mountPending=true;
      // A spawned callback starts synchronously. Mount retained pages after this render.
      cx.timer.after(1,task=>this.syncOpenViews(task));
    }
    const select=(doc,closing,event)=>{
      event.stop_propagation();
      if (group.pane) run("pane.focus",{pane:group.pane});
      if (closing) closePage(this.groupId,doc.id);
      else choosePage(this.groupId,doc.id);
    };
    const strip=h_flex().id("pane-file-tabs").w_full().h(32).flex_none().items_center().gap(2)
      .px(4).bg(t.chrome).border_b(1).border_color(t.border).overflow_x_scroll().track_scroll(this.tabScroll);
    for (const doc of group?.docs || []) {
      const selected=doc.id===group.active;
      strip.child(h_flex().id("file-tab-"+doc.id).h(27).flex_none().max_w(210).px(7).gap(5).rounded(4)
        .items_center().cursor_pointer().bg(selected?t.selected:t.chrome).text_color(selected?t.foreground:t.muted)
        .tooltip(doc.source).on_click((_e,c)=>select(doc,false,c))
        .child(div().min_w(0).truncate().text_size(12).child(doc.name))
        .child(div().id("close-file-tab-"+doc.id).w(17).h(19).flex().items_center().justify_center().rounded(3)
          .hover(el=>el.bg(t.hover)).tooltip("Close file").on_click((_e,c)=>select(doc,true,c)).child("×")));
    }
    return v_flex().id("document-group").size_full().min_h(0).bg(t.background).text_color(t.foreground)
      .on_mouse_down("left",()=>{if (group?.pane && focused()?.pane!==group.pane) run("pane.focus",{pane:group.pane});})
      .child(strip).child(div().flex_1().min_h(0).overflow_hidden()
        .when(Boolean(this.page && active?.id===this.pageId),el=>el.child(this.page))
        .when(!active,el=>el.child(div().p(12).text_color(t.muted).child("Open a file from Files"))));
  }

  initPage(p,cx) {
    this.document = { source:p.source, on:p.on ?? null, mode:p.mode ?? "pdf" };
    this.transfer = p.transfer ?? true;
    this.documentId = p.id;
    this.groupId = p.groupId;
    this.viewerPane = p.pane;
    this.viewerTab = p.tab;
    this.isPicture=/\.(?:png|jpe?g)$/i.test(p.source || "");
    this.isHtml=/\.html?$/i.test(p.source || "");
    this.width = 850;
    this.height = 720;
    this.zoom = p.position?.zoom ?? 1;
    this.pendingPosition = p.position;
    this.scroll = { x:0, y:0 };
    this.pages = new Map();
    this.sizes = [];
    this.requestVersion = 0;
    this.renderingPage = false;
    this.failed = new Map();
    this.docFocus = cx.focus_handle();
    if (checking() || !p.source) return;
    this.checkForChanges(cx);
    cx.timer.every(POLL_MS, tick => { if (this.isShown()) this.checkForChanges(tick); });
  }

  isShown() {
    if (this.groupId && groupState(this.groupId)?.active!==this.documentId) return false;
    const id = focused()?.tab;
    if (this.viewerTab) return id === this.viewerTab;
    return true;
  }

  request(action, fields={}) {
    const {source,on} = this.document;
    return bridge({action,source,on,job:jobId(),...fields}).then(result => {
      if (!result.ok) throw Object.assign(new Error(result.error || "File preview failed"),{code:result.code});
      return result;
    });
  }

  checkForChanges(cx) {
    const now=Date.now();
    if (this.checkingFile || !this.document?.source || now<this.nextPoll) return;
    const afterIdle=now-(this.lastPoll || now)>300000;
    this.lastPoll=now;
    this.checkingFile = true;
    cx.spawn(async task => {
      const previousWarning=this.documentWarning;
      let refreshed=false;
      try {
        if (this.revision || this.isHtml) {
          const revision = (await this.request("revision")).revision.join(":");
          const unchanged=revision===this.revision;
          // The browser can still display a file when its source cannot be read as text.
          if (this.isHtml && !unchanged) {
            this.revision=revision;
            this.queueHtmlPreview(task);
          }
          if (unchanged && !(this.isHtml && this.documentWarning)) {
            this.pollDelay=Math.min(16000,(this.pollDelay || POLL_MS)*2);
            this.documentWarning = null;
            // The file is unchanged, but cached bitmaps expire while a tab is away: ask again for what is shown.
            if (this.document.mode === "pdf") this.queuePages(task);
            else if (this.isPicture && afterIdle) { this.picture=await this.request("image"); refreshed=true; }
            else if (this.isHtml && afterIdle) { this.htmlAttemptKey=null; this.queueHtmlPreview(task); }
            return;
          }
        }
        if (this.document.mode === "pdf") await this.readPdf(task);
        else if (this.isPicture) {
          this.picture=await this.request("image");
          this.revision=this.picture.revision.join(":");
        }
        else await this.readText();
        refreshed=true;
        this.pollDelay=POLL_MS;
        this.documentWarning = null;
      } catch (error) {
        this.pollDelay=16000;
        this.documentWarning = String(error).replace(/^Error:\s*/, "");
      } finally {
        this.nextPoll=Date.now()+this.pollDelay;
        this.checkingFile = false;
        if(refreshed || previousWarning!==this.documentWarning) task.notify();
      }
    });
  }

  async readText() {
    const {text,revision,html}=await this.request("text").catch(error=>{
      if (this.isHtml) {
        this.code?.release();
        this.code=null;
        this.html=null;
      }
      throw error;
    });
    this.html = html ?? null;
    this.revision=revision.join(":");
    if (text === null || text.includes("\0")) {
      this.markdown=null;
      this.code?.release();
      this.code = null;
      this.textStatus = "Preview unavailable for this file. Use Download to open it.";
      return;
    }
    const ext = this.document.source.split('.').pop().toLowerCase();
    const t = theme();
    const displayed=text.length>400000 ? text.slice(0,400000)+"\n… (file truncated)" : text;
    this.markdown=["md","markdown","mdown"].includes(ext) ? markdownBlocks(displayed) : null;
    const next = EditorState.new({language:modes[ext] || ext,readonly:true,font_family:settings().font_family,font_size:12,
      value:displayed,
      syntax:{keyword:t.ansi5,string:t.ansi2,comment:t.dim,function:t.ansi4,type:t.ansi3,number:t.ansi1,constant:t.ansi6}});
    this.code?.release();
    this.code = next;
    this.textStatus = null;
  }

  htmlViewport() {
    if (!this.htmlSize || !this.htmlSize.width || !this.htmlSize.height) return null;
    const zoom=Number(settings().zoom) || 1;
    const width=Math.max(1,Math.round(this.htmlSize.width/zoom));
    const height=Math.max(1,Math.round(this.htmlSize.height/zoom));
    return {width,height,key:[width,height,this.revision].join("/")};
  }

  queueHtmlPreview(cx) {
    const viewport=this.htmlViewport();
    if (!viewport || this.showSource || this.htmlCapturing) return;
    const {width,height,key}=viewport;
    if (key===this.htmlTimerKey) return;
    this.htmlTimer?.cancel();
    this.htmlTimer=null;
    this.htmlTimerKey=null;
    if (key===this.htmlAttemptKey) return;
    this.htmlTimerKey=key;
    this.htmlTimer=cx.timer.after(220,tick=>{
      this.htmlTimerKey=null;
      this.htmlTimer=null;
      if (this.showSource || !this.isShown() || this.htmlViewport()?.key!==key) return;
      this.htmlAttemptKey=key;
      this.htmlCapturing=true;
      tick.spawn(async task=>{
        try {
          const frame=await this.request("html-preview",{width,height});
          const latest=this.htmlViewport();
          // Source may finish loading during the capture. Accept a matching revision and layout only.
          if (latest?.width===width && latest.height===height &&
              (!this.revision || frame.revision.join(":")===this.revision)) {
            this.htmlFrame=frame;
            this.htmlError=null;
            this.htmlAttemptKey=latest.key;
          }
        } catch (error) {
          if (this.htmlViewport()?.key===key) {
            this.htmlError=String(error).replace(/^Error:\s*/,"");
            this.htmlFrame=null;
          }
        } finally {
          this.htmlCapturing=false;
          task.notify();
        }
      });
    });
  }

  openHtml(cx) {
    if (this.openingHtml) return;
    this.openingHtml=true;
    cx.spawn(async task=>{
      try { await this.request("html-open"); }
      catch (error) { notify({title:"Could not open HTML in browser",body:String(error),level:"warning"}); }
      finally { this.openingHtml=false; task.notify(); }
    });
  }

  htmlPreview(cx,t) {
    this.queueHtmlPreview(cx);
    const body=v_flex().id("html-preview").flex_1().min_h(0).w_full().overflow_y_scrollbar()
      .on_size_change((size,task)=>{
        this.htmlSize=size;
        this.queueHtmlPreview(task);
      });
    const frame=this.htmlFrame;
    if (frame) {
      const width=this.htmlViewport()?.width || frame.width;
      return body.child(image(frame.image).w(width).h(width*frame.height/frame.width).flex_none())
        .when(frame.truncated,el=>el.child(div().p(8).text_color(t.muted).child("Open in browser to see the rest of this page.")));
    }
    if (!this.htmlError) return body.child(div().p(12).text_color(t.muted).child("Rendering HTML preview…"));
    return body.px(18).py(12).gap(8)
      .child(div().text_color(t.muted).child("Browser preview unavailable. "+this.htmlError))
      .when(Boolean(this.html),el=>el.child(TextView.html("html-body",this.html).selectable(true).scrollable(false).w_full()));
  }

  flow() {
    const scale = Number(settings().zoom) || 1;
    return pageFlow(this.sizes,this.width/scale,Math.max(80,this.height/scale-106),this.zoom);
  }

  anchor(y = this.scroll.y) {
    const flow = this.flow();
    const index = pageAt(flow,y);
    const page = flow.pages[index];
    return [index,page ? (y-page.top)/page.height : 0];
  }

  async readPdf(task) {
    const [index,fraction] = this.pendingPosition?.anchor || this.anchor();
    const width = this.rasterWidth();
    const value = await this.request("preview",{page:index,width,sizes:true});
    this.requestVersion++;
    this.revision = value.revision.join(":");
    this.cachedPdf = value.pdf;
    this.sizes = value.sizes;
    this.pages = new Map([[value.page,{...value,rasterWidth:width,at:Date.now()}]]);
    this.failed = new Map();
    this.selection = null;
    this.scroll.y = index || fraction > 0 ? restorePosition(this.flow(),index,fraction) : 0;
    this.pendingPosition = null;
    this.queuePages(task);
  }

  rasterWidth(flow = this.flow()) {
    const appZoom = Number(settings().zoom) || 1;
    // Render at 2x display size. Buckets let nearby pane sizes reuse the same bitmap.
    const pixels = Math.max(1100*this.zoom, flow.pageWidth*appZoom*2);
    return Math.min(4096, Math.ceil(pixels/128)*128);
  }

  queuePages(cx) {
    if (this.renderingPage || !this.sizes.length) return;
    const flow = this.flow(), width = this.rasterWidth(flow), now = Date.now();
    const failed = this.failed ||= new Map();
    const wanted = i => {
      const miss = failed.get(i), data = this.pages.get(i);
      if (miss && now < miss.until) return false;
      return !data || data.rasterWidth < width || now-data.at > PAGE_STALE_MS;
    };
    const visible = visiblePages(flow,this.scroll.y);
    const center = this.scroll.y+flow.viewportHeight*.35;
    visible.sort((a,b)=>Math.abs(flow.pages[a].top-center)-Math.abs(flow.pages[b].top-center));
    // Every page missing from the screen goes into one helper run, nearest the reading position first.
    let batch = visible.filter(wanted).slice(0,PAGE_BATCH);
    if (!batch.length && this.isShown()) {
      // The screen is complete: read one page ahead in the direction of travel, so it is ready on arrival.
      const step = this.scrollDirection || 1;
      const edge = step > 0 ? Math.max(...visible) : Math.min(...visible);
      // A dense page can be evicted as soon as it arrives. Read ahead only once at each edge.
      const edgeKey = [this.requestVersion, width, edge, step].join("/");
      if (this.prefetchEdge !== edgeKey) {
        this.prefetchEdge = edgeKey;
        this.prefetchDistance = 0;
      }
      while (this.prefetchDistance < PAGE_AHEAD && !batch.length) {
        const i = edge + step * ++this.prefetchDistance;
        if (i >= 0 && i < this.sizes.length && wanted(i)) batch = [i];
      }
    }
    if (!batch.length) {
      const retry = Math.min(...visible.map(i=>failed.get(i)?.until ?? Infinity));
      if (Number.isFinite(retry) && !this.retryTimer) {
        this.retryTimer = cx.timer?.after(Math.max(250,retry-now),task=>{ this.retryTimer = null; this.queuePages(task); });
      }
      return;
    }
    const version = this.requestVersion;
    this.renderingPage = true;
    cx.spawn(async task => {
      try {
        const remote = this.document.on !== null;
        const asked = batch.map(i=>!this.pages.get(i)?.chars);
        const fields = {pages:batch,width,chars:asked};
        let result;
        try {
          result=await this.request(remote ? "render" : "preview",{source:this.cachedPdf,on:null,...fields});
        } catch (error) {
          if (!remote || error.code!=="cache_miss") throw error;
          result=await this.request("preview",fields);
          if (version===this.requestVersion && result.revision.join(":")!==this.revision) {
            await this.readPdf(task); return;
          }
        }
        if (version !== this.requestVersion) return;
        const rendered = remote || result.revision?.join(":")===this.revision ? result.rendered || [] : [];
        const at = Date.now();
        for (const page of rendered) {
          const previous = this.pages.get(page.page);
          const chars = asked[batch.indexOf(page.page)] ? page.chars : previous?.chars ?? page.chars;
          this.pages.set(page.page,{...page,chars:chars || [],rasterWidth:width,at});
          failed.delete(page.page);
        }
        // A reply may stop early at its text budget; those pages are simply asked for again.
        if (!rendered.length) this.failPages(batch);
        this.trimPages();
      } catch (error) {
        if (version === this.requestVersion) {
          this.failPages(batch);
          this.documentWarning=String(error);
        }
      } finally {
        this.renderingPage=false;
        task.notify();
        this.queuePages(task);
      }
    });
  }

  failPages(pages) {
    const now = Date.now(), failed = this.failed ||= new Map();
    const shown = new Set(visiblePages(this.flow(),this.scroll.y));
    for (const i of pages) {
      // A page read ahead waits until it is on screen. A visible one is retried a few times, further apart.
      const count = shown.has(i) ? (failed.get(i)?.count || 0)+1 : 0;
      const wait = count ? PAGE_RETRY_MS[count-1] : 15000;
      failed.set(i,{count,until:wait === undefined ? Infinity : now+wait});
    }
  }

  // Pages scrolled out of view stay known, so scrolling back starts no helper. The farthest go first.
  trimPages() {
    const flow = this.flow();
    const shown = new Set(visiblePages(flow,this.scroll.y));
    const here = pageAt(flow,this.scroll.y);
    const spare = [...this.pages.keys()].filter(i=>!shown.has(i)).sort((a,b)=>Math.abs(b-here)-Math.abs(a-here));
    let chars = 0;
    for (const data of this.pages.values()) chars += data.chars?.length || 0;
    for (const i of spare) {
      if (this.pages.size <= PAGE_KEEP && chars <= PAGE_KEEP_CHARS) break;
      chars -= this.pages.get(i).chars?.length || 0;
      this.pages.delete(i);
    }
  }

  moveTo(x,y,cx) {
    const flow = this.flow();
    const next = {x:Math.max(0,Math.min(flow.maxX,x)),y:Math.max(0,Math.min(flow.maxY,y))};
    if (next.y !== this.scroll.y) this.scrollDirection = next.y > this.scroll.y ? 1 : -1;
    this.scroll = next;
    this.queuePages(cx);
    if (this.viewerPane && this.sizes.length) {
      this.savePositionTimer?.cancel();
      this.savePositionTimer=cx.timer.after(120,()=>{
        if(this.viewerTab)saveDocumentPosition(this.viewerTab,this.viewerPane,this.documentId,{anchor:this.anchor(),zoom:this.zoom});
      });
    }
    cx.notify();
  }

  changeZoom(zoom,cx,point) {
    const next = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoom));
    if (next === this.zoom) return;
    const appZoom = Number(settings().zoom) || 1;
    const offsetY = (point?.y ?? 0)/appZoom;
    const [index,fraction] = this.anchor(this.scroll.y + offsetY);
    let x = this.scroll.x;
    if (point) {
      const offsetX = point.x/appZoom - PAGE_LEFT;
      x = (x + offsetX)*next/this.zoom - offsetX;
    }
    this.zoom = next;
    this.failed = new Map();
    this.moveTo(x,restorePosition(this.flow(),index,fraction,offsetY),cx);
  }

  jump(index,cx) {
    this.moveTo(this.scroll.x,restorePosition(this.flow(),Math.max(0,index),0),cx);
  }

  wheel(event,cx) {
    cx.stop_propagation();
    if (event.modifiers?.control) {
      const dy = (event.delta_lines ?? event.delta).y;
      if (dy) this.changeZoom(this.zoom + Math.sign(dy)*ZOOM_STEP,cx,event.local_position);
      return;
    }
    const appZoom = Number(settings().zoom)||1;
    const delta = event.delta_lines ? { x:event.delta_lines.x*28,y:event.delta_lines.y*28 } : event.delta;
    const sideways = event.modifiers?.shift && !delta.x;
    this.moveTo(this.scroll.x-(sideways?delta.y:delta.x)/appZoom,
      this.scroll.y-(sideways?0:delta.y)/appZoom,cx);
  }

  point(event,strict) {
    const point=event.local_position;
    if (!point) return null;
    const scale=Number(settings().zoom)||1, flow=this.flow();
    const y=point.y/scale+this.scroll.y, index=pageAt(flow,y), page=flow.pages[index];
    const data=this.pages.get(index);
    if (!page || !data) return null;
    const x=(point.x/scale+this.scroll.x-PAGE_LEFT)/page.width;
    const row=(y-page.top)/page.height;
    if (strict && (x<0 || x>1 || row<0 || row>1)) return null;
    const char=hitChar(data.chars,x,row,strict);
    return char<0 ? null : {index,char};
  }

  startSelection(event,cx) {
    if (this.viewerPane && focused()?.pane!==this.viewerPane) run("pane.focus",{pane:this.viewerPane});
    this.docFocus?.focus();
    // A click on the page also retries pages that stopped loading.
    if (this.failed?.size) { this.failed = new Map(); this.queuePages(cx); }
    const start=this.point(event,true);
    this.selecting=Boolean(start);
    this.selection=start ? {start,end:start} : null;
    cx.stop_propagation();
    cx.notify();
  }

  extendSelection(event,cx) {
    if (!this.selecting) return;
    const end=this.point(event,false);
    if (end && this.selection && (end.index!==this.selection.end.index || end.char!==this.selection.end.char)) {
      this.selection.end=end;
      cx.notify();
    }
  }

  range(index) {
    if (!this.selection) return null;
    let {start,end}=this.selection;
    if (start.index>end.index) [start,end]=[end,start];
    if (index < start.index || index > end.index) return null;
    return [index===start.index ? start.char : 0,index===end.index ? end.char : (this.pages.get(index)?.chars.length||0)-1];
  }

  copyDocumentText(cx) {
    if (!this.selection) return;
    const {start,end}=this.selection, chunks=[];
    for(let index=Math.min(start.index,end.index);index<=Math.max(start.index,end.index);index++) {
      const data=this.pages.get(index), range=this.range(index);
      if (!data || !range) continue;
      const text=selectedText(data.chars,...range);
      if (text) chunks.push(text);
    }
    if (chunks.length) cx.write_to_clipboard(chunks.join("\n"));
  }

  keyDocument(event,cx) {
    const key=event.key?.toLowerCase();
    if(event.modifiers?.control && key==='c') { this.copyDocumentText(cx);cx.stop_propagation();return; }
    const g=this.flow();
    const delta={pagedown:g.viewportHeight*.85,pageup:-g.viewportHeight*.85,down:45,up:-45}[key];
    if(delta || key==='home' || key==='end') {
      this.moveTo(this.scroll.x,key==='home'?0:key==='end'?g.maxY:this.scroll.y+delta,cx);
      cx.stop_propagation();
    }
  }

  pageImage(index, page, t) {
    const left=PAGE_LEFT-this.scroll.x, top=page.top-this.scroll.y;
    const data=this.pages.get(index);
    const el=div().id(`doc-page-${index}`).absolute().left(left).top(top).w(page.width).h(page.height).bg("#ffffff");
    if (!data) return el.child(div().px(10).py(6).text_color("#606060").child(`Page ${index+1}`));
    const range=this.range(index);
    return el.child(image(data.image).absolute().inset_0().w(page.width).h(page.height))
      .children((range?selectionRects(data.chars,...range):[]).map(r=>div().absolute().left(r[0]*page.width).top(r[1]*page.height)
        .w((r[2]-r[0])*page.width).h(Math.max(2,(r[3]-r[1])*page.height)).bg("#60a5fa66")));
  }

  renderPage(cx) {
    const t=theme(), {source,on,mode}=this.document;
    const isPdf=mode==="pdf", caption=source?.split(/[\\/]/).pop()||"Document";
    const g=this.flow(), index=pageAt(g,this.scroll.y+1), data=this.pages.get(index);
    const hasHtml = this.isHtml;
    const hasPreview = hasHtml || Boolean(this.markdown);
    const compact=g.viewportWidth<320;
    const narrow=g.viewportWidth<205;
    const picture=this.picture;
    const scale=picture ? Math.max(0.01,Math.min(1,(g.viewportWidth-16)/picture.width,
      (this.height/(Number(settings().zoom)||1)-58)/picture.height)) : 1;
    return v_flex().id("file-document").size_full().min_h(0).bg(t.background).text_color(t.foreground).text_size(13)
      .on_size_change((size,cx)=>{
        if(this.width===size.width && this.height===size.height)return;
        const anchor=this.anchor();this.width=size.width;this.height=size.height;
        this.moveTo(this.scroll.x,restorePosition(this.flow(),...anchor),cx);
      })
      .track_focus(this.docFocus).on_key_down((e,cx)=>{if(isPdf)this.keyDocument(e,cx);})
      .child(h_flex().h(42).flex_none().px(10).gap(5).items_center().bg(t.chrome)
        .child(div().flex_1().min_w(0).truncate().font_semibold().child(caption))
        .when(hasPreview,el=>el.child(this.button(hasHtml?"html-toggle":"markdown-toggle",this.showSource?"Preview":"Source",cx=>{
          this.showSource=!this.showSource;
          if (!this.showSource && this.htmlError) this.htmlAttemptKey=null;
          cx.notify();
        })))
        .when(hasHtml,el=>el.child(this.button("html-open",compact?"Browser":"Open in browser",cx=>this.openHtml(cx))
          .flex_none().tooltip("Open in browser")))
        .when(!compact,el=>el.child(this.button("document-download","Download",()=>this.job([{action:"download",source,on,job:jobId()}]),!source)))
        .when(isPdf && !compact,el=>el.child(this.button("pdf-copy","Copy text",cx=>this.copyDocumentText(cx),!this.selection)))
        )
      .when(hasHtml && !this.showSource,el=>el.child(this.htmlPreview(cx,t)))
      .when(!isPdf && this.markdown && !this.showSource,el=>el.child(v_flex().id("markdown-preview").flex_1().min_h(0)
        .overflow_y_scrollbar().px(18).py(12).gap(8).children(this.markdown.map((block,i)=>
          TextView.markdown("markdown-block-"+i,block).selectable(true).scrollable(false).w_full()
            .on_link_click((url,cx)=>{if (/^https?:\/\/[^\s\\/]+(?:[/?#]|$)/i.test(url)) cx.open_url(url);})))) )
      .when(this.isPicture,el=>el.child(div().flex_1().min_h(0).flex().items_center().justify_center()
        .child(picture && !this.documentWarning ? image(picture.image).w(picture.width*scale).h(picture.height*scale)
          : div().text_color(t.dim).child(this.documentWarning||"Loading image…"))))
      .when(!isPdf && !this.isPicture && (!hasPreview || this.showSource),el=>el.child(this.code ? Editor.new(this.code).flex_1().min_h(0)
        : div().p(12).text_color(t.dim).child(this.documentWarning||this.textStatus||"Loading file…")))
      .when(isPdf,el=>el
        .child(h_flex().h(40).flex_none().px(9).gap(4).items_center().bg(t.surface)
          .child(this.button("pdf-prev",compact?"‹":"‹ Prev",cx=>this.jump(index-1,cx),index===0))
          .child(div().text_color(t.muted).child(this.sizes.length?`${index+1} / ${this.sizes.length}`:"PDF"))
          .child(this.button("pdf-next",compact?"›":"Next ›",cx=>this.jump(index+1,cx),index>=this.sizes.length-1))
          .child(div().flex_1())
          .when(!narrow,bar=>bar
            .child(this.button("pdf-zoom-out","−",cx=>this.changeZoom(this.zoom-ZOOM_STEP,cx),this.zoom<=MIN_ZOOM))
            .child(this.button("pdf-fit",`${Math.round(this.zoom*100)}%`,cx=>this.changeZoom(1,cx)))
            .child(this.button("pdf-zoom-in","+",cx=>this.changeZoom(this.zoom+ZOOM_STEP,cx),this.zoom>=MAX_ZOOM))))
        .child(div().id("pdf-scroll").relative().h(g.viewportHeight).flex_none().w_full().overflow_hidden()
          .on_scroll_wheel((event,cx)=>this.wheel(event,cx))
          .on_mouse_down("left",(event,cx)=>this.startSelection(event,cx))
          .on_mouse_move((event,cx)=>this.extendSelection(event,cx))
          .on_mouse_up("left",(event,cx)=>{this.extendSelection(event,cx);this.selecting=false;cx.stop_propagation();})
          .on_hover(hovered=>{if(!hovered)this.selecting=false;})
          .children(visiblePages(g,this.scroll.y).map(i=>this.pageImage(i,g.pages[i],t)))
          .when(g.maxY>0,view=>view.child(div().absolute().right(2).top(2+this.scroll.y/g.maxY*Math.max(0,g.viewportHeight-50)).w(5).h(46).rounded(3).bg(t.muted))))
        .child(div().h(24).flex_none().px(12).text_size(11).truncate().text_color(this.documentWarning?t.blocked:t.muted)
          .child(this.documentWarning||(!data?"Loading PDF…":data.chars.some(item=>item.r)?"Drag to select text · Ctrl+C to copy":"No text layer on this page"))));
  }
}

// Each retained page owns its timers, editor and bitmaps. Hidden pages skip
// polling and are released on close or when evicted from the pane's four recent views.
class GroupPage extends DocumentView {
  init(p,cx) { this.initPage(p,cx); }
  render(cx) { return this.renderPage(cx); }
  button(id,label,action,disabled=false) {
    const t=theme();
    return div().id(id).px(9).py(5).rounded(5).text_color(disabled?t.dim:t.foreground)
      .cursor_pointer().hover(el=>el.bg(disabled?t.surface:t.hover))
      .on_click((_e,cx)=>{if (!disabled) action(cx);}).child(label);
  }
  job(requests) {
    openOverlay({mod:"personal-files",kind:"dialog",width:520,height:300,props:{mode:"job",requests}});
  }
}
