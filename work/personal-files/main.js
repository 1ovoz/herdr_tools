// A lazy file browser for the focused pane's folder, with bounded read-only previews.
import { div, svg } from "gpui-kit";
import { v_flex, h_flex, Button, Editor, EditorState, Input, InputState } from "gpui-base";
import { spaces, panes, focused, exec, readTextFile, writeTextFile, watchFolder, theme, settings, window, props, checking, appHome, openOverlay, closeOverlay, shared, setShared, run, layout, notify } from "herdr";
import { bridge, jobId, uploadRequests } from "./actions.js";
import { DocumentView } from "./document-view.js";
import { dropSide } from "./document-flow.js";
import { fileDocument, openDocument, movement, startDocumentDrag, splitDocument, liftPane } from "./document-drag.js";

function location() {
  if (props()?.folder) return { cwd: props().folder, on: props().on ?? null, space: "pinned" };
  const space = spaces().find(s => s.active), f = focused();
  const pane = f?.pane ? panes().find(p => p.pane === f.pane) : null;
  const on = f?.pane === null ? (f.terminal?.includes("/") ? f.terminal.split("/")[0] : null) : space?.machine ?? null;
  const nearby = pane?.mod ? panes().find(candidate=>candidate.tab===pane.tab && candidate.terminal && candidate.cwd) : null;
  return { cwd: pane?.cwd || f?.cwd || nearby?.cwd || space?.folder, on, space: space?.id };
}
const key = () => JSON.stringify(location());
const LANG = { ts: "js", tsx: "js", mts: "js", cts: "js", jsx: "js", mjs: "js", toml: "yaml", jsonc: "json", svelte: "html", vue: "html" };
const PER_FOLDER = 500, TOTAL = 5000;
// Listing starts programs, so reported changes wait this long after the last listing.
const MIN_REFRESH_MS = 2000;
// The whole tree is read again at these intervals: on another machine, while its listing keeps changing or
// has been steady; on this computer, with or without a working folder watch; and when the window is inactive.
const REMOTE_MS = 10000, REMOTE_QUIET_MS = 30000, WATCHED_MS = 60000, UNWATCHED_MS = 10000, INACTIVE_MS = 60000;
const GIT_ONLY = "\0git";
// Programs a repository's own config can make `git status` run.
const GIT_COMMAND_KEYS = "^(filter\\..*\\.(clean|smudge|process)|core\\.fsmonitor)$";
const CHANGE_DIALOG_HEIGHT = 210, JOB_DIALOG_HEIGHT = 300;
const CLIPBOARD = "personal-files.clipboard";
const TRUSTED = "personal-files.trusted-repositories";
const FILE_ACTIONS = [
  {id:"open-side", label:"Open to the Side", feature:"pdf", key:"ctrl-enter", hint:"Ctrl+Enter"},
  {id:"cut", label:"Cut", feature:"transfer", key:"ctrl-x", hint:"Ctrl+X"},
  {id:"copy", label:"Copy", feature:"transfer", key:"ctrl-c", hint:"Ctrl+C"},
  {id:"download", label:"Download…", feature:"transfer"},
  {id:"copy-path", label:"Copy Path", feature:"transfer", key:"alt-shift-c", hint:"Shift+Alt+C"},
  {id:"copy-relative", label:"Copy Relative Path", feature:"transfer", key:"ctrl-k ctrl-shift-c", hint:"Ctrl+K, Ctrl+Shift+C"},
  {id:"rename", label:"Rename…", feature:"transfer", key:"f2", hint:"F2"},
  {id:"delete", label:"Delete Permanently…", feature:"transfer", key:"delete", hint:"Del"},
  {id:"view-file", label:"Open in tab", feature:"pdf"},
  {id:"view-split-left", label:"Open left", feature:"pdf"},
  {id:"download-open", label:"Download & Open", feature:"transfer"},
];
const PASTE = {id:"paste", label:"Paste", feature:"transfer", key:"ctrl-v", hint:"Ctrl+V"};
const OPEN_DOWNLOADS = {id:"open-downloads", label:"Open Downloads folder", feature:"transfer"};

function menuTarget(root, on, relative, dir, name) {
  const windows = /^[A-Za-z]:[\\/]|^\\\\/.test(root) ||
    (!on && root.startsWith("//") && window()?.platform === "windows");
  const path = windows ? relative.replace(/\//g,"\\") : relative;
  const base = windows ? root.replace(/\//g,"\\").replace(/\\+$/, "") : root.replace(/\/+$/, "");
  return {root, on, path:relative, relative:path, source:relative ? base + (windows ? "\\" : "/") + path : root, dir, name};
}

function findNode(node,id) {
  if (node?.id === id) return node;
  for (const item of node?.children || []) {
    const found=findNode(item,id);
    if(found)return found;
  }
  return null;
}

let systemPowerShell = "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe";

async function windowsDirectory(path, on) {
  // Windows PowerShell otherwise uses the console code page; exec decodes UTF-8.
  // Links keep directory attributes even when dangling; check their target.
  // Other reparse points (OneDrive's folders) have no LinkType and are folders.
  const args = ["-NoProfile", "-Command", "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); & { @(Get-ChildItem -LiteralPath . -Force -ErrorAction Stop | Where-Object Name -ne '.git' | Select-Object -First 501 | ForEach-Object { @{ name=$_.Name; dir=($_.PSIsContainer -and (-not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -or -not $_.LinkType -or ($_.Target -and [IO.Directory]::Exists(([IO.Path]::Combine([IO.Path]::GetDirectoryName($_.FullName), $_.Target[0])))))) } }) | ConvertTo-Json -Compress }"];
  let r = null;
  // The listed folder is the working directory, so on this computer the system's own PowerShell is named in full.
  if (!on && systemPowerShell) {
    try { r = await exec(systemPowerShell, args, { cwd:path }); }
    catch { r = null; }
  }
  if (!r) {
    r = await exec("powershell", args, { on, cwd:path });
    if (!on) systemPowerShell = null;
  }
  if (r.code !== 0) throw new Error(r.stderr || "Cannot list this folder");
  const result = JSON.parse(r.stdout || "[]");
  return Array.isArray(result) ? result : [result];
}

// Lists several folders in one program. Each answer is the folder's entries, null when it is not a folder,
// or the error that stopped its listing.
async function listFolders(paths, on) {
  const each = async () => {
    const out = [];
    for (const path of paths) out.push(await windowsDirectory(path, on).catch(error => error instanceof Error ? error : new Error(String(error))));
    return out;
  };
  if (!on && window()?.platform === "windows") return each();
  const script = 'for d in "$@"; do if [ -d "$d" ]; then printf "D\\0%s\\0" 1; else printf "D\\0%s\\0" 0; continue; fi; n=0; for p in "$d"/* "$d"/.[!.]* "$d"/..?*; do [ -e "$p" ] || [ -L "$p" ] || continue; name=${p##*/}; [ "$name" = .git ] && continue; if [ -d "$p" ]; then kind=d; else kind=f; fi; printf "%s\\0%s\\0" "$kind" "$name"; n=$((n+1)); [ "$n" -gt 500 ] && break; done; done; exit 0';
  const out = [];
  for (let first = 0; first < paths.length; first += 40) {
    const group = paths.slice(first, first + 40);
    let r;
    try { r = await exec("sh", ["-c", script, "files", ...group], { on }); }
    catch (e) {
      if (on && String(e).includes("cannot start sh: program not found")) return each();
      throw e;
    }
    if (r.code !== 0) throw new Error(r.stderr || "Cannot list this folder");
    const fields = r.stdout.split("\0"), found = [];
    for (let i = 0; i + 1 < fields.length; i += 2) {
      if (fields[i] === "D") found.push(fields[i + 1] === "1" ? [] : null);
      else found.at(-1)?.push({ name: fields[i + 1], dir: fields[i] === "d" });
    }
    if (found.length !== group.length) throw new Error("Cannot list this folder");
    out.push(...found);
  }
  return out;
}

// The shown folders a batch of changed paths touches: "" is the root. Null means read everything again.
function changedFolders(paths, root, expanded) {
  const tidy = value => value.replace(/\\/g, "/").replace(/\/+$/, "");
  const windows = /^[A-Za-z]:(?:\/|$)|^\/\//.test(tidy(root));
  const fold = value => windows ? value.toLowerCase() : value;
  const base = fold(tidy(root));
  const shown = new Map([["", ""], ...[...expanded].map(folder => [fold(folder), folder])]);
  const out = new Set();
  for (const raw of paths) {
    const path = fold(tidy(String(raw)));
    if (path === base || !path.startsWith(base + "/")) return null;
    const relative = path.slice(base.length + 1);
    if (relative === ".git" || relative.startsWith(".git/")) { out.add(GIT_ONLY); continue; }
    const slash = relative.lastIndexOf("/"), parent = slash < 0 ? "" : relative.slice(0, slash);
    if (shown.has(parent)) out.add(shown.get(parent));
    if (shown.has(relative)) out.add(shown.get(relative));
  }
  return out;
}

// A repository's config can name programs that `git status` would run. Listing a folder must not run what the
// folder supplies, so its marks are skipped. Config from the account and the system is the person's own.
async function repositoryRunsPrograms(cwd, on) {
  const ask = flags => exec("git", ["config", ...flags, "-z", "--get-regexp", GIT_COMMAND_KEYS], { cwd, on });
  try {
    const scoped = await ask(["--show-scope"]);
    if (scoped.code === 0) {
      const fields = scoped.stdout.split("\0");
      for (let i = 0; i + 1 < fields.length; i += 2) if (!["system", "global", "command"].includes(fields[i])) return true;
      return false;
    }
    if (scoped.code === 1) return false;
    if (scoped.code !== 129) return true;
    // Git before 2.26 cannot report scopes: ask for the repository's own config instead.
    return (await ask(["--local", "--includes"])).code !== 1;
  } catch { return true; }
}

function nodePath(node, id, trail = []) {
  if (!node) return null;
  const here = [...trail, node];
  if (node.id === id) return here;
  for (const child of node.children || []) {
    const found = nodePath(child, id, here);
    if (found) return found;
  }
  return null;
}

export default class Files extends DocumentView {
  init(_props, cx) {
    this.mode = props()?.mode;
    this.transfer = true;
    this.pdf = true;
    this.busy = false;
    if (this.mode === "menu") {
      this.treeFocus = cx.focus_handle();
      this.treeFocus.focus();
      return;
    }
    if (this.mode === "rename" || this.mode === "delete") {
      if (this.mode === "rename") {
        const name = props().target.name;
        this.nameInput = InputState.new({value:name});
        this.nameInput.on("submit", (_e,task)=>this.submitChange(task));
        this.nameInput.focus();
        const dot = name.lastIndexOf(".");
        this.nameInput.set_selected_range({start:0,end:dot > 0 ? dot : name.length});
      }
      return;
    }
    if (this.mode === "job") {
      this.queue = props().requests || []; this.index = 0;
      if (!checking()) {
        this.work(cx);
        cx.timer.every(1000, cx => this.pollProgress(cx));
      }
      return;
    }
    if (this.mode === "pdf" || this.mode === "document" || this.mode === "group") { this.initDocument(cx); return; }
    if (this.mode === "drop" || this.mode === "lift") {
      this.dropWidth=1280;this.dropHeight=800;
      this.dropFocus=cx.focus_handle();this.dropFocus.focus();
      cx.timer.after(8000,()=>this.cancelDrop());
      if (props()?.side) cx.timer.after(1,tick=>this.finishDrop(props().side,tick));
      return;
    }
    this.saved = new Map();
    this.treeFocus = cx.focus_handle();
    const bindings = this.shortcuts().map(a=>({
      keystroke:a.key, action:"personal-files-" + a.id, context:this.keyContext()
    }));
    if (bindings.length) cx.bind_keys(bindings);
    this.entries = new Map(); this.folders = new Set(); this.pending = new Set(); this.marks = {};
    this.dropFolder = null;
    if (!checking()) {
      this.refresh(cx);
      cx.timer.every(10000, cx => this.tick(cx));
    }
  }

  // False while the Files block is hidden, or another panel is in front of it.
  shown() {
    try {
      if (props()?.folder) return true;
      const path = nodePath(layout(), "files");
      if (!path || path.at(-1).content?.mod !== "personal-files") return true;
      return path.every((node, i) => !node.hidden &&
        !(node.type === "stack" && node.active && path[i + 1] && node.active !== path[i + 1].id));
    } catch { return true; }
  }

  // The fallback for changes no watch reports. Nothing is read while the panel is out of sight.
  tick(cx) {
    if (!this.shown()) { this.stale = true; return; }
    if (key() !== this.context?.key) { this.refresh(cx); return; }
    let every = this.on ? (this.quiet >= 6 ? REMOTE_QUIET_MS : REMOTE_MS) : (this.watched ? WATCHED_MS : UNWATCHED_MS);
    if (window()?.active === false) every = Math.max(every, INACTIVE_MS);
    if (!this.stale && Date.now() - (this.refreshedAt || 0) < every - 500) return;
    this.refresh(cx);
  }

  job(requests) {
    if (!requests.length) return;
    openOverlay({mod:"personal-files",kind:"dialog",width:520,height:JOB_DIALOG_HEIGHT,props:{mode:"job",requests}});
  }

  upload(paths, directory, on) {
    this.job(uploadRequests(paths, directory, on));
  }

  trackFileDrag(event, cx) {
    const press = this.documentPress;
    if (!press) return;
    // A folder's mouse move bubbles here with the panel's own local coordinates.
    const folder = press.hoverFolder ?? null;
    press.hoverFolder = null;
    if (!this.fileDragged && !movement(press.point,event)) return;
    this.fileDragged = true;
    if (!this.transfer) return;
    this.dropFolder = folder === press.parent ? null : folder;
    press.pointer = { ...event.local_position, width:event.bounds.width, height:event.bounds.height };
    cx.notify();
  }

  clearFileDrag(cx) {
    const visible = this.documentPress?.pointer;
    this.documentPress = null;
    this.dropFolder = null;
    if (visible) cx.notify();
  }

  finishFileDrag(event, folder, cx) {
    const press = this.documentPress;
    if (!press) return;
    this.fileDragged ||= movement(press.point,event);
    this.clearFileDrag(cx);
    if (!this.fileDragged) return;
    cx.stop_propagation();
    if (folder === null || folder === press.parent || !this.current(press.context)) return;
    const {source,on} = press.doc;
    const directory = folder ? `${this.root}/${folder}` : this.root;
    cx.spawn(async task=>{
      try {
        const result = await bridge({action:"move",source,directory,on,job:jobId()});
        if (!result.ok) {
          const message = result.code === "exists" ? "The destination already contains a file with this name." : result.error;
          throw new Error(message);
        }
        setShared("personal-files.changed",jobId());
        task.notify();
        notify({title:"File moved",level:"info"});
      } catch (error) {
        notify({title:"Could not move file",body:String(error.message || error),level:"warning"});
      }
    });
  }

  fileDropTarget(el, folder, t) {
    return el.when(this.dropFolder === folder,target=>target.bg(t.selected).border_1().border_color(t.accent))
      .on_mouse_move(()=>{if (this.documentPress) this.documentPress.hoverFolder = folder;})
      .on_mouse_up("left",(event,cx)=>this.finishFileDrag(event,folder,cx));
  }

  fileDragLabel(press, t) {
    const scale = Number(settings().zoom) || 1;
    const point = press.pointer;
    const x = point.x / scale, y = point.y / scale;
    const width = point.width / scale, height = point.height / scale;
    const leftHalf = x <= width / 2;
    const below = height - y >= 38;
    // Keep the label inside the panel and away from the pointer's hit target.
    return div().id("file-drag-label").absolute().px(8).py(4).rounded(5).shadow_sm()
      .max_w(Math.max(1,(leftHalf ? width - x : x) - 14)).truncate()
      .when(leftHalf,el=>el.left(x + 10)).when(!leftHalf,el=>el.right(width - x + 10))
      .when(below,el=>el.top(y + 10)).when(!below,el=>el.bottom(height - y + 10))
      .border_1().border_color(t.accent).bg(t.popover).text_color(t.foreground).text_size(12)
      .child(press.doc.name);
  }

  cancelDrop() {
    if (!this.dropping && props()?.overlay) closeOverlay(props().overlay);
  }

  finishDrop(side,cx) {
    if (this.dropping) return;
    if (!side) { this.cancelDrop();return; }
    const {drag,overlay}=props();
    this.dropping=true;
    cx.spawn(async task=>{
      try {
        if(!await splitDocument(drag,side,task)) notify({title:"Could not open the split view",level:"warning"});
      } catch (error) {
        notify({title:"Could not open the split view",body:String(error),level:"warning"});
      } finally { if(overlay)closeOverlay(overlay); }
    });
  }

  renderLift() {
    const t=theme(), zoom=Number(settings().zoom)||1, current=layout();
    const tabs=findNode(current,"tabs"), sidebar=findNode(current,"sidebar");
    const left=sidebar && !sidebar.hidden ? sidebar.size?.px || 0 : 0;
    const height=tabs && !tabs.hidden ? tabs.size?.px || 42 : 0;
    const right=this.dropWidth/zoom;
    const inTabs=event=>{
      const point=event.position;
      return point.x>=left*zoom && point.x<right*zoom && point.y>=0 && point.y<height*zoom;
    };
    return div().id("pane-lift-target").size_full().relative().track_focus(this.dropFocus)
      .on_size_change((size,cx)=>{if(this.dropWidth!==size.width){this.dropWidth=size.width;cx.notify();}})
      .on_key_down((event,cx)=>{if(event.key==="escape"){cx.stop_propagation();this.cancelDrop();}})
      .on_mouse_down("left",(_event,cx)=>{cx.stop_propagation();this.cancelDrop();})
      .on_mouse_move((event,cx)=>{const over=inTabs(event);if(this.overTabs!==over){this.overTabs=over;cx.notify();}})
      .on_mouse_up("left",(event,cx)=>{
        cx.stop_propagation();
        if (this.dropping) return;
        if (!inTabs(event)) {this.cancelDrop();return;}
        const {pane,overlay}=props();
        this.dropping=true;
        cx.spawn(async task=>{
          try {
            if (!await liftPane(pane,task)) notify({title:"Could not move the pane to a new tab",level:"warning"});
          } catch (error) {
            notify({title:"Could not move the pane to a new tab",body:String(error),level:"warning"});
          } finally { if(overlay)closeOverlay(overlay); }
        });
      })
      .when(height>0,el=>el.child(h_flex().absolute().left(left+5).top(3).w(Math.max(1,right-left-10)).h(Math.max(1,height-6))
        .items_center().justify_center().rounded(6).border(1).border_color(this.overTabs?t.accent:t.border)
        .bg(this.overTabs?"#2563eb66":"#172033aa")
        .child(div().rounded(4).px(10).py(3).bg(t.raised).text_color(t.foreground).child("Drop here to move to a new tab"))));
  }

  renderDrop() {
    const t=theme(),zoom=Number(settings().zoom)||1,current=layout();
    const sidebar=findNode(current,"sidebar"), panel=findNode(current,"panel");
    const left=sidebar && !sidebar.hidden ? (sidebar.size?.px||0)+8 : 8;
    const right=this.dropWidth/zoom-(panel && !panel.hidden ? panel.size?.px||0 : 0)-8;
    const top=(findNode(current,"tabs")?.size?.px||42)+8;
    const bottom=this.dropHeight/zoom-36;
    const bounds={left:left*zoom,right:right*zoom,top:top*zoom,bottom:bottom*zoom};
    const where=event=>dropSide(event.local_position || event.position,bounds);
    const slot=(side,x)=>v_flex().absolute().left(x).top(top).w(Math.max(1,(right-left)/2)).h(Math.max(1,bottom-top))
      .items_center().justify_center().rounded(9).border(2).border_color(this.side===side?t.accent:t.border)
      .bg(this.side===side?"#2563eb44":"#17203344")
      .child(div().px(12).py(7).rounded(7).bg(t.raised).text_color(t.foreground).child(side==="left"?"Split left":"Split right"));
    return div().id("document-drop-target").size_full().relative().track_focus(this.dropFocus)
      .on_size_change((size,cx)=>{if(this.dropWidth!==size.width||this.dropHeight!==size.height){this.dropWidth=size.width;this.dropHeight=size.height;cx.notify();}})
      .on_key_down((event,cx)=>{if(event.key==="escape"){cx.stop_propagation();this.cancelDrop();}})
      .on_mouse_down("left",(_event,cx)=>{cx.stop_propagation();this.cancelDrop();})
      .on_mouse_move((event,cx)=>{const side=where(event);if(side!==this.side){this.side=side;cx.notify();}})
      .on_mouse_up("left",(event,cx)=>{cx.stop_propagation();this.finishDrop(where(event),cx);})
      .child(slot("left",left)).child(slot("right",(left+right)/2));
  }

  menuActions(dir) {
    return (dir ? [PASTE,OPEN_DOWNLOADS] : [...FILE_ACTIONS,OPEN_DOWNLOADS]).filter(a=>this[a.feature]);
  }

  menuHeight(dir) {
    return 42 + 30 * this.menuActions(dir).length + (dir ? 34 : 0);
  }

  keyContext() {
    return "HerdrFiles" + (this.transfer ? "Transfer" : "") + (this.pdf ? "Document" : "");
  }

  shortcuts() {
    return [...FILE_ACTIONS,PASTE].filter(item=>item.key && this[item.feature]);
  }

  withShortcuts(el, target) {
    el = el.track_focus(this.treeFocus);
    if (!target) return el;
    el = el.key_context(this.keyContext());
    for (const item of this.shortcuts()) {
      el = el.on_action("personal-files-" + item.id, (_event,cx)=>{
        const popup = this.mode === "menu";
        const active = popup ? target : this.selected || target;
        cx.stop_propagation();
        if ((popup || this.current(this.context)) && this.menuActions(active.dir).includes(item)) {
          this.menuAction(item.id,active,cx);
        }
      });
    }
    return el;
  }

  showMenu(target, cx) {
    cx.stop_propagation();
    this.selected = target;
    this.openPane = focused()?.pane ?? this.openPane;
    this.treeFocus.focus();
    openOverlay({mod:"personal-files",kind:"popup",width:310,height:this.menuHeight(target.dir),
      props:{mode:"menu",target,transfer:this.transfer,pdf:this.pdf,openPane:this.openPane}});
  }

  pasteSource(target) {
    const clip = shared(CLIPBOARD);
    return target.dir && clip?.source && clip.on === target.on &&
      (clip.action === "copy" || clip.action === "move") ? clip : null;
  }

  menuAction(id, target, cx) {
    const clip = id === "paste" ? this.pasteSource(target) : null;
    if (id === "paste" && !clip) return;
    const overlay = this.mode === "menu" && props()?.overlay;
    if (overlay) closeOverlay(overlay);
    const {source,on} = target;
    switch (id) {
      case "open-side":
      case "view-split-left":
        startDocumentDrag(fileDocument(target.source,target.on),id === "open-side" ? "right" : "left");
        break;
      case "view-file":
        openDocument(fileDocument(target.source,target.on),cx,props()?.openPane ?? this.openPane);
        break;
      case "cut":
      case "copy":
        setShared(CLIPBOARD,{action:id === "cut" ? "move" : "copy",source,on,id:jobId()});
        break;
      case "paste":
        this.job([{action:clip.action,source:clip.source,on,directory:target.source,
          cutId:clip.action === "move" ? clip.id : null,job:jobId()}]);
        break;
      case "copy-path":
      case "copy-relative":
        cx.write_to_clipboard(id === "copy-path" ? source : target.relative);
        setShared(CLIPBOARD,null);
        break;
      case "rename":
      case "delete":
        openOverlay({mod:"personal-files",kind:"dialog",width:440,height:CHANGE_DIALOG_HEIGHT,
          props:{mode:id,target,transfer:this.transfer}});
        break;
      case "download":
      case "download-open":
        this.job([{action:"download",source,on,choose:id === "download",open:id === "download-open",job:jobId()}]);
        break;
      case "open-downloads":
        this.job([{action:"folder",job:jobId()}]);
        break;
    }
  }

  submitChange(cx) {
    const {target,overlay} = props();
    if (!this.transfer || this.busy || target.dir) return;
    const rename = this.mode === "rename";
    const request = {action:this.mode,source:target.source,on:target.on,job:jobId()};
    if (rename) {
      request.name = this.nameInput.value();
      if (!request.name || request.name === "." || request.name === ".." || request.name.includes("/")) {
        this.error = "Enter a single file name."; cx.notify(); return;
      }
      if (request.name === target.name) { closeOverlay(overlay); return; }
    } else {
      request.confirmed = true;
    }
    this.busy = true;
    this.error = null;
    cx.notify();
    cx.spawn(async task=>{
      try {
        const result = await bridge(request);
        if (!result.ok) throw new Error(result.error);
        setShared("personal-files.changed",{id:request.job,source:target.source,on:target.on});
        closeOverlay(overlay);
      } catch (error) {
        this.error = String(error.message || error);
      } finally {
        this.busy = false; task.notify();
      }
    });
  }

  dialogButton(id, label, action, style = "secondary", disabled = this.busy) {
    const t = theme(), primary = style === "primary", danger = style === "danger";
    return Button.new(id).accessibility_label(label).disabled(disabled)
      .h_flex().items_center().justify_center().flex_none().h(34).min_w(80).px(12)
      .whitespace_nowrap().rounded(6).border_1().font_medium()
      .bg(primary ? t.solid : t.raised).text_color(primary ? t.solid_foreground : danger ? t.ansi1 : t.foreground)
      .border_color(primary ? t.solid : danger ? t.ansi1 : t.input)
      .focus(s=>s.border_color(t.accent))
      .when(disabled, el=>el.opacity(0.55))
      .when(!disabled, el=>el.cursor_pointer().hover(s=>primary ? s.opacity(0.88) : s.bg(t.hover)))
      .on_click((_e,cx)=>action(cx)).child(label);
  }

  renderDialog(height, title, body, actions) {
    const t = theme();
    return v_flex().w_full().h(height).max_h_full().min_h(0).p(16).gap(10)
      .bg(t.popover).text_color(t.foreground).text_size(13)
      .child(div().flex_none().text_size(16).font_semibold().child(title))
      .child(body.id("file-dialog-body").w_full().flex_1().min_h(0).gap(8).overflow_y_scrollbar())
      .child(actions.w_full().flex_none().items_center().justify_end().gap(8));
  }

  renderChange() {
    const t = theme(), {target,overlay} = props(), rename = this.mode === "rename";
    const body = v_flex()
      .child(div().flex_none().truncate().tooltip(target.source).child((target.on ? target.on + " · " : "") + target.source))
      .when(rename, el=>el.child(Input.new(this.nameInput).flex_none().h(34).px(9).items_center().rounded(5).border_1()
        .border_color(t.accent).bg(t.background).text_color(t.foreground)))
      .when(!rename, el=>el.child(div().flex_none().text_color(t.muted).child("This file cannot be recovered from the Recycle Bin.")))
      .when(Boolean(this.error), el=>el.child(div().flex_none().text_color(t.blocked).child(this.error)));
    const actions = h_flex()
      .child(this.dialogButton("cancel-change","Cancel",()=>closeOverlay(overlay)))
      .child(this.dialogButton("confirm-" + this.mode, rename ? "Rename" : "Delete permanently",
        cx=>this.submitChange(cx), rename ? "primary" : "danger"));
    return this.renderDialog(CHANGE_DIALOG_HEIGHT, rename ? "Rename file" : "Permanently delete this file?", body, actions);
  }

  async pollProgress(cx) {
    const job = this.queue?.[this.index]?.job;
    if (!this.busy || !job || this.polling) return;
    this.polling = true;
    try {
      const text = await readTextFile(`${appHome()}/data/personal-files/jobs/${job}.json`);
      if (text && this.queue?.[this.index]?.job === job) { this.progress = JSON.parse(text); cx.notify(); }
    } catch {} finally { this.polling = false; }
  }

  // Asks the running helper to stop. It checks between chunks and removes what it staged.
  cancelJob(cx) {
    const job = this.queue?.[this.index]?.job;
    if (!this.busy || !job || this.cancelling) return;
    this.cancelling = true;
    cx.notify();
    writeTextFile(`${appHome()}/data/personal-files/jobs/${job}.cancel`, "1", null).catch(() => {});
  }

  // A transfer that stopped part-way keeps a staging file. Remove it when the dialog is dismissed.
  closeJob(cx) {
    const {resume,on,job} = this.queue?.[this.index] || {};
    if (!resume || this.busy) { closeOverlay(props().overlay); return; }
    this.busy = true;
    cx.notify();
    cx.spawn(async () => {
      try { await bridge({action:"discard",resume,on,job}); } catch {}
      closeOverlay(props().overlay);
    });
  }

  work(cx, overwrite = false) {
    if (this.busy || this.index >= this.queue.length) return;
    if (overwrite) this.queue[this.index].overwrite = true;
    this.busy = true; this.error = null; this.collision = false; this.cancelling = false;
    cx.spawn(async cx => {
      try {
        while (this.index < this.queue.length) {
          this.progress = null;
          const {cutId,...request} = this.queue[this.index];
          let value = await bridge(request);
          // A long transfer returns before the app's time limit and continues from where it stopped.
          while (value.ok && value.partial) {
            this.queue[this.index].resume = request.resume = value.resume;
            if (this.cancelling) {
              await bridge({action:"discard",resume:value.resume,on:request.on,job:request.job});
              value = {ok:false,code:"cancelled"};
            } else value = await bridge(request);
          }
          // A failure that can continue says where; any other clears it so a retry starts over.
          this.queue[this.index].resume = value.ok ? undefined : value.resume;
          if (value.code === "cancelled") {
            this.result = {cancelled:true};
            this.index = this.queue.length;
            return;
          }
          if (!value.ok) {
            this.error = value.error;
            this.collision = value.code === "exists" && (request.action === "upload" || (request.action === "download" && !request.choose));
            return;
          }
          this.result = value;
          this.index++;
          if (!value.cancelled) {
            if (cutId && shared(CLIPBOARD)?.id === cutId) setShared(CLIPBOARD,null);
            setShared("personal-files.changed", request.action === "move"
              ? {id:request.job,source:request.source,on:request.on} : jobId());
          }
          cx.notify();
        }
      } catch (e) { this.error = String(e); }
      finally { this.busy = false; this.cancelling = false; cx.notify(); }
    });
  }

  button(id, label, action, disabled = false) {
    const t=theme();
    return div().id(id).px(9).py(5).rounded(5).text_color(disabled?t.dim:t.foreground)
      .cursor_pointer().hover(s=>s.bg(disabled?t.surface:t.hover))
      .on_mouse_down("left",(_e,cx)=>cx.stop_propagation())
      .on_click((_e,cx)=>{if(!disabled)action(cx);}).child(label);
  }

  renderMenu() {
    const t=theme(), target=props().target;
    // Native popups measure their contents before assigning a height to the scroll area.
    const menu = v_flex().w_full().h(this.menuHeight(target.dir)).min_h(0).overflow_y_scrollbar().p(6).gap(2).bg(t.popover).text_size(13).text_color(t.foreground)
      .child(div().px(9).py(5).truncate().text_color(t.dim).child(target.name))
      .children(this.menuActions(target.dir).map(item=>{
        const label = h_flex().items_center().justify_between().gap(8).child(item.label)
          .when(Boolean(item.hint),el=>el.child(div().text_size(11).text_color(t.dim).child(item.hint)));
        return this.button(item.id,label,cx=>this.menuAction(item.id,target,cx),item.id === "paste" && !this.pasteSource(target));
      }))
      .when(target.dir && this.transfer,el=>el.child(div().p(9).text_color(t.muted).child("Drop files onto this folder to upload.")));
    return this.withShortcuts(menu,target);
  }

  renderJob() {
    const t=theme(), current=this.queue?.[this.index], done=this.index>=this.queue.length;
    const title=current?.action==="upload"?"Upload to "+(current.on||"this computer"):
      ({copy:"Copy file",move:"Move file",folder:"Open Downloads folder"})[current?.action] || "Download";
    const cancelled = done && this.result?.cancelled;
    const progress=this.progress;
    const body = v_flex()
      .child(div().flex_none().text_color(t.muted).truncate().child(current?.source || this.result?.path || ""))
      .child(div().flex_none().text_color(this.error?t.blocked:t.muted).child(this.error || (this.cancelling ? "Cancelling…" : this.busy ? (progress ? `${Math.round(progress.done/Math.max(1,progress.total)*100)}% · ${(progress.done/1048576).toFixed(1)} / ${(progress.total/1048576).toFixed(1)} MB` : "Connecting…") : cancelled?"":done?(this.result?.message || `${this.index} operation(s) completed`):"Ready")))
      .when(current?.action==="upload",el=>el.child(div().flex_none().text_color(t.dim).truncate().child(`Folder: ${current.directory}`)));
    const stoppable = this.busy && ["upload","download"].includes(current?.action);
    const actions = h_flex()
      .child(this.dialogButton("close-job",this.busy ? "Working…" : "Close",cx=>this.closeJob(cx)))
      .when(stoppable, el=>el.child(this.dialogButton("cancel-job","Cancel",cx=>this.cancelJob(cx),"danger",this.cancelling)))
      .when(this.collision, el=>el.child(this.dialogButton("replace-file","Replace file",cx=>this.work(cx,true),"danger")))
      .when(Boolean(this.error) && !this.collision, el=>el.child(this.dialogButton("retry-file","Retry",cx=>this.work(cx),"primary")));
    return this.renderDialog(JOB_DIALOG_HEIGHT, cancelled ? "Cancelled" : done ? "Completed" : title, body, actions);
  }

  watch(root, cx) {
    if (this.on || this.watched === root) return;
    this.watched = root;
    const context = this.context;
    cx.spawn(async cx => {
      try {
        while (this.context === context) {
          const paths = await (this.watching = watchFolder(root));
          if (this.current(context)) this.noteChanges(paths, context, cx);
        }
      }
      catch { if (this.context === context) this.watched = null; }
    });
  }

  // A batch from the watch: read again only the shown folders it touches.
  noteChanges(paths, context, cx) {
    const folders = changedFolders(paths, context.cwd, this.folders);
    if (folders && !folders.size) return;
    this.touched = !folders || this.touched === "all" ? "all" : new Set([...(this.touched || []), ...folders]);
    this.scheduleChanges(cx);
  }

  scheduleChanges(cx) {
    if (!this.touched || this.changeTimer || this.loading) return;
    const apart = window()?.active === false ? UNWATCHED_MS : MIN_REFRESH_MS;
    const wait = Math.max(50, apart - (Date.now() - (this.refreshedAt || 0)));
    this.changeTimer = cx.timer.after(wait, cx => {
      this.changeTimer = null;
      if (this.loading) return;
      const touched = this.touched;
      this.touched = null;
      if (!this.shown()) { this.stale = true; return; }
      this.refresh(cx, false, touched === "all" ? null : touched);
    });
  }

  current(context) {
    return this.context === context && key() === context.key;
  }

  applyFolder(path, entries) {
    const used = [...this.entries.entries()].filter(([p]) => p !== path).reduce((n, [, e]) => n + e.length, 0);
    this.entries.set(path, entries.slice(0, Math.max(0, Math.min(PER_FOLDER, TOTAL - used))).sort((a, b) => Number(b.dir) - Number(a.dir) || a.name.localeCompare(b.name)));
    if (entries.length > PER_FOLDER || used + entries.length > TOTAL) this.limited = true;
  }

  async loadFolder(path, context) {
    const { on, cwd: root } = context;
    const [entries] = await listFolders([path ? `${root}/${path}` : root], on);
    if (!this.current(context) || (path && !this.folders.has(path))) return;
    if (!Array.isArray(entries)) throw entries || new Error("Cannot list this folder");
    this.applyFolder(path, entries);
  }

  entryAt(path) {
    const slash = path.lastIndexOf("/");
    const parent = slash < 0 ? "" : path.slice(0,slash);
    return this.entries.get(parent)?.find(entry=>entry.name === path.slice(slash + 1));
  }

  requestRefresh(cx) {
    this.quiet = 0;
    this.refresh(cx,true);
    cx.notify();
  }

  trustRepository(cx) {
    if (!this.gitNote) return;
    setShared(TRUSTED, [...(shared(TRUSTED) || []).filter(key => key !== this.gitNote).slice(-49), this.gitNote]);
    this.requestRefresh(cx);
  }

  // Reads the tree again. `only` names the shown folders a watch reported; without it everything is read.
  refresh(cx, queueIfBusy = false, only = null) {
    const { cwd, on } = location(), next = key();
    if (next !== this.context?.key) {
      this.clearFileDrag(cx);
      this.selected = null;
      if (this.context) this.saved.set(this.context.key, { folders: this.folders, file: this.file });
      if (this.saved.size > 50) this.saved.delete(this.saved.keys().next().value);
      const saved = this.saved.get(next);
      this.context = { key: next, cwd, on }; this.root = cwd; this.on = on; this.entries = new Map(); this.folders = new Set(saved?.folders);
      this.pending = new Set(); this.marks = {}; this.show(null); this.watched = null; this.error = null; this.limited = false;
      this.loading = false; this.refreshAgain = false;
      // The folder that was shown is no longer watched.
      this.watching?.cancel?.(); this.watching = null;
      this.changeTimer?.cancel?.(); this.changeTimer = null;
      this.touched = null; this.quiet = 0; this.listed = null; this.gitNote = null;
      only = null;
      if (saved?.file) this.show(saved.file, cx);
    }
    if (!cwd) return;
    if (this.loading) {
      if (queueIfBusy) this.refreshAgain = true;
      return;
    }
    const context = this.context;
    this.loading = true;
    if (!only) { this.limited = false; this.stale = false; }
    cx.spawn(async cx => {
      try {
        const wanted = only ? [...only].filter(path => path !== GIT_ONLY && (path === "" || this.folders.has(path))) : ["", ...this.folders];
        // One program lists every folder that is read.
        const listed = wanted.length ? await listFolders(wanted.map(path => path ? `${cwd}/${path}` : cwd), on) : [];
        if (!this.current(context)) return;
        wanted.forEach((path, i) => {
          const entries = listed[i];
          if (path && (!this.folders.has(path) || !this.entryAt(path)?.dir || entries === null)) {
            this.folders.delete(path);
            this.entries.delete(path);
            return;
          }
          if (!Array.isArray(entries)) throw entries || new Error("Cannot list this folder");
          this.applyFolder(path, entries);
        });
        // An open folder is dropped once its parent's new listing no longer has it.
        for (const folder of only ? [...this.folders] : []) {
          const slash = folder.lastIndexOf("/"), parent = slash < 0 ? "" : folder.slice(0, slash);
          if ((parent && !this.folders.has(parent)) || (wanted.includes(parent) && !this.entryAt(folder)?.dir)) {
            this.folders.delete(folder);
            this.entries.delete(folder);
          }
        }
        if (this.selected?.path && this.entryAt(this.selected.path)?.dir !== this.selected.dir) this.selected = null;
        const top = await exec("git", ["rev-parse", "--show-toplevel"], { cwd, on }).catch(() => null);
        const marks = {};
        let gitNote = null;
        if (top?.code === 0) {
          const repository = `${on ?? ""}\n${top.stdout.trim()}`;
          if (!(shared(TRUSTED) || []).includes(repository) && await repositoryRunsPrograms(cwd, on)) gitNote = repository;
          else {
            // Writes nothing under .git (index lock, fsmonitor cookie): the folder watch would refresh again.
            // A submodule is compared by its commit only, so no status runs inside it under its own config.
            const status = await exec("git", ["--no-optional-locks", "-c", "core.fsmonitor=false", "status", "--porcelain=v1", "-z", "--no-renames", "--untracked-files=all", "--ignore-submodules=dirty"], { cwd, on }).catch(() => null);
            if (status?.code === 0) for (const entry of status.stdout.split("\0").filter(Boolean).slice(0, TOTAL)) {
              const xy = entry.slice(0, 2);
              marks[`${top.stdout.trim()}/${entry.slice(3)}`] = xy === "??" || xy.includes("A") ? "A" : xy.includes("U") ? "U" : xy.includes("D") ? "D" : "M";
            }
          }
        }
        if (!this.current(context)) return;
        this.marks = marks; this.gitNote = gitNote; this.error = null; this.watch(cwd, cx);
        if (on && !only) {
          // Another machine reports no changes: read less often while its listing stays the same.
          const now = JSON.stringify([[...this.entries], marks]);
          this.quiet = now === this.listed ? (this.quiet || 0) + 1 : 0;
          this.listed = now;
        }
      } catch (e) { if (this.current(context)) this.error = String(e); }
      finally {
        if (this.context === context) {
          this.loading = false;
          this.refreshedAt = Date.now();
          if (this.refreshAgain) {
            this.refreshAgain = false;
            this.refresh(cx);
          } else this.scheduleChanges(cx);
        }
        cx.notify();
      }
    });
  }

  toggle(path, cx) {
    if (this.folders.has(path)) {
      for (const folder of [...this.folders]) if (folder === path || folder.startsWith(path + "/")) {
        this.folders.delete(folder);
        this.entries.delete(folder);
      }
    } else {
      this.folders.add(path);
      if (!this.entries.has(path) && !this.pending.has(path)) {
        const context = this.context;
        this.pending.add(path);
        cx.spawn(async cx => {
          try { await this.loadFolder(path, context); }
          catch (e) { if (this.current(context)) this.error = String(e); }
          finally { if (this.context === context) this.pending.delete(path); cx.notify(); }
        });
      }
    }
    cx.notify();
  }

  show(path, cx) {
    this.code?.release(); this.code = null; this.file = path; this.fileError = null;
    if (!path || !cx) return;
    const context = this.context, root = this.root, on = this.on;
    cx.spawn(async cx => {
      try {
        const preview = await bridge({action:"text",source:`${root}/${path}`,on,job:jobId()});
        if (!preview.ok) throw new Error("Cannot read file");
        const text=preview.text;
        if (this.file !== path || !this.current(context)) return;
        if (text === null) { this.fileError = "Binary file · no text preview"; return; }
        if (text.includes("\0")) { this.fileError = "Binary file · no text preview"; return; }
        const t = theme(), ext = path.includes(".") ? path.split(".").pop() : "txt";
        this.code = EditorState.new({ language: LANG[ext] ?? ext, readonly: true,
          value: text.length > 400000 ? text.slice(0, 400000) + "\n… (file truncated)" : text,
          font_family: settings().font_family, font_size: 12,
          syntax: { keyword: t.ansi5, string: t.ansi2, comment: t.dim, function: t.ansi4, type: t.ansi3, number: t.ansi1, constant: t.ansi6 } });
      } catch { if (this.file === path && this.current(context)) this.fileError = "Cannot preview this file (binary, too large, or unreadable)"; }
      finally { cx.notify(); }
    });
  }

  openFile(target, cx) {
    if (this.pdf) openDocument(fileDocument(target.source,target.on),cx,this.openPane);
    else this.show(target.path,cx);
  }

  rows(prefix, depth, out, t) {
    const root=this.root,on=this.on;
    if (out.length >= TOTAL || depth > 40) return out;
    for (const entry of this.entries.get(prefix) ?? []) {
      if (out.length >= TOTAL) break;
      const path = prefix ? `${prefix}/${entry.name}` : entry.name, open = this.folders.has(path), mark = this.marks[`${this.root}/${path}`];
      const target = menuTarget(root,on,path,entry.dir,entry.name);
      out.push(h_flex().id(`file-${path}`).h(28).flex_none().pl(8 + depth * 18).pr(8).gap(7).items_center().rounded(7).cursor_pointer().hover(s => s.bg(this.dropFolder === path ? t.selected : t.hover))
        .when(this.selected?.source === target.source && this.selected?.on === on,el=>el.bg(t.selected))
        .on_click((event, cx) => {
          if (this.fileDragged || this.root !== root || this.on !== on) return;
          if (entry.dir && event.click_count === 1) this.toggle(path,cx);
          if (!entry.dir && event.click_count === 2) this.openFile(target,cx);
        })
        .on_mouse_down("left",(event,cx)=>{
          cx.stop_propagation();
          this.openPane = focused()?.pane ?? this.openPane;
          this.selected = target;
          this.treeFocus.focus();
          cx.notify();
          this.fileDragged=false;
          this.documentPress=entry.dir || (!this.transfer && !this.pdf) ? null : {point:event.position,parent:prefix,context:this.context,doc:fileDocument(target.source,target.on)};
        })
        .when(this.transfer && entry.dir,el=>this.fileDropTarget(el,path,t))
        .when(this.transfer || (this.pdf && !entry.dir),el=>el.on_mouse_down("right",(_e,cx)=>this.showMenu(target,cx)))
        .when(this.transfer && entry.dir,el=>el.on_drop((event,cx)=>{cx.stop_propagation();this.upload(event.paths,`${root}/${path}`,on);}))
        .child(entry.dir ? svg(`mods/files/chevron-${open ? "down" : "right"}.svg`).size(12).flex_none().text_color(t.dim) : div().w(12).flex_none())
        .child(svg(`mods/files/${entry.dir ? "folder" : "file"}.svg`).size(14).flex_none().text_color(t.muted))
        .child(div().flex_1().min_w(0).truncate().child(entry.name))
        .when(Boolean(mark), el => el.child(div().text_size(11).text_color(mark === "A" ? t.ansi2 : mark === "D" || mark === "U" ? t.ansi1 : t.blocked).child(mark))));
      if (entry.dir && open) this.rows(path, depth + 1, out, t);
    }
    return out;
  }

  render(cx) {
    if(this.mode==="menu") return this.renderMenu();
    if(this.mode==="rename" || this.mode==="delete") return this.renderChange();
    if(this.mode==="job") return this.renderJob();
    if(this.mode==="pdf" || this.mode==="document" || this.mode==="group") return this.renderDocument(cx);
    if(this.mode==="drop") return this.renderDrop();
    if(this.mode==="lift") return this.renderLift();
    const changed=shared("personal-files.changed");
    const changeId = changed?.id ?? changed;
    if (!checking() && (key() !== this.context?.key || changeId !== this.changed)) {
      if (changeId !== this.changed && changed?.source && changed.on === this.on) {
        if (this.selected?.source === changed.source) this.selected = null;
        if (this.file && menuTarget(this.root,this.on,this.file,false,"").source === changed.source) this.show(null);
      }
      const newChange = changeId !== this.changed;
      this.changed=changeId; this.refresh(cx,newChange);
    } else if (!checking() && this.stale && !this.loading && this.shown()) this.refresh(cx);
    const t = theme();
    this.openPane = focused()?.pane ?? this.openPane;
    const root=this.root,on=this.on,file=this.file;
    const rootTarget = root ? menuTarget(root,on,"",true,root) : null;
    return v_flex().id("files").relative().size_full().min_h(0).rounded(10).overflow_hidden().bg(t.background).border_1().border_color(t.border).text_color(t.foreground).text_size(13)
      .on_mouse_move((event,cx)=>this.trackFileDrag(event,cx))
      .on_mouse_up("left",(event,cx)=>this.finishFileDrag(event,null,cx))
      .on_mouse_down_out((_event,cx)=>this.clearFileDrag(cx))
      .on_key_down((event,cx)=>{
        if (event.key === "escape" && this.documentPress) {
          cx.stop_propagation();
          this.fileDragged = true;
          this.clearFileDrag(cx);
        }
      })
      .on_hover((hovered,cx)=>{
        if (hovered || !this.documentPress) return;
        const {doc,context} = this.documentPress;
        this.fileDragged=true;
        this.clearFileDrag(cx);
        if (this.current(context)) startDocumentDrag(doc);
      })
      .child(h_flex().h(42).flex_none().px(14).gap(8).items_center().border_b(1).border_color(t.border)
        .when(Boolean(this.file), el => el.child(div().id("files-back").w(20).cursor_pointer().text_color(t.muted).on_click((_e, cx) => { this.show(null); cx.notify(); }).child("←")))
        .child(div().font_semibold().child("Files"))
        .when(root && !file,el=>el.child(this.button("files-refresh",this.loading ? "Refreshing…" : "Refresh",cx=>this.requestRefresh(cx))
          .tooltip("Refresh this folder and expanded folders (F5)")))
        .when(Boolean(file),el=>el.child(this.button("download-preview","Download",()=>this.job([{action:"download",source:`${root}/${file}`,on,job:jobId()}]))))
        .child(div().flex_1().min_w(0).truncate().text_right().text_size(12).text_color(t.dim).child(this.file ?? this.root?.split(/[\\/]/).pop() ?? "")))
      .when(!this.file,el=>el.child(div().id("upload-root").px(12).py(8).text_size(11).text_color(t.muted).bg(t.surface)
        .tooltip(this.root?`Upload to ${this.on||"this computer"}: ${this.root}`:"Choose a folder first")
        .when(Boolean(rootTarget),el=>el
          .on_mouse_down("left",(_e,cx)=>{this.selected=rootTarget; this.treeFocus.focus(); cx.notify();})
          .on_mouse_down("right",(_e,cx)=>this.showMenu(rootTarget,cx)))
        .when(Boolean(root),target=>this.fileDropTarget(target,"",t))
        .on_drop((event,cx)=>{cx.stop_propagation();if(root)this.upload(event.paths,root,on);})
        .child(this.fileDragged && this.documentPress ? "Drop here to move to the current root folder" : "Drop files here or onto a folder to upload")))
      .when(!this.file, el => el.child(this.withShortcuts(v_flex().id("files-tree").flex_1().min_h(0).overflow_y_scrollbar().p(6),rootTarget)
        .on_mouse_down("left",(_event,cx)=>{this.selected=rootTarget; this.treeFocus.focus(); cx.notify();})
        .on_key_down((event,cx)=>{
          if (event.keystroke === "f5" && root) {
            cx.stop_propagation();
            this.requestRefresh(cx);
          } else if (event.keystroke === "enter" && this.selected && !this.selected.dir) {
            cx.stop_propagation();
            if (!event.is_held) this.openFile(this.selected,cx);
          }
        })
        .when(this.transfer && rootTarget,tree=>tree.on_mouse_down("right",(_e,cx)=>this.showMenu(rootTarget,cx)))
        .on_drop((event,cx)=>{cx.stop_propagation();if(root)this.upload(event.paths,root,on);})
        .children(this.rows("", 0, [], t))
        .when(Boolean(this.error) || !this.entries.get("")?.length, el => el.child(div().p(8).text_size(12).text_color(t.dim).child(this.error || (this.loading ? "Loading files…" : this.root ? "No files" : "No folder"))))
        .when(this.limited, el => el.child(div().p(8).text_size(11).text_color(t.dim).child("File list limited to 500 entries per folder and 5,000 total")))
        .when(Boolean(this.gitNote), el => el.child(div().id("git-marks-off").p(8).text_size(11).text_color(t.dim).cursor_pointer()
          .tooltip("Git would run programs named in this repository's own config to compare files. Click if you trust this repository.")
          .on_click((_e, cx) => this.trustRepository(cx)).child("Git marks are off: this repository's config runs its own programs · Trust it")))))
      .when(Boolean(this.file), el => el.child(this.code ? Editor.new(this.code).flex_1().min_h(0) : div().p(12).text_color(t.dim).child(this.fileError || "Loading file…")))
      .when(this.documentPress?.pointer,el=>el.child(this.fileDragLabel(this.documentPress,t)));
  }
}
