// contextpull-server: single-binary MCP server over a ContextPull store.
//
//	contextpull-server serve <store.sqlite> [--log]                 stdio (Claude Code and other local hosts)
//	contextpull-server serve <store.sqlite> --http 127.0.0.1:8765  streamable HTTP at /mcp (shared read-only deployment)
//	contextpull-server search <store.sqlite> <query>                quick check from the command line
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"strings"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	contextpull "github.com/mi2arun/contextpull/sdk/go"
)

const preamble = "ContextPull gives you exact sections from a document corpus. The index below lists every document. " +
	"Search for pointers (ids + snippets), read the sections you need verbatim, then answer citing ids like [path.md#3]. " +
	"For comparisons search each document with in=[...] and read both. For codes, flags and identifiers use grep.\n\n"

const indexURI = "contextpull://index"

func text(v any) *mcp.CallToolResult {
	var s string
	if str, ok := v.(string); ok {
		s = str
	} else {
		b, _ := json.Marshal(v)
		s = string(b)
	}
	return &mcp.CallToolResult{Content: []mcp.Content{&mcp.TextContent{Text: s}}}
}

func buildServer(store *contextpull.Store, logCalls bool) *mcp.Server {
	instructions := preamble + store.Meta("index_text")
	if store.Meta("index_text") == "" {
		instructions = preamble + "(index empty: run contextpull ingest)"
	}
	srv := mcp.NewServer(&mcp.Implementation{Name: "contextpull", Version: "0.2.1"}, &mcp.ServerOptions{Instructions: instructions})
	_, tools := contextpull.Tools()
	for _, t := range tools {
		name := t.Name
		srv.AddTool(&mcp.Tool{Name: t.Name, Description: t.Description, InputSchema: t.InputSchema}, func(ctx context.Context, req *mcp.CallToolRequest) (*mcp.CallToolResult, error) {
			args := map[string]any{}
			if len(req.Params.Arguments) > 0 {
				if err := json.Unmarshal(req.Params.Arguments, &args); err != nil {
					r := text(map[string]any{"error": "arguments must be a JSON object", "suggestion": "check the argument types against the tool schema"})
					r.IsError = true
					return r, nil
				}
			}
			out, err := store.Call(name, args)
			if logCalls {
				a, _ := json.Marshal(args)
				log.Printf("%s %s -> err=%v", name, a, err)
			}
			if err != nil {
				payload := map[string]any{"error": err.Error(), "suggestion": "check the argument types against the tool schema"}
				if oe, ok := err.(*contextpull.OpsError); ok {
					payload = map[string]any{"error": oe.Message, "suggestion": oe.Suggestion}
				}
				r := text(payload)
				r.IsError = true
				return r, nil
			}
			return text(out), nil
		})
	}
	docs, secs := store.Counts()
	srv.AddResource(&mcp.Resource{Name: "index", URI: indexURI, MIMEType: "text/plain",
		Description: fmt.Sprintf("Table of contents: %d documents, %d sections. Same text as the server instructions.", docs, secs)},
		func(ctx context.Context, req *mcp.ReadResourceRequest) (*mcp.ReadResourceResult, error) {
			return &mcp.ReadResourceResult{Contents: []*mcp.ResourceContents{{URI: indexURI, MIMEType: "text/plain", Text: store.Index("")}}}, nil
		})
	return srv
}

func main() {
	log.SetOutput(os.Stderr)
	if len(os.Args) < 3 {
		fmt.Fprintln(os.Stderr, "usage: contextpull-server serve <store.sqlite> [--log] [--http host:port] | search <store.sqlite> <query>")
		os.Exit(2)
	}
	cmd, storePath := os.Args[1], os.Args[2]
	store, err := contextpull.Open(storePath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
	defer store.Close()

	switch cmd {
	case "search":
		r, err := store.Search(strings.Join(os.Args[3:], " "), nil, 10, "lexical")
		if err != nil {
			fmt.Fprintln(os.Stderr, "error:", err)
			os.Exit(2)
		}
		b, _ := json.MarshalIndent(r, "", "  ")
		fmt.Println(string(b))
	case "serve":
		fs := flag.NewFlagSet("serve", flag.ExitOnError)
		logCalls := fs.Bool("log", false, "log one line per tool call to stderr")
		httpAddr := fs.String("http", "", "serve streamable HTTP at this host:port instead of stdio")
		_ = fs.Parse(os.Args[3:])
		srv := buildServer(store, *logCalls)
		docs, secs := store.Counts()
		if *httpAddr != "" {
			handler := mcp.NewStreamableHTTPHandler(func(*http.Request) *mcp.Server { return srv }, &mcp.StreamableHTTPOptions{Stateless: true})
			mux := http.NewServeMux()
			mux.Handle("/mcp", handler)
			log.Printf("contextpull (go) serving %s at http://%s/mcp (%d documents, %d sections)", storePath, *httpAddr, docs, secs)
			log.Fatal(http.ListenAndServe(*httpAddr, mux))
		}
		if *logCalls {
			log.Printf("contextpull (go) serving %s over stdio (%d documents, %d sections)", storePath, docs, secs)
		}
		if err := srv.Run(context.Background(), &mcp.StdioTransport{}); err != nil {
			log.Fatal(err)
		}
	default:
		fmt.Fprintln(os.Stderr, "unknown command", cmd)
		os.Exit(2)
	}
}
