package contextpull

import (
	_ "embed"
	"encoding/json"
)

//go:embed tools.json
var toolsJSON []byte

// ToolDef is one entry of tools.json: the shared tool contract for every surface.
type ToolDef struct {
	Name        string         `json:"name"`
	Description string         `json:"description"`
	InputSchema map[string]any `json:"input_schema"`
}

// Tools returns the tool definitions embedded from tools.json (kept in sync with the repo root by CI).
func Tools() (version string, tools []ToolDef) {
	var doc struct {
		Version string    `json:"version"`
		Tools   []ToolDef `json:"tools"`
	}
	_ = json.Unmarshal(toolsJSON, &doc)
	return doc.Version, doc.Tools
}
