// Protocol client (Tier 0): talk to the Python ContextPull server over stdio.
// Usage: CONTEXTPULL_STORE=/path/store.sqlite npm start
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const store = process.env.CONTEXTPULL_STORE ?? ".contextpull/store.sqlite";
const [cmd, ...cmdArgs] = (process.env.CONTEXTPULL_CMD ?? "uvx contextpull serve").split(" ");
const transport = new StdioClientTransport({ command: cmd, args: [...cmdArgs, store] });
const client = new Client({ name: "example-ts", version: "0.1.0" });
await client.connect(transport);

// The index arrives in the server's instructions: this is what a host puts in the system prompt.
console.log("--- instructions (first 5 lines) ---");
console.log((client.getInstructions() ?? "").split("\n").slice(0, 5).join("\n"));

// A comparison question: search both documents, read both, cite both.
const q = "refund window";
const found = await client.callTool({ name: "search", arguments: { query: q, in: ["policies/policy-2024.md", "policies/policy-2025.md"] } });
const hits = JSON.parse(found.content[0].text).hits;
console.log("--- search ---", hits.map(h => `${h.id} · ${h.heading_path}`));
for (const h of hits.slice(0, 2)) {
  const r = await client.callTool({ name: "read", arguments: { id: h.id } });
  console.log(`--- read ${h.id} ---\n` + JSON.parse(r.content[0].text).text);
}
await client.close();
