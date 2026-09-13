// Protocol client (Tier 0): talk to the Python ContextPull server over stdio.
// Usage: CONTEXTPULL_STORE=/path/store.sqlite go run .
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"os/exec"
	"strings"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

func main() {
	ctx := context.Background()
	store := os.Getenv("CONTEXTPULL_STORE")
	if store == "" {
		store = ".contextpull/store.sqlite"
	}
	client := mcp.NewClient(&mcp.Implementation{Name: "example-go", Version: "0.1.0"}, nil)
	cmdline := os.Getenv("CONTEXTPULL_CMD")
	if cmdline == "" {
		cmdline = "uvx contextpull serve"
	}
	parts := append(strings.Fields(cmdline), store)
	session, err := client.Connect(ctx, &mcp.CommandTransport{Command: exec.Command(parts[0], parts[1:]...)}, nil)
	if err != nil {
		log.Fatal(err)
	}
	defer session.Close()

	fmt.Println("--- instructions (first line) ---")
	if init := session.InitializeResult(); init != nil {
		fmt.Println(firstLine(init.Instructions))
	}

	res, err := session.CallTool(ctx, &mcp.CallToolParams{Name: "search", Arguments: map[string]any{
		"query": "refund window", "in": []string{"policies/policy-2024.md", "policies/policy-2025.md"}}})
	if err != nil {
		log.Fatal(err)
	}
	var out struct {
		Hits []struct {
			ID          string `json:"id"`
			HeadingPath string `json:"heading_path"`
		} `json:"hits"`
	}
	_ = json.Unmarshal([]byte(res.Content[0].(*mcp.TextContent).Text), &out)
	for _, h := range out.Hits[:2] {
		fmt.Printf("--- hit %s · %s\n", h.ID, h.HeadingPath)
		r, err := session.CallTool(ctx, &mcp.CallToolParams{Name: "read", Arguments: map[string]any{"id": h.ID}})
		if err != nil {
			log.Fatal(err)
		}
		fmt.Printf("--- read %s ---\n%s\n", h.ID, r.Content[0].(*mcp.TextContent).Text)
	}
}

func firstLine(s string) string {
	for i, c := range s {
		if c == '\n' {
			return s[:i]
		}
	}
	return s
}
