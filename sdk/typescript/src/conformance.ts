/** Conformance runner: node dist/conformance.js [store.sqlite] [cases.json]. Exit 1 on any mismatch. */
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { Store, OpsError } from "./store.js";

const sha = (s: string) => createHash("sha256").update(s).digest("hex").slice(0, 16);

export function runCase(store: Store, op: string, a: Record<string, any>): Record<string, any> {
  try {
    switch (op) {
      case "index": return { text_sha: sha(store.index(a.prefix)) };
      case "search": { const r = store.search(a.query, a.in, a.limit ?? 10, a.mode ?? "lexical"); return { ids: r.hits.map((h) => h.id), mode: r.mode, empty: r.hits.length === 0 }; }
      case "read": { const r = store.read(a.id, a.context ?? 0); return { id: r.id, text_sha: sha(r.text), heading_path: r.heading_path, context_ids: r.context.map((c) => c.id), prev: r.prev_id, next: r.next_id }; }
      case "grep": { const r = store.grep(a.pattern, a.in, false, a.limit ?? 20); return { ids: r.matches.map((m) => m.id), lines_sha: r.matches.map((m) => sha(m.line)), truncated: r.truncated }; }
      case "neighbours": { const r = store.neighbours(a.id, a.before ?? 1, a.after ?? 1); return { ids: r.sections.map((s) => s.id), header: r.header?.id ?? null }; }
    }
  } catch (e) { if (e instanceof OpsError) return { error: true }; throw e; }
  throw new Error(`unknown op ${op}`);
}

const stable = (v: unknown): string => JSON.stringify(v, (_k, val) => (val && typeof val === "object" && !Array.isArray(val)) ? Object.keys(val).sort().reduce((o: any, k) => (o[k] = val[k], o), {}) : val);

export function check(storePath: string, casesPath: string): number {
  const data = JSON.parse(readFileSync(casesPath, "utf8"));
  const store = Store.open(storePath);
  let failures = 0;
  for (const c of data.cases) {
    const got = runCase(store, c.op, c.args);
    if (stable(got) !== stable(c.expect)) { failures++; console.log(`FAIL ${c.op} ${JSON.stringify(c.args)}\n  expect ${stable(c.expect)}\n  got    ${stable(got)}`); }
  }
  console.log(`${data.cases.length - failures}/${data.cases.length} conformance cases pass (node)`);
  store.close();
  return failures ? 1 : 0;
}

if (process.argv[1] && process.argv[1].endsWith("conformance.js")) {
  const store = process.argv[2] ?? "../../conformance/store.sqlite";
  const cases = process.argv[3] ?? "../../conformance/cases.json";
  process.exit(check(store, cases));
}
