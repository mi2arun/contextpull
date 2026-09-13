#!/usr/bin/env bash
# One-minute demo of ContextPull on the bundled fixture corpus. Needs `uv` only.
#   ./scripts/demo.sh            # fixture corpus (refund policies, error codes, specs)
#   ./scripts/demo.sh ./my-docs  # your own folder of .md/.txt files
set -euo pipefail
cd "$(dirname "$0")/.."
CORPUS="${1:-conformance/corpus}"
STORE="${STORE:-/tmp/contextpull-demo.sqlite}"
rm -f "$STORE" "$STORE-wal" "$STORE-shm"

echo "== 1. ingest $CORPUS"
uv run contextpull ingest "$CORPUS" --store "$STORE"

echo; echo "== 2. the always-in-context index (what the model sees before it does anything)"
uv run contextpull index --store "$STORE" | head -12

echo; echo "== 3. search: pointers only, never bodies"
uv run contextpull search "refund window" --store "$STORE" --limit 3

echo; echo "== 4. read: one section verbatim, with its neighbours' ids"
uv run contextpull read "policies/policy-2025.md#2" --store "$STORE" 2>/dev/null || \
  uv run contextpull read "$(uv run contextpull search refund --store "$STORE" --json --limit 1 | python3 -c 'import sys,json;print(json.load(sys.stdin)["hits"][0]["id"])')" --store "$STORE"

echo; echo "== 5. grep: exact identifiers an embedding would blur"
uv run contextpull grep "TX-4419" --store "$STORE" || true

echo; echo "== 6. attach to Claude Code (copy/paste; nothing is changed by this script)"
echo "   claude mcp add contextpull -- uv run --project $(pwd) contextpull serve $STORE"
echo "   then ask: What changed in the refund window between the 2024 and 2025 policy? Cite section ids."
echo
echo "== 7. or the Node server (no Python at query time), after: cd sdk/typescript && npm install && npm run build"
echo "   claude mcp add contextpull -- node $(pwd)/sdk/typescript/bin/contextpull.mjs serve $STORE"
