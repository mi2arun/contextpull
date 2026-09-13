/**
 * Store-native reader: implements docs/store-format.md over better-sqlite3.
 * Read-only. Passing the conformance suite (src/conformance.ts) is the definition of correct.
 */
import Database from "better-sqlite3";

export const SUPPORTED_MAJOR = "1";

export interface Hit { id: string; doc: string; heading_path: string; snippet: string; score: number; kind: string }
export interface SearchResult { hits: Hit[]; mode: "lexical"; hint: string | null }
export interface Section { id: string; doc: string; heading_path: string; kind: string; text: string; prev_id: string | null; next_id: string | null; context: boolean }
export interface ReadResult extends Omit<Section, "context"> { context: Section[] }
export interface Match { id: string; doc: string; heading_path: string; line: string }
export interface GrepResult { matches: Match[]; truncated: boolean }
export interface NeighboursResult { sections: Section[]; header: Section | null }

export class OpsError extends Error {
  constructor(message: string, public suggestion: string | null = null) { super(message); }
  toJSON() { return { error: this.message, suggestion: this.suggestion }; }
}

const TOKEN_RE = /[^\W_][\w.\-]*/gu;
const LEAD = /(?<![\w.\-])[-_.]+(?=\w)/gu;
const TRAIL = /(?<=\w)[-_.]+(?![\w.\-])/gu;

/** Same normalisation ingest applied to the indexed columns (store-format.md, Tokenisation). */
export function normalizeForFts(text: string): string {
  return text.replace(LEAD, "").replace(TRAIL, "");
}

export function tokenize(text: string): string[] {
  const out: string[] = [];
  for (const m of normalizeForFts(text.toLowerCase()).matchAll(TOKEN_RE)) {
    const t = m[0].replace(/^[._-]+|[._-]+$/g, "");
    if (t) out.push(t);
  }
  return out;
}

const ftsString = (tok: string) => `"${tok.replace(/"/g, '""')}"`;

function globClause(paths?: string[] | null): { where: string; args: string[] } {
  if (!paths || paths.length === 0) return { where: "", args: [] };
  const parts: string[] = []; const args: string[] = [];
  for (const p of paths) {
    if (typeof p !== "string" || !p) throw new OpsError(`invalid path filter ${JSON.stringify(p)}`, "pass document paths or globs as shown in the index");
    parts.push("d.path GLOB ?"); args.push(p);
    if (!/[*?[]/.test(p)) { parts.push("d.path GLOB ?"); args.push(p.replace(/\/+$/, "") + "/*"); }
  }
  return { where: " AND (" + parts.join(" OR ") + ")", args };
}

type Row = Record<string, any>;

export class Store {
  private db: Database.Database;
  private constructor(db: Database.Database, public readonly path: string) { this.db = db; }

  static open(path: string): Store {
    let db: Database.Database;
    try { db = new Database(path, { readonly: true, fileMustExist: true }); }
    catch (e) { throw new OpsError(`no store at ${path}; run \`contextpull ingest <corpus>\` first`); }
    let version: string | undefined;
    try { version = (db.prepare("SELECT value FROM meta WHERE key='schema_version'").get() as Row | undefined)?.value; }
    catch { db.close(); throw new OpsError(`${path} is not a ContextPull store`); }
    if (!version) { db.close(); throw new OpsError(`${path} is not a ContextPull store (no schema_version)`); }
    if (version.split(".")[0] !== SUPPORTED_MAJOR) { db.close(); throw new OpsError(`store ${path} has schema ${version}; this reader supports ${SUPPORTED_MAJOR}.x`); }
    try { db.prepare("SELECT count(*) FROM sections_fts LIMIT 1").get(); }
    catch { db.close(); throw new OpsError("this SQLite build lacks FTS5; ContextPull needs an FTS5-enabled SQLite"); }
    return new Store(db, path);
  }

  close(): void { this.db.close(); }
  meta(key: string): string | null { return (this.db.prepare("SELECT value FROM meta WHERE key=?").get(key) as Row | undefined)?.value ?? null; }
  counts(): { documents: number; sections: number } {
    return { documents: (this.db.prepare("SELECT count(*) c FROM documents").get() as Row).c, sections: (this.db.prepare("SELECT count(*) c FROM sections").get() as Row).c };
  }

  // ---------------------------------------------------------------- index
  index(prefix?: string | null): string {
    if (!prefix) return this.meta("index_text") ?? "";
    const like = prefix.replace(/[\\%_]/g, (c) => "\\" + c) + "%";
    const agg = this.db.prepare("SELECT count(*) n, coalesce(sum(n_sections),0) m FROM documents WHERE path LIKE ? ESCAPE '\\'").get(like) as Row;
    const rows = this.db.prepare("SELECT path, title, summary, n_sections FROM documents WHERE path LIKE ? ESCAPE '\\' ORDER BY path").all(like) as Row[];
    const lines = rows.map((r) => docLine(r.path, r.title, r.summary, r.n_sections));
    return [`ContextPull index · ${prefix || "/"} · ${agg.n} documents · ${agg.m} sections`, ...lines].join("\n");
  }

  // --------------------------------------------------------------- search
  search(query: string, in_?: string[] | null, limit = 10, mode: "lexical" | "hybrid" = "lexical"): SearchResult {
    limit = Math.max(1, Math.min(Number(limit) || 10, 50));
    const toks = tokenize(query ?? "");
    if (toks.length === 0) return { hits: [], mode: "lexical", hint: "no searchable words in query" };
    const { where, args } = globClause(in_);
    const queries: string[] = [];
    if (toks.length >= 2) { queries.push(ftsString(toks.join(" "))); queries.push(toks.map(ftsString).join(" AND ")); }
    queries.push(toks.map(ftsString).join(" OR "));
    const stmt = this.db.prepare(`SELECT f.id, d.path, s.heading_path, s.kind,
        snippet(sections_fts, 2, '**', '**', '…', 20) AS snip, bm25(sections_fts, 0.0, 2.0, 1.0) AS rank
      FROM sections_fts f JOIN sections s ON s.id = f.id JOIN documents d ON d.doc_id = s.doc_id
      WHERE sections_fts MATCH ?${where} ORDER BY rank, f.id LIMIT ?`);
    const seen = new Set<string>(); const hits: Hit[] = [];
    for (const q of queries) {
      if (hits.length >= limit) break;
      for (const r of stmt.all(q, ...args, limit) as Row[]) {
        if (seen.has(r.id)) continue;
        seen.add(r.id);
        hits.push({ id: r.id, doc: r.path, heading_path: r.heading_path, snippet: String(r.snip).split(/\s+/).join(" ").trim(), score: Math.round(-r.rank * 100) / 100, kind: r.kind });
        if (hits.length >= limit) break;
      }
    }
    let hint: string | null = null;
    if (mode === "hybrid") hint = "no embeddings in store; ran lexical";
    if (hits.length === 0) hint = "no hits; try grep for exact codes, drop the in= filter, or use fewer words";
    return { hits, mode: "lexical", hint };
  }

  // ----------------------------------------------------------------- read
  private getRow(id: string): Row {
    const r = this.db.prepare("SELECT s.*, d.path FROM sections s JOIN documents d ON d.doc_id = s.doc_id WHERE s.id = ?").get(id) as Row | undefined;
    if (!r) throw new OpsError(`no section '${id}'`, "search for it first; ids look like path.md#3");
    return r;
  }
  private toSection(r: Row, context = false): Section {
    return { id: r.id, doc: r.path, heading_path: r.heading_path, kind: r.kind, text: r.text, prev_id: r.prev_id ?? null, next_id: r.next_id ?? null, context };
  }
  private tableHeader(r: Row): Row | null {
    if (r.kind !== "table") return null;
    let first = r;
    while (first.prev_id) {
      const prev = this.getRow(first.prev_id);
      if (prev.kind === "table" && prev.heading_path === r.heading_path) first = prev; else break;
    }
    return first.id === r.id ? null : first;
  }

  read(id: string, context = 0): ReadResult {
    const r = this.getRow(id);
    const sec = this.toSection(r);
    const header = this.tableHeader(r);
    if (header) {
      const head = String(header.text).split("\n").filter((l) => l.trimStart().startsWith("|")).slice(0, 2).join("\n");
      if (head && !sec.text.startsWith(head)) sec.text = head + "\n" + sec.text;
    }
    const n = Math.max(0, Math.min(Number(context) || 0, 5));
    let ctx: Section[] = [];
    if (n) {
      const rows = this.db.prepare(`SELECT s.*, d.path FROM sections s JOIN documents d ON d.doc_id = s.doc_id
        WHERE s.doc_id = ? AND s.ordinal BETWEEN ? AND ? AND s.id != ? ORDER BY s.ordinal`).all(r.doc_id, r.ordinal - n, r.ordinal + n, id) as Row[];
      ctx = rows.map((x) => this.toSection(x, true));
    }
    const { context: _c, ...rest } = sec;
    return { ...rest, context: ctx };
  }

  // ----------------------------------------------------------------- grep
  grep(pattern: string, in_?: string[] | null, regex = false, limit = 20): GrepResult {
    if (!pattern || pattern.length > 200) throw new OpsError("pattern must be 1–200 characters", "narrow the pattern");
    limit = Math.max(1, Math.min(Number(limit) || 20, 100));
    const { where, args } = globClause(in_);
    const rows = regex
      ? (this.db.prepare(`SELECT s.id, d.path, s.heading_path, s.text FROM sections s JOIN documents d ON d.doc_id = s.doc_id WHERE 1=1${where} ORDER BY s.id`).all(...args) as Row[])
      : (this.db.prepare(`SELECT s.id, d.path, s.heading_path, s.text FROM sections s JOIN documents d ON d.doc_id = s.doc_id WHERE instr(lower(s.text), ?) > 0${where} ORDER BY s.id`).all(pattern.toLowerCase(), ...args) as Row[]);
    let re: RegExp | null = null;
    if (regex) { try { re = new RegExp(pattern, "i"); } catch (e) { throw new OpsError(`pattern does not compile: ${(e as Error).message}`, "set regex=false for a literal match"); } }
    const needle = pattern.toLowerCase();
    const matches: Match[] = []; let truncated = false; let scanned = 0;
    for (const r of rows) {
      if (regex) { scanned += r.text.length; if (scanned > 200_000) throw new OpsError("pattern too expensive", "narrow with in= or use a literal pattern"); }
      for (const line of String(r.text).split("\n")) {
        const ok = re ? re.test(line) : line.toLowerCase().includes(needle);
        if (ok) {
          if (matches.length >= limit) { truncated = true; break; }
          matches.push({ id: r.id, doc: r.path, heading_path: r.heading_path, line: line.trim() });
          break;
        }
      }
      if (truncated) break;
    }
    return { matches, truncated };
  }

  // ----------------------------------------------------------- neighbours
  neighbours(id: string, before = 1, after = 1): NeighboursResult {
    const r = this.getRow(id);
    before = Math.max(0, Math.min(Number(before) || 0, 5)); after = Math.max(0, Math.min(Number(after) || 0, 5));
    const rows = this.db.prepare(`SELECT s.*, d.path FROM sections s JOIN documents d ON d.doc_id = s.doc_id
      WHERE s.doc_id = ? AND s.ordinal BETWEEN ? AND ? ORDER BY s.ordinal`).all(r.doc_id, r.ordinal - before, r.ordinal + after) as Row[];
    const header = this.tableHeader(r);
    return { sections: rows.map((x) => this.toSection(x)), header: header ? this.toSection(header) : null };
  }
}

function docLine(path: string, title: string, summary: string | null, n: number, compact = false): string {
  const padded = path.padEnd(30);
  if (compact) return `${padded}  (${n})`;
  let label = (summary || title || "").trim();
  if (label.length > 60) label = label.slice(0, 59).trimEnd() + "…";
  return `${padded}  ${label}  (${n})`;
}

/** Dispatch a tool call by name; mirrors contextpull.tools.call in Python. */
export function callTool(store: Store, name: string, args: Record<string, any>): string | object {
  const a = args ?? {};
  switch (name) {
    case "index": return store.index(a.prefix);
    case "search": return store.search(a.query, a.in, a.limit ?? 10, a.mode ?? "lexical");
    case "read": return store.read(a.id, a.context ?? 0);
    case "grep": return store.grep(a.pattern, a.in, Boolean(a.regex), a.limit ?? 20);
    case "neighbours": return store.neighbours(a.id, a.before ?? 1, a.after ?? 1);
    default: throw new OpsError(`unknown tool '${name}'`, "tools: index, search, read, grep, neighbours");
  }
}
