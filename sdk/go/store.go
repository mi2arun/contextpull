// Package contextpull is a store-native Go reader for ContextPull stores
// (SQLite + FTS5). It implements docs/store-format.md; the conformance suite
// under ../../conformance defines correctness. Read-only.
package contextpull

import (
	"database/sql"
	"errors"
	"fmt"
	"math"
	"regexp"
	"sort"
	"strings"

	_ "modernc.org/sqlite"
)

const SupportedMajor = "1"

// OpsError is a tool error: a message plus a suggestion the model can act on.
type OpsError struct {
	Message    string `json:"error"`
	Suggestion string `json:"suggestion,omitempty"`
}

func (e *OpsError) Error() string { return e.Message }

type Hit struct {
	ID          string  `json:"id"`
	Doc         string  `json:"doc"`
	HeadingPath string  `json:"heading_path"`
	Snippet     string  `json:"snippet"`
	Score       float64 `json:"score"`
	Kind        string  `json:"kind"`
}

type SearchResult struct {
	Hits []Hit   `json:"hits"`
	Mode string  `json:"mode"`
	Hint *string `json:"hint"`
}

type Section struct {
	ID          string  `json:"id"`
	Doc         string  `json:"doc"`
	HeadingPath string  `json:"heading_path"`
	Kind        string  `json:"kind"`
	Text        string  `json:"text"`
	PrevID      *string `json:"prev_id"`
	NextID      *string `json:"next_id"`
	Context     bool    `json:"context"`
}

type ReadResult struct {
	Section
	ContextSections []Section `json:"context"`
}

type Match struct {
	ID          string `json:"id"`
	Doc         string `json:"doc"`
	HeadingPath string `json:"heading_path"`
	Line        string `json:"line"`
}

type GrepResult struct {
	Matches   []Match `json:"matches"`
	Truncated bool    `json:"truncated"`
}

type NeighboursResult struct {
	Sections []Section `json:"sections"`
	Header   *Section  `json:"header"`
}

var (
	tokenRe = regexp.MustCompile(`[\pL\pN][\pL\pN._\-]*`)
	leadRe  = regexp.MustCompile(`(^|[^\pL\pN._\-])[-_.]+([\pL\pN])`)
	trailRe = regexp.MustCompile(`([\pL\pN])[-_.]+($|[^\pL\pN._\-])`)
)

// NormalizeForFTS strips leading/trailing '-', '_' and '.' from tokens, as ingest does for the indexed columns.
func NormalizeForFTS(text string) string {
	// Two passes: Go's RE2 has no lookaround, so consume and restore the boundary character.
	out := leadRe.ReplaceAllString(text, "$1$2")
	out = trailRe.ReplaceAllString(out, "$1$2")
	return out
}

func Tokenize(text string) []string {
	var out []string
	for _, t := range tokenRe.FindAllString(NormalizeForFTS(strings.ToLower(text)), -1) {
		t = strings.Trim(t, "._-")
		if t != "" {
			out = append(out, t)
		}
	}
	return out
}

func ftsString(tok string) string { return `"` + strings.ReplaceAll(tok, `"`, `""`) + `"` }

type Store struct {
	db *sql.DB
}

// Open opens a store read-only and verifies its schema version and FTS5 availability.
func Open(path string) (*Store, error) {
	db, err := sql.Open("sqlite", "file:"+path+"?mode=ro&_pragma=query_only(1)")
	if err != nil {
		return nil, err
	}
	var version string
	if err := db.QueryRow("SELECT value FROM meta WHERE key='schema_version'").Scan(&version); err != nil {
		db.Close()
		if errors.Is(err, sql.ErrNoRows) {
			return nil, &OpsError{Message: fmt.Sprintf("%s is not a ContextPull store (no schema_version)", path)}
		}
		return nil, &OpsError{Message: fmt.Sprintf("%s is not a ContextPull store: %v", path, err)}
	}
	if strings.SplitN(version, ".", 2)[0] != SupportedMajor {
		db.Close()
		return nil, &OpsError{Message: fmt.Sprintf("store %s has schema %s; this reader supports %s.x", path, version, SupportedMajor)}
	}
	var n int
	if err := db.QueryRow("SELECT count(*) FROM sections_fts LIMIT 1").Scan(&n); err != nil {
		db.Close()
		return nil, &OpsError{Message: "this SQLite build lacks FTS5; ContextPull needs an FTS5-enabled SQLite"}
	}
	return &Store{db: db}, nil
}

func (s *Store) Close() error { return s.db.Close() }

func (s *Store) Meta(key string) string {
	var v string
	_ = s.db.QueryRow("SELECT value FROM meta WHERE key=?", key).Scan(&v)
	return v
}

func (s *Store) Counts() (docs, sections int) {
	_ = s.db.QueryRow("SELECT count(*) FROM documents").Scan(&docs)
	_ = s.db.QueryRow("SELECT count(*) FROM sections").Scan(&sections)
	return
}

func globClause(paths []string) (string, []any, error) {
	if len(paths) == 0 {
		return "", nil, nil
	}
	var parts []string
	var args []any
	for _, p := range paths {
		if p == "" {
			return "", nil, &OpsError{Message: `invalid path filter ""`, Suggestion: "pass document paths or globs as shown in the index"}
		}
		parts = append(parts, "d.path GLOB ?")
		args = append(args, p)
		if !strings.ContainsAny(p, "*?[") {
			parts = append(parts, "d.path GLOB ?")
			args = append(args, strings.TrimRight(p, "/")+"/*")
		}
	}
	return " AND (" + strings.Join(parts, " OR ") + ")", args, nil
}

func clamp(v, lo, hi int) int {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

// ---------------------------------------------------------------- index

func (s *Store) Index(prefix string) string {
	if prefix == "" {
		return s.Meta("index_text")
	}
	esc := strings.NewReplacer(`\`, `\\`, `%`, `\%`, `_`, `\_`).Replace(prefix) + "%"
	var n, m int
	_ = s.db.QueryRow(`SELECT count(*), coalesce(sum(n_sections),0) FROM documents WHERE path LIKE ? ESCAPE '\'`, esc).Scan(&n, &m)
	rows, err := s.db.Query(`SELECT path, title, coalesce(summary,''), n_sections FROM documents WHERE path LIKE ? ESCAPE '\' ORDER BY path`, esc)
	lines := []string{fmt.Sprintf("ContextPull index · %s · %d documents · %d sections", prefix, n, m)}
	if err == nil {
		defer rows.Close()
		for rows.Next() {
			var path, title, summary string
			var ns int
			_ = rows.Scan(&path, &title, &summary, &ns)
			label := strings.TrimSpace(summary)
			if label == "" {
				label = strings.TrimSpace(title)
			}
			if r := []rune(label); len(r) > 60 {
				label = strings.TrimRight(string(r[:59]), " ") + "…"
			}
			lines = append(lines, fmt.Sprintf("%-30s  %s  (%d)", path, label, ns))
		}
	}
	return strings.Join(lines, "\n")
}

// --------------------------------------------------------------- search

func (s *Store) Search(query string, in []string, limit int, mode string) (*SearchResult, error) {
	limit = clamp(limit, 1, 50)
	if limit == 0 {
		limit = 10
	}
	toks := Tokenize(query)
	if len(toks) == 0 {
		h := "no searchable words in query"
		return &SearchResult{Hits: []Hit{}, Mode: "lexical", Hint: &h}, nil
	}
	where, args, err := globClause(in)
	if err != nil {
		return nil, err
	}
	var queries []string
	if len(toks) >= 2 {
		queries = append(queries, ftsString(strings.Join(toks, " ")))
		q := make([]string, len(toks))
		for i, t := range toks {
			q[i] = ftsString(t)
		}
		queries = append(queries, strings.Join(q, " AND "))
	}
	q := make([]string, len(toks))
	for i, t := range toks {
		q[i] = ftsString(t)
	}
	queries = append(queries, strings.Join(q, " OR "))

	stmt := `SELECT f.id, d.path, s.heading_path, s.kind,
	           snippet(sections_fts, 2, '**', '**', '…', 20), bm25(sections_fts, 0.0, 2.0, 1.0) AS rank
	         FROM sections_fts f JOIN sections s ON s.id = f.id JOIN documents d ON d.doc_id = s.doc_id
	         WHERE sections_fts MATCH ?` + where + ` ORDER BY rank, f.id LIMIT ?`
	seen := map[string]bool{}
	hits := []Hit{}
	for _, fq := range queries {
		if len(hits) >= limit {
			break
		}
		qargs := append([]any{fq}, args...)
		qargs = append(qargs, limit)
		rows, err := s.db.Query(stmt, qargs...)
		if err != nil {
			return nil, err
		}
		for rows.Next() {
			var h Hit
			var snip string
			var rank float64
			if err := rows.Scan(&h.ID, &h.Doc, &h.HeadingPath, &h.Kind, &snip, &rank); err != nil {
				rows.Close()
				return nil, err
			}
			if seen[h.ID] {
				continue
			}
			seen[h.ID] = true
			h.Snippet = strings.Join(strings.Fields(snip), " ")
			h.Score = math.Round(-rank*100) / 100
			hits = append(hits, h)
			if len(hits) >= limit {
				break
			}
		}
		rows.Close()
	}
	res := &SearchResult{Hits: hits, Mode: "lexical"}
	if mode == "hybrid" {
		h := "no embeddings in store; ran lexical"
		res.Hint = &h
	}
	if len(hits) == 0 {
		h := "no hits; try grep for exact codes, drop the in= filter, or use fewer words"
		res.Hint = &h
	}
	return res, nil
}

// ----------------------------------------------------------------- read

type row struct {
	Section
	docID, ordinal int
}

func (s *Store) get(id string) (*row, error) {
	r := &row{}
	var prev, next sql.NullString
	err := s.db.QueryRow(`SELECT s.id, d.path, s.heading_path, s.kind, s.text, s.prev_id, s.next_id, s.doc_id, s.ordinal
	                      FROM sections s JOIN documents d ON d.doc_id = s.doc_id WHERE s.id = ?`, id).
		Scan(&r.ID, &r.Doc, &r.HeadingPath, &r.Kind, &r.Text, &prev, &next, &r.docID, &r.ordinal)
	if err != nil {
		return nil, &OpsError{Message: fmt.Sprintf("no section '%s'", id), Suggestion: "search for it first; ids look like path.md#3"}
	}
	if prev.Valid {
		r.PrevID = &prev.String
	}
	if next.Valid {
		r.NextID = &next.String
	}
	return r, nil
}

func (s *Store) tableHeader(r *row) *row {
	if r.Kind != "table" {
		return nil
	}
	first := r
	for first.PrevID != nil {
		prev, err := s.get(*first.PrevID)
		if err != nil || prev.Kind != "table" || prev.HeadingPath != r.HeadingPath {
			break
		}
		first = prev
	}
	if first.ID == r.ID {
		return nil
	}
	return first
}

func (s *Store) rangeRows(docID, lo, hi int, exclude string) ([]Section, error) {
	rows, err := s.db.Query(`SELECT s.id, d.path, s.heading_path, s.kind, s.text, s.prev_id, s.next_id FROM sections s
	                         JOIN documents d ON d.doc_id = s.doc_id WHERE s.doc_id = ? AND s.ordinal BETWEEN ? AND ? AND s.id != ? ORDER BY s.ordinal`,
		docID, lo, hi, exclude)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Section
	for rows.Next() {
		var sec Section
		var prev, next sql.NullString
		if err := rows.Scan(&sec.ID, &sec.Doc, &sec.HeadingPath, &sec.Kind, &sec.Text, &prev, &next); err != nil {
			return nil, err
		}
		if prev.Valid {
			sec.PrevID = &prev.String
		}
		if next.Valid {
			sec.NextID = &next.String
		}
		out = append(out, sec)
	}
	return out, nil
}

func (s *Store) Read(id string, context int) (*ReadResult, error) {
	r, err := s.get(id)
	if err != nil {
		return nil, err
	}
	res := &ReadResult{Section: r.Section, ContextSections: []Section{}}
	if h := s.tableHeader(r); h != nil {
		var lines []string
		for _, l := range strings.Split(h.Text, "\n") {
			if strings.HasPrefix(strings.TrimLeft(l, " \t"), "|") {
				lines = append(lines, l)
				if len(lines) == 2 {
					break
				}
			}
		}
		head := strings.Join(lines, "\n")
		if head != "" && !strings.HasPrefix(res.Text, head) {
			res.Text = head + "\n" + res.Text
		}
	}
	if n := clamp(context, 0, 5); n > 0 {
		ctx, err := s.rangeRows(r.docID, r.ordinal-n, r.ordinal+n, id)
		if err != nil {
			return nil, err
		}
		for i := range ctx {
			ctx[i].Context = true
		}
		res.ContextSections = ctx
	}
	return res, nil
}

// ----------------------------------------------------------------- grep

func (s *Store) Grep(pattern string, in []string, regex bool, limit int) (*GrepResult, error) {
	if pattern == "" || len(pattern) > 200 {
		return nil, &OpsError{Message: "pattern must be 1–200 characters", Suggestion: "narrow the pattern"}
	}
	limit = clamp(limit, 1, 100)
	where, args, err := globClause(in)
	if err != nil {
		return nil, err
	}
	var rows *sql.Rows
	if regex {
		rows, err = s.db.Query(`SELECT s.id, d.path, s.heading_path, s.text FROM sections s JOIN documents d ON d.doc_id = s.doc_id WHERE 1=1`+where+` ORDER BY s.id`, args...)
	} else {
		qargs := append([]any{strings.ToLower(pattern)}, args...)
		rows, err = s.db.Query(`SELECT s.id, d.path, s.heading_path, s.text FROM sections s JOIN documents d ON d.doc_id = s.doc_id
		                        WHERE instr(lower(s.text), ?) > 0`+where+` ORDER BY s.id`, qargs...)
	}
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var re *regexp.Regexp
	if regex {
		re, err = regexp.Compile("(?i)" + pattern)
		if err != nil {
			return nil, &OpsError{Message: "pattern does not compile: " + err.Error(), Suggestion: "set regex=false for a literal match"}
		}
	}
	needle := strings.ToLower(pattern)
	res := &GrepResult{Matches: []Match{}}
	scanned := 0
	for rows.Next() {
		var m Match
		var text string
		if err := rows.Scan(&m.ID, &m.Doc, &m.HeadingPath, &text); err != nil {
			return nil, err
		}
		if regex {
			scanned += len(text)
			if scanned > 200_000 {
				return nil, &OpsError{Message: "pattern too expensive", Suggestion: "narrow with in= or use a literal pattern"}
			}
		}
		for _, line := range strings.Split(text, "\n") {
			var ok bool
			if re != nil {
				ok = re.MatchString(line)
			} else {
				ok = strings.Contains(strings.ToLower(line), needle)
			}
			if ok {
				if len(res.Matches) >= limit {
					res.Truncated = true
					return res, nil
				}
				m.Line = strings.TrimSpace(line)
				res.Matches = append(res.Matches, m)
				break
			}
		}
	}
	return res, nil
}

// ----------------------------------------------------------- neighbours

func (s *Store) Neighbours(id string, before, after int) (*NeighboursResult, error) {
	r, err := s.get(id)
	if err != nil {
		return nil, err
	}
	before, after = clamp(before, 0, 5), clamp(after, 0, 5)
	secs, err := s.rangeRows(r.docID, r.ordinal-before, r.ordinal+after, "")
	if err != nil {
		return nil, err
	}
	sort.SliceStable(secs, func(i, j int) bool { return false })
	res := &NeighboursResult{Sections: secs}
	if h := s.tableHeader(r); h != nil {
		hs := h.Section
		res.Header = &hs
	}
	return res, nil
}

// Call dispatches a tool call by name; mirrors contextpull.tools.call.
func (s *Store) Call(name string, args map[string]any) (any, error) {
	str := func(k string) string {
		if v, ok := args[k].(string); ok {
			return v
		}
		return ""
	}
	num := func(k string, def int) int {
		switch v := args[k].(type) {
		case float64:
			return int(v)
		case int:
			return v
		}
		return def
	}
	strs := func(k string) []string {
		var out []string
		if xs, ok := args[k].([]any); ok {
			for _, x := range xs {
				if sx, ok := x.(string); ok {
					out = append(out, sx)
				} else {
					out = append(out, "")
				}
			}
		}
		return out
	}
	switch name {
	case "index":
		return s.Index(str("prefix")), nil
	case "search":
		mode := str("mode")
		if mode == "" {
			mode = "lexical"
		}
		return s.Search(str("query"), strs("in"), num("limit", 10), mode)
	case "read":
		return s.Read(str("id"), num("context", 0))
	case "grep":
		rx, _ := args["regex"].(bool)
		return s.Grep(str("pattern"), strs("in"), rx, num("limit", 20))
	case "neighbours":
		return s.Neighbours(str("id"), num("before", 1), num("after", 1))
	}
	return nil, &OpsError{Message: fmt.Sprintf("unknown tool '%s'", name), Suggestion: "tools: index, search, read, grep, neighbours"}
}
