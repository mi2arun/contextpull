#!/usr/bin/env node
// npx contextpull serve <store.sqlite> [--log]   — native Node MCP server over a ContextPull store
// npx contextpull index|search|read|grep|neighbours … — read a store from the command line
// npx contextpull ingest …                        — delegates to the Python reference (uvx contextpull ingest)
import { spawnSync } from "node:child_process";
import { serveStdio, Store, callTool } from "../dist/index.js";

const [cmd, ...rest] = process.argv.slice(2);
const flag = (name) => { const i = rest.indexOf(name); if (i >= 0) { const v = rest[i + 1]; rest.splice(i, 2); return v; } return undefined; };
const bool = (name) => { const i = rest.indexOf(name); if (i >= 0) { rest.splice(i, 1); return true; } return false; };

async function main() {
  if (!cmd || cmd === "--help" || cmd === "-h") {
    console.log("usage: contextpull serve <store.sqlite> [--log] | index [prefix] | search <query> [--in path]... | read <id> [--context n] | grep <pattern> | neighbours <id> | ingest <dir> (Python)\n  --store <file> (default $CONTEXTPULL_STORE or .contextpull/store.sqlite)");
    return 0;
  }
  if (cmd === "ingest") {
    const r = spawnSync("uvx", ["contextpull", "ingest", ...rest], { stdio: "inherit" });
    if (r.error) { console.error("ingest needs the Python reference implementation: install uv, then `uvx contextpull ingest <dir>`"); return 1; }
    return r.status ?? 1;
  }
  const log = bool("--log");
  const storeArg = flag("--store");
  if (cmd === "serve") { await serveStdio(rest[0] ?? storeArg ?? process.env.CONTEXTPULL_STORE ?? ".contextpull/store.sqlite", log); return 0; }
  const store = Store.open(storeArg ?? process.env.CONTEXTPULL_STORE ?? ".contextpull/store.sqlite");
  const json = bool("--json");
  const ins = []; let v; while ((v = flag("--in")) !== undefined) ins.push(v);
  const args = { index: { prefix: rest[0] }, search: { query: rest[0], in: ins.length ? ins : undefined, limit: Number(flag("--limit") ?? 10) },
    read: { id: rest[0], context: Number(flag("--context") ?? 0) }, grep: { pattern: rest[0], in: ins.length ? ins : undefined, regex: bool("--regex"), limit: Number(flag("--limit") ?? 20) },
    neighbours: { id: rest[0], before: Number(flag("--before") ?? 1), after: Number(flag("--after") ?? 1) } }[cmd];
  if (!args) { console.error(`unknown command ${cmd}`); return 2; }
  try {
    const out = callTool(store, cmd, args);
    console.log(typeof out === "string" ? out : JSON.stringify(out, null, json ? 2 : 0));
    return 0;
  } catch (e) { console.error(`error: ${e.message}${e.suggestion ? ` (${e.suggestion})` : ""}`); return 2; }
}
process.exit(await main());
