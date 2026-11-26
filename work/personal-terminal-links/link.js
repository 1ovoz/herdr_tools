import { exec, notify } from "herdr";
import { routeDocument } from "../personal-files/document-drag.js";

const RESOLVE_REMOTE = `
import json, os, re, sys
from pathlib import Path

raw, cwd = sys.argv[1:]
for spelling in (raw, re.sub(r'(?::[0-9]+){1,2}$', '', raw)):
    if spelling.startswith(('$HOME/', '$PWD/')):
        name, rest = spelling.split('/', 1)
        base = str(Path.home()) if name == '$HOME' else cwd
        if not base:
            continue
        spelling = os.path.join(base, rest)
    path = Path(spelling).expanduser()
    if not path.is_absolute():
        if not cwd:
            continue
        path = Path(cwd) / path
    if path.is_file():
        print(json.dumps(str(path)))
        break
`;

function remoteSpelling(raw, machine) {
  if (!raw.startsWith("file:")) return raw;
  const match = /^file:\/\/([^/]*)(\/[^?#]*)/i.exec(raw);
  if (!match) return null;
  const [, host, path] = match;
  if (host && !["localhost", machine.toLowerCase()].includes(host.toLowerCase())) return null;
  try { return decodeURIComponent(path); }
  catch { return null; }
}

export async function handleLink({link, source}) {
  if (link.kind !== "file" || !source.space) return "pass";
  if (!source.machine && [link.raw,link.path].some(externalFileLink)) {
    notify({title:"Network file link blocked",body:"Open the file through its connected Herdr machine.",level:"warning"});
    return "handled";
  }
  let path = link.path;
  if (source.machine) {
    const spelling = remoteSpelling(link.raw, source.machine);
    if (!spelling || spelling.includes("\0")) return "pass";
    try {
      // -I: the machine's home folder is the working directory and must not supply modules.
      const result = await exec("python3", ["-I", "-c", RESOLVE_REMOTE, spelling, source.cwd || ""],
        { on: source.machine, timeout: 9000 });
      path = result.code === 0 && result.stdout.trim() ? JSON.parse(result.stdout) : null;
    } catch { path = null; }
    if (!path) {
      notify({title:"Could not open document",body:"Check that the file still exists on the connected machine.",level:"warning"});
      return "handled";
    }
  }
  if (!path) return "pass";
  const name = path.split(/[\\/]/).pop();
  if (!name) return "pass";
  routeDocument({name,source:path,on:source.machine,mode:/\.pdf$/i.test(name)?"pdf":"document"},
    source.space,source.tab,source.pane);
  return "handled";
}

function externalFileLink(value) {
  if (!value) return false;
  let path=value.replace(/\\/g,"/");
  if (/^file:/i.test(path)) {
    try { path=decodeURIComponent(path.slice(5)).replace(/\\/g,"/"); }
    catch { return true; }
    // A drive URL has three slashes. Four slashes can encode a UNC path.
    if (/^\/\/\/(?!\/)/.test(path)) return false;
  }
  if (!path.startsWith("//")) return false;
  const host=path.replace(/^\/+/,"").split("/")[0].toLowerCase();
  return !["localhost","wsl.localhost","wsl$"].includes(host);
}
