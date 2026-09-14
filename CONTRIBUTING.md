# Contributing

Thanks for looking. ContextPull is small on purpose, and the rules below keep it that way.

## Ground rules

- **Zero runtime dependencies in the core.** Anything that needs a package goes behind an extra (`mcp`, `pdf`) or into `sdk/`.
- **The store file is the contract.** A change to what any of the five operations returns is a change to `docs/store-format.md`, a conformance-suite update, and a schema or tools version bump. Readers in Python, TypeScript and Go must agree; CI runs all three against both suites.
- **Measure, don't assert.** A change that claims to improve retrieval comes with a ragbisect row or a scenario, and the write-up includes the cases where it does not help.
- **Five tools.** A sixth needs a documented question the five cannot answer.

## Setup

```sh
uv sync --all-extras
uv run pytest -q
uv run python conformance/run.py check all
cd sdk/typescript && npm install && npm run build && npm run conformance
cd ../go && go build ./... && go run ./cmd/contextpull-conformance
```

`./scripts/demo.sh` is a one-minute tour.

## Where to start

Issues labelled `good first issue` are scoped and self-contained. The conformance suite makes new-language readers a well-defined task: pass `conformance/cases.json` and `conformance/scenarios/cases.json` and you have a ContextPull reader.

## Pull requests

- One change per PR, with tests. Python tests live in `tests/`; the scenario corpus under `conformance/scenarios/corpus` is the place for realistic cases.
- If you touched `ops.py`, regenerate nothing: the conformance cases are the oracle. If you intentionally changed semantics, say so in the PR and update the store-format doc.
- Run the three readers' conformance before pushing; CI will anyway.
- Docs are in `docs/`; the website is generated from them by `scripts/build_site.py` and committed under `site/`.

## Reporting a retrieval problem

The most useful bug report is a small corpus plus a question plus what you expected `search` or `read` to return. `contextpull search … --json` output and the store's `index` text make it reproducible.
