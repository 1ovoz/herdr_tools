"""Stage portable variants of the live Herdr mods for the Windows installer."""

from pathlib import Path
import json
import shutil

work = Path(__file__).resolve().parents[1]
kit = work / "herdr-mod-kit"
source = work / "personal-files"
common = kit / "common"
files, pdf, tabs, usage, pane, links = (
    kit / "mods" / f"herdr-kit-{name}" for name in ("files", "pdf", "tabs", "usage", "pane", "links")
)


def read(path):
    return path.read_text(encoding="utf-8-sig")


def write(path, content):
    path.write_text(content, encoding="utf8")


def adapt(content, *edits):
    for original, replacement in edits:
        if original not in content:
            raise ValueError(f"Live implementation changed near {original!r}")
        content = content.replace(original, replacement)
    return content


for folder in (files, pdf, tabs, usage, pane):
    folder.mkdir(parents=True, exist_ok=True)
    write(folder / "mod.json", '{"place":"none"}\n')

shutil.copytree(work/"kit-version",kit/"mods"/"herdr-kit-version",dirs_exist_ok=True)

main = read(source / "main.js")
files_main = adapt(
    main,
    ('import { div, svg }', 'import { View, div, svg }'),
    ('import { DocumentView } from "./document-view.js";\n', ''),
    ('extends DocumentView', 'extends View'),
    ('    this.transfer = true;', '    this.transfer = Boolean(props()?.transfer);'),
    ('    this.pdf = true;', '    this.pdf = Boolean(props()?.pdf);'),
    ('    if (this.mode === "pdf" || this.mode === "document" || this.mode === "group") { this.initDocument(cx); return; }\n', ''),
    ('    if(this.mode==="pdf" || this.mode==="document" || this.mode==="group") return this.renderDocument(cx);\n', ''),
    ('personal-files', 'herdr-kit-files'),
    ('fileDocument(target.source,target.on)', 'fileDocument(target.source,target.on,this.transfer)'),
    ('if (this.current(context)) startDocumentDrag(doc);', 'if (this.pdf && this.current(context)) startDocumentDrag(doc);'),
    ('.when(Boolean(file),el=>el.child(this.button("download-preview"', '.when(this.transfer && Boolean(file),el=>el.child(this.button("download-preview"'),
    ('.when(!this.file,el=>el.child(div().id("upload-root")', '.when(this.transfer && !this.file,el=>el.child(div().id("upload-root")'),
    ('.on_drop((event,cx)=>{cx.stop_propagation();if(root)this.upload(event.paths,root,on);})\n        .children',
     '.when(this.transfer,tree=>tree.on_drop((event,cx)=>{cx.stop_propagation();if(root)this.upload(event.paths,root,on);}))\n        .children'),
    ('/data/herdr-kit-files/jobs/', '/data/herdr-mod-kit/files/jobs/'),
    ('if (!await liftPane(pane,task)) notify({title:"Could not move the pane to a new tab",level:"warning"});',
     '''if (!await liftPane(pane,task)) {
              console.error("[herdr-kit/tabs] pane_move_failed");
              notify({title:"Could not move the pane to a new tab",level:"warning"});
            }'''),
    ('notify({title:"Could not move the pane to a new tab",body:String(error),level:"warning"});',
     '''console.error("[herdr-kit/tabs] pane_move_failed");
            notify({title:"Could not move the pane to a new tab",body:String(error),level:"warning"});'''),
)
write(files / "main.js", "// Adapted from Herdr Files (Apache-2.0).\n" + files_main)

document = adapt(
    read(source / "document-view.js"),
    ('export class DocumentView extends View {\n  initDocument(cx) {',
     'export default class DocumentView extends View {\n  init(_props,cx) { this.initDocument(cx); }\n  render(cx) { return this.renderDocument(cx); }\n  initDocument(cx) {'),
    ('mod:"personal-files",kind:"dialog"', 'mod:"herdr-kit-files",kind:"dialog"'),
    ('this.transfer = p.transfer ?? true;', 'this.transfer = Boolean(p.transfer);'),
    ('.when(!compact,el=>el.child(this.button("document-download"',
     '.when(this.transfer && !compact,el=>el.child(this.button("document-download"'),
    ('"Preview unavailable for this file. Use Download to open it."',
     'this.transfer ? "Preview unavailable for this file. Use Download to open it." : "Preview unavailable for this file."'),
)
write(pdf / "main.js", document)
shutil.copy2(source / "pdf-geometry.js", pdf / "pdf-geometry.js")

drag = adapt(
    read(source / "document-drag.js"),
    ('personal-files', 'herdr-kit-pdf'),
    ('mod:"herdr-kit-pdf",kind:"window"', 'mod:"herdr-kit-files",kind:"window"'),
    ('fileDocument(source,on)', 'fileDocument(source,on,transfer)'),
    ('return {source,on,mode:', 'return {source,on,transfer,mode:'),
    ('name:doc.name,position:doc.position,id,anchorTab', 'name:doc.name,transfer:doc.transfer,position:doc.position,id,anchorTab'),
    ('mode:doc.mode,name:doc.name,split:true', 'mode:doc.mode,name:doc.name,transfer:doc.transfer,split:true'),
)
write(common / "document-drag.js", drag)
shutil.copy2(source / "document-flow.js", common / "document-flow.js")

tabs_main = adapt(
    read(work / "personal-tabs" / "main.js"),
    ('../personal-files/', './'),
    ('"personal-tabs"', '"herdr-kit-tabs"'),
    ('personal-files', 'herdr-kit-pdf'),
    ('mod:"herdr-kit-pdf",kind:"window"', 'mod:"herdr-kit-files",kind:"window"'),
)
write(tabs / "main.js", "// Adapted from Herdr Tabs (Apache-2.0).\n" + tabs_main)

pane_main = adapt(
    read(work / "personal-pane" / "main.js"),
    ('mod:"personal-files",kind:"window"', 'mod:"herdr-kit-files",kind:"window"'),
    ('p.mod === "personal-files"', 'p.mod === "herdr-kit-pdf"'),
    ('"personal-files.pane-documents"', '"herdr-kit-pdf.pane-documents"'),
    ('"personal-pane-lift"', '"herdr-kit-pane-lift"'),
)
write(pane / "main.js", "// Adapted from Herdr Pane (Apache-2.0).\n" + pane_main)

links.mkdir(parents=True, exist_ok=True)
link_source = work / "personal-terminal-links"
write(links / "mod.json", json.dumps(json.loads(read(link_source / "mod.json")), indent=2) + "\n")
link_main = adapt(
    read(link_source / "link.js"),
    ('import { exec, notify }', 'import { exec, layout, notify, shared }'),
    ('../personal-files/document-drag.js','./document-drag.js'),
    ('  if (link.kind !== "file" || !source.space)', '  if (shared("layout") !== "herdr-mod-kit" || link.kind !== "file" || !source.space)'),
    ('  routeDocument({name,', '''  const filesPanel = findFilesPanel(layout());
  routeDocument({name,'''),
    ('source:path,on:source.machine,mode:', 'source:path,on:source.machine,transfer:Boolean(filesPanel?.content?.props?.transfer),mode:'),
    ('    if (!path) {\n      notify', '    if (!path) {\n      console.error("[herdr-kit/pdf] link_resolution_failed");\n      notify'),
)
write(links / "link.js", link_main + '''

function findFilesPanel(block) {
  if (block?.id === "files") return block;
  for (const child of block?.children || []) {
    const panel = findFilesPanel(child);
    if (panel) return panel;
  }
  return null;
}
''')

actions = adapt(
    read(source / "actions.js"),
    ('/mods/personal-files/', '/data/herdr-mod-kit/helpers/'),
    ('''  const config = JSON.parse(await readTextFile''', '''  const feature = ["revision","preview","render","image","text"].includes(request.action) ? "pdf" : "transfer";
  try {
    const config = JSON.parse(await readTextFile'''),
    ('''  const result = await exec''', '''    const result = await exec'''),
    ('''  if (result.code !== 0) throw new Error("File helper stopped. Check the host connection and retry.");
  try { return JSON.parse(result.stdout); }
  catch { throw new Error("The file helper did not return a valid result."); }''',
     '''    if (result.code !== 0) throw new Error("Helper stopped");
    return JSON.parse(result.stdout);
  } catch {
    console.error(`[herdr-kit/${feature}] helper_unavailable action=${request.action}`);
    throw new Error("File helper unavailable. Run the kit diagnostics and retry.");
  }'''),
)
write(common / "actions.js", actions)

bridge = adapt(
    read(source / "bridge.py"),
    ('import ctypes\n', 'import ctypes\nfrom kit_log import record\n'),
    ("str(Path(__file__).parent/'vendor')", "str(Path(__file__).parents[3]/'mods'/'herdr-kit-pdf'/'vendor')"),
    ("'personal-files'", "'herdr-mod-kit'/'files'"),
    ("Reinstall the personal-files helper.", "Run the PDF diagnostics."),
    ('    parser=argparse.ArgumentParser()', '    global active_log\n    parser=argparse.ArgumentParser()'),
    ("    unfinished=False\n    try:", """    unfinished=False
    feature = 'pdf' if action in ('preview', 'render', 'revision', 'image', 'text') else 'transfer'
    active_log = (args.home, feature, action, job)
    if action != 'revision':
        record(args.home, feature, action, 'start', job)
    try:"""),
    ("    print(json.dumps({'ok':True,**result},ensure_ascii=False,separators=(',',':')))",
     """    if action != 'revision':
        record(args.home, feature, action, 'partial' if unfinished else 'ok', job)
    print(json.dumps({'ok':True,**result},ensure_ascii=False,separators=(',',':')))"""),
    ("    try:main()", "    active_log = None\n    try:main()"),
    ("    except Exception as e:\n        print(json.dumps({'ok':False,",
     """    except Exception as e:
        if active_log:
            root, feature, action, job = active_log
            record(root, feature, action, getattr(e, 'code', type(e).__name__), job)
        print(json.dumps({'ok':False,"""),
)
write(common / "bridge.py", bridge)
shutil.copy2(source / "file_host.py",common / "file_host.py")

usage_main = adapt(
    read(work / "lab-usage" / "main.js"),
    ('lab-weekly-usage', 'herdr-kit-usage'),
    ('return {machine:"lab", python:"python3"};',
     'return JSON.parse(await readTextFile(`${appHome()}/data/herdr-mod-kit/helpers/runtime.json`));'),
    ('    if (code !== "ok") console.error(`[${MOD}] ${provider} ${code}`);', '''    this.reported ??= {};
    const key = cacheKey(provider, host);
    if (this.reported[key] === code) return;
    this.reported[key] = code;
    const fallback = () => console.error(`[herdr-kit/usage] ${provider} ${code}`);
    const home = appHome();
    exec(this.config.python, ["-X", "utf8", `${home}/data/herdr-mod-kit/helpers/kit_log.py`, home, "usage", provider, code], {on:null, timeout:5000})
      .then(result => { if (result.code !== 0) fallback(); }, fallback);'''),
)
write(usage / "main.js", usage_main)
shutil.copy2(work / "lab-usage" / "codex.svg", usage / "codex.svg")
collector = adapt(
    read(work / "lab-usage" / "collect.py"),
    ('Run on lab', 'Run on the configured usage host'),
    ('Herdr-Lab-Usage/1.0', 'Herdr-Mod-Kit-Usage/1.1'),
    ("{'error': '구독 로그인 필요'}", "{'error': 'Subscription login required', 'code': 'login_required'}"),
    ("{'error': '응답 크기 초과'}", "{'error': 'Usage response too large', 'code': 'response_too_large'}"),
    ("{'error': 'lab 로그인 파일 없음'}", "{'error': 'Login file missing', 'code': 'login_file_missing'}"),
    ("{'error': 'Rate limited', 'status': 429", "{'error': 'Rate limited', 'code': 'http_429', 'status': 429"),
    ("{'error': {401: 'lab 재로그인 필요', 403: '사용량 조회 거부', 429: '요청 제한 · 잠시 후 재시도'}.get(error.code, '조회 오류 HTTP ' + str(error.code))}",
     "{'code': f'http_{error.code}', 'error': {401: 'Sign in again', 403: 'Usage access denied'}.get(error.code, f'Usage HTTP {error.code}')}"),
    ("{'error': '주간 사용량 확인 불가'}", "{'error': 'Weekly usage unavailable', 'code': 'weekly_unavailable'}"),
    ("{'error': 'lab 사용량 연결 실패'}", "{'error': 'Usage request failed', 'code': 'network_error'}"),
)
write(usage / "collect.py", collector)

for item in (source / "vendor").iterdir():
    if item.name in {"pypdfium2", "pypdfium2_raw", "pypdfium2_cfg"} or item.name.endswith(".dist-info"):
        shutil.copytree(item, pdf / "vendor" / item.name, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
