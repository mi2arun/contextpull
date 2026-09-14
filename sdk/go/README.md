# contextpull (Go)

Store-native Go reader and single-binary MCP server for [ContextPull](https://github.com/mi2arun/contextpull) stores. Pure Go (`modernc.org/sqlite`, no cgo), so it cross-compiles to one static file for the shared, read-only deployment. Correctness is defined by the shared conformance suite: `go run ./cmd/contextpull-conformance`.

```sh
go build -o contextpull-server ./cmd/contextpull-server
./contextpull-server serve /data/store.sqlite                        # stdio, for Claude Code and other local hosts
./contextpull-server serve /data/store.sqlite --http 0.0.0.0:8765   # streamable HTTP at /mcp
./contextpull-server search /data/store.sqlite "refund window"      # quick check
```

```go
import contextpull "github.com/mi2arun/contextpull/sdk/go"

store, err := contextpull.Open("/data/store.sqlite")
res, err := store.Search("refund window", []string{"policies/*"}, 10, "lexical")
sec, err := store.Read(res.Hits[0].ID, 0)
```

The store is built by the Python reference (`uvx contextpull ingest`); this module only reads. `tools.json` is embedded and must match the repo root (CI checks).
