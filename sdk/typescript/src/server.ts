/**
 * Native MCP server over a ContextPull store: same tools, same instructions,
 * same index delivery as the Python server, no Python at query time.
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListResourcesRequestSchema, ListToolsRequestSchema, ReadResourceRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import { Store, OpsError, callTool } from "./store.js";
import { TOOLS } from "./tools.js";

export const INDEX_URI = "contextpull://index";
export const PREAMBLE =
  "ContextPull gives you exact sections from a document corpus. The index below lists every document. " +
  "Search for pointers (ids + snippets), read the sections you need verbatim, then answer citing ids like [path.md#3]. " +
  "For comparisons search each document with in=[...] and read both. For codes, flags and identifiers use grep.\n\n";

export function instructionsText(store: Store): string {
  return PREAMBLE + (store.meta("index_text") ?? "(index empty: run contextpull ingest)");
}

export function buildServer(store: Store, log = false): Server {
  const { documents, sections } = store.counts();
  const server = new Server({ name: "contextpull", version: "0.2.0" }, { capabilities: { tools: {}, resources: {} }, instructions: instructionsText(store) });

  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: TOOLS.map((t) => ({ name: t.name, description: t.description, inputSchema: t.input_schema })),
  }));

  server.setRequestHandler(CallToolRequestSchema, async (req) => {
    const t0 = performance.now();
    const args = (req.params.arguments ?? {}) as Record<string, any>;
    try {
      const out = callTool(store, req.params.name, args);
      const text = typeof out === "string" ? out : JSON.stringify(out);
      if (log) console.error(`${req.params.name} ${JSON.stringify(args).slice(0, 120)} in ${(performance.now() - t0).toFixed(1)} ms`);
      return { content: [{ type: "text", text }] };
    } catch (e) {
      const payload = e instanceof OpsError ? e.toJSON() : { error: `${(e as Error).name}: ${(e as Error).message}`, suggestion: "check the argument types against the tool schema" };
      if (log) console.error(`${req.params.name} -> error: ${payload.error}`);
      return { content: [{ type: "text", text: JSON.stringify(payload) }], isError: true };
    }
  });

  server.setRequestHandler(ListResourcesRequestSchema, async () => ({
    resources: [{ name: "index", uri: INDEX_URI, title: "ContextPull index", mimeType: "text/plain", description: `Table of contents: ${documents} documents, ${sections} sections. Same text as the server instructions.` }],
  }));
  server.setRequestHandler(ReadResourceRequestSchema, async (req) => {
    if (req.params.uri !== INDEX_URI) throw new Error(`unknown resource ${req.params.uri}; only ${INDEX_URI} exists`);
    return { contents: [{ uri: INDEX_URI, mimeType: "text/plain", text: store.index() }] };
  });
  return server;
}

export async function serveStdio(storePath: string, log = false): Promise<void> {
  const store = Store.open(storePath);
  const server = buildServer(store, log);
  if (log) { const c = store.counts(); console.error(`contextpull (node) serving ${storePath}: ${c.documents} documents, ${c.sections} sections`); }
  const transport = new StdioServerTransport();
  await server.connect(transport);
  // connect() returns once the transport is started; stay alive until the client goes away.
  await new Promise<void>((resolve) => { server.onclose = () => resolve(); transport.onclose = () => resolve(); process.stdin.on("end", () => resolve()); });
  store.close();
}
