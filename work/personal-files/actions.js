import { appHome, exec, readTextFile } from "herdr";

export const jobId = () => Array.from({length:32}, () => Math.floor(Math.random()*16).toString(16)).join("");

export async function bridge(request) {
  const home = appHome();
  const config = JSON.parse(await readTextFile(`${home}/mods/personal-files/runtime.json`));
  const result = await exec(config.python, ["-X", "utf8", `${home}/mods/personal-files/bridge.py`, "--hc", config.hc, "--home", home, "--request", JSON.stringify(request)], { timeout: 600000 });
  if (result.code !== 0) throw new Error("File helper stopped. Check the host connection and retry.");
  try { return JSON.parse(result.stdout); }
  catch { throw new Error("The file helper did not return a valid result."); }
}

export function uploadRequests(paths, directory, on) {
  return paths.map(source => ({action:"upload",source,directory,on,job:jobId()}));
}
