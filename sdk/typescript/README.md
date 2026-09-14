# contextpull (Node)

Store-native TypeScript reader and MCP server for [ContextPull](https://github.com/mi2arun/contextpull) stores. Opens the same SQLite file the Python reference writes; no Python at query time. Correctness is defined by the shared conformance suite.

```sh
uvx contextpull ingest ./docs                    # build the store (Python reference; ingest is not ported)
npx contextpull serve ./docs/.contextpull/store.sqlite
npx contextpull search "refund window" --in policy-2025.md
```

```ts
import { Store } from "contextpull";
const store = Store.open(".contextpull/store.sqlite");
const hits = store.search("refund window", ["policy-2024.md", "policy-2025.md"]).hits;
const section = store.read(hits[0].id);
```

Claude Code: `claude mcp add contextpull -- npx contextpull serve /path/store.sqlite`.

Install: `npm install contextpull` (or `npx contextpull …`). Develop: `npm install && npm run build && npm run conformance`.
