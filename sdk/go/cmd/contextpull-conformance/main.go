// Conformance runner: contextpull-conformance [store.sqlite] [cases.json]. Exit 1 on any mismatch.
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"reflect"

	contextpull "github.com/mi2arun/contextpull/sdk/go"
)

func sha(s string) string {
	h := sha256.Sum256([]byte(s))
	return hex.EncodeToString(h[:])[:16]
}

type tcase struct {
	Op     string         `json:"op"`
	Args   map[string]any `json:"args"`
	Expect map[string]any `json:"expect"`
}

func strs(k string, a map[string]any) []string {
	var out []string
	if xs, ok := a[k].([]any); ok {
		for _, x := range xs {
			out = append(out, x.(string))
		}
	}
	return out
}
func num(k string, a map[string]any, def int) int {
	if v, ok := a[k].(float64); ok {
		return int(v)
	}
	return def
}
func str(k string, a map[string]any) string {
	if v, ok := a[k].(string); ok {
		return v
	}
	return ""
}

func run(s *contextpull.Store, c tcase) map[string]any {
	errOut := func(err error) (map[string]any, bool) {
		if _, ok := err.(*contextpull.OpsError); ok {
			return map[string]any{"error": true}, true
		}
		if err != nil {
			panic(err)
		}
		return nil, false
	}
	switch c.Op {
	case "index":
		return map[string]any{"text_sha": sha(s.Index(str("prefix", c.Args)))}
	case "search":
		mode := str("mode", c.Args)
		if mode == "" {
			mode = "lexical"
		}
		r, err := s.Search(str("query", c.Args), strs("in", c.Args), num("limit", c.Args, 10), mode)
		if m, bad := errOut(err); bad {
			return m
		}
		ids := []any{}
		for _, h := range r.Hits {
			ids = append(ids, h.ID)
		}
		return map[string]any{"ids": ids, "mode": r.Mode, "empty": len(r.Hits) == 0}
	case "read":
		r, err := s.Read(str("id", c.Args), num("context", c.Args, 0))
		if m, bad := errOut(err); bad {
			return m
		}
		ctx := []any{}
		for _, x := range r.ContextSections {
			ctx = append(ctx, x.ID)
		}
		var prev, next any
		if r.PrevID != nil {
			prev = *r.PrevID
		}
		if r.NextID != nil {
			next = *r.NextID
		}
		return map[string]any{"id": r.ID, "text_sha": sha(r.Text), "heading_path": r.HeadingPath, "context_ids": ctx, "prev": prev, "next": next}
	case "grep":
		r, err := s.Grep(str("pattern", c.Args), strs("in", c.Args), false, num("limit", c.Args, 20))
		if m, bad := errOut(err); bad {
			return m
		}
		ids, shas := []any{}, []any{}
		for _, m := range r.Matches {
			ids = append(ids, m.ID)
			shas = append(shas, sha(m.Line))
		}
		return map[string]any{"ids": ids, "lines_sha": shas, "truncated": r.Truncated}
	case "neighbours":
		r, err := s.Neighbours(str("id", c.Args), num("before", c.Args, 1), num("after", c.Args, 1))
		if m, bad := errOut(err); bad {
			return m
		}
		ids := []any{}
		for _, x := range r.Sections {
			ids = append(ids, x.ID)
		}
		var header any
		if r.Header != nil {
			header = r.Header.ID
		}
		return map[string]any{"ids": ids, "header": header}
	}
	panic("unknown op " + c.Op)
}

// normalise both sides through JSON so numbers/nils compare the same way.
func canon(v any) any {
	b, _ := json.Marshal(v)
	var out any
	_ = json.Unmarshal(b, &out)
	return out
}

func main() {
	store := "../../conformance/store.sqlite"
	cases := "../../conformance/cases.json"
	if len(os.Args) > 1 {
		store = os.Args[1]
	}
	if len(os.Args) > 2 {
		cases = os.Args[2]
	}
	s, err := contextpull.Open(store)
	if err != nil {
		fmt.Println("open:", err)
		os.Exit(1)
	}
	defer s.Close()
	raw, err := os.ReadFile(cases)
	if err != nil {
		fmt.Println(err)
		os.Exit(1)
	}
	var data struct {
		Cases []tcase `json:"cases"`
	}
	if err := json.Unmarshal(raw, &data); err != nil {
		fmt.Println(err)
		os.Exit(1)
	}
	failures := 0
	for _, c := range data.Cases {
		got := canon(run(s, c))
		want := canon(c.Expect)
		if !reflect.DeepEqual(got, want) {
			failures++
			g, _ := json.Marshal(got)
			w, _ := json.Marshal(want)
			a, _ := json.Marshal(c.Args)
			fmt.Printf("FAIL %s %s\n  expect %s\n  got    %s\n", c.Op, a, w, g)
		}
	}
	fmt.Printf("%d/%d conformance cases pass (go)\n", len(data.Cases)-failures, len(data.Cases))
	if failures > 0 {
		os.Exit(1)
	}
}
