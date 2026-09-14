# Live agent scenarios, 2026-09-14

Corpus: `conformance/scenarios/corpus` (12 documents in six formats: versioned policies, split error-code references, spec tables, a procedure, Word, Excel, PowerPoint, PDF, text). Six complex questions run through the real pull loop with expectations on which sections must be read and what the answer must contain. Runner: `scripts/scenario_agent.py`.

| file | model | result |
|---|---|---|
| `api-loop-gpt-5.4-mini-strict.txt` | gpt-5.4-mini, reasoning off, strict prompt | 6/6; 26 tool calls, 14 reads, 37k input tokens for all six |
| `claude-code.txt` | Claude Code headless | 6/6; 31 tool calls, 19 reads, 462k input tokens (mostly cache reads), $1.59 |

Reading: the same small model that reads a section on one factoid question in twenty read four sections for the version comparison and three for the multi-hop question. When the answer cannot fit a snippet, it reads.
