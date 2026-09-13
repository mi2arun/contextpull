/** Tool definitions, embedded verbatim from ../../tools.json at build time (one definition, every surface). */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

export interface ToolDef { name: string; description: string; input_schema: Record<string, any> }

function load(): { version: string; tools: ToolDef[] } {
  const here = dirname(fileURLToPath(import.meta.url));
  for (const candidate of [join(here, "tools.json"), join(here, "..", "tools.json"), join(here, "..", "..", "..", "tools.json")]) {
    try { return JSON.parse(readFileSync(candidate, "utf8")); } catch { /* try next */ }
  }
  throw new Error("tools.json not found next to the package; run `npm run build`");
}

const loaded = load();
export const TOOLS_VERSION: string = loaded.version;
export const TOOLS: ToolDef[] = loaded.tools;
