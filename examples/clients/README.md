# Protocol clients

Tier 0 of the [SDK plan](../../docs/sdk-plan.md): any language talks to the Python server over MCP stdio. Each example asks the same comparison question over the conformance corpus.

```sh
contextpull ingest conformance/corpus --store /tmp/cp.sqlite
export CONTEXTPULL_STORE=/tmp/cp.sqlite
```

| language | run | notes |
|---|---|---|
| TypeScript | `cd typescript && npm install && npm start` | official `@modelcontextprotocol/sdk` |
| Go | `cd go && go mod tidy && go run .` | official `github.com/modelcontextprotocol/go-sdk` |
| Java | `cd java && javac Client.java && java Client $CONTEXTPULL_STORE` | no SDK, raw JSON-RPC over stdio, shows the wire format |

All three launch the server with `uvx contextpull serve <store>` by default. Set `CONTEXTPULL_CMD` to override, e.g. `CONTEXTPULL_CMD="python -m contextpull.cli serve"` while the package is not on PyPI.
