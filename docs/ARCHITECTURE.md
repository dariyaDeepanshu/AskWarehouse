# AskWarehouse — Architecture

Full visual version (diagram + component grid): https://claude.ai/code/artifact/420109db-206e-407a-9ecf-9880bf303b7a

## Pipeline

```
Question
  └─► Schema retrieval (embeddings over table/column descriptions, sample values,
      + a value-index for literal matching, e.g. "California" -> state = 'CA')
       └─► Ambiguity check ──ambiguous──► clarifying question back to user (pipeline pauses)
        │
        └─► Plan: decompose into steps, identify joins & grain
             └─► Generate SQL (dialect-aware: DuckDB / SQLite) + self-critique pass
                  └─► Static guards: read-only AST check, LIMIT injection,
                      EXPLAIN row/cost estimate, PII column deny-list
                       └─► Execute in sandbox (read-only connection, timeout, statement cap)
                            ├─error──► repair loop (max 3 attempts, exact DB error text as feedback)
                            └─ok────► sanity checks (empty result? suspicious cardinality?
                                       grain mismatch after a 1:many join?)
                                        └─► NL answer + chart + SQL shown
                                            (+ "verify this": re-run a differently-phrased
                                            equivalent query, flag mismatches)
```

Side components:
- **Semantic layer** — curated metric definitions (`revenue`, `active_user`, `aov`) as dbt views, resolved during SQL generation.
- **Cache** — question-fingerprint → SQL, keyed on schema version; invalidates automatically on schema change.
- **Audit log** — every statement that reaches the database, independent of what the UI shows.

## Module map

| Path | Owns |
|---|---|
| `src/askwarehouse/retrieval/` | schema embedding index + value index |
| `src/askwarehouse/core/ambiguity.py` | ambiguity classifier |
| `src/askwarehouse/core/planner.py` | join/grain planning step |
| `src/askwarehouse/sql/` | dialect-aware prompt + generation + self-critique |
| `src/askwarehouse/safety/` | sqlglot read-only guard, LIMIT injection, EXPLAIN cost check, PII deny-list |
| `src/askwarehouse/execution/` | sandboxed runner, repair loop, audit log |
| `src/askwarehouse/core/sanity.py` | post-execution sanity checks |
| `src/askwarehouse/core/cache.py` | fingerprint cache |
| `src/askwarehouse/providers/` | local (Qwen2.5-Coder-7B-Instruct, 4-bit) + pluggable OpenAI/Anthropic |
| `src/askwarehouse/ui/` | CLI + Streamlit |
| `dbt_project/` | staging → marts (star schema) → semantic layer views |
| `eval/` | gold Q&A, ablation results, ambiguity-eval set, failure taxonomy |

## Why a local model

No API key exists in this environment and the brief asked for something free and accurate. The machine has an
RTX 4000 Ada (20GB VRAM) with CUDA 12.9, and torch/transformers were already installed system-wide, so the
venv was created with `--system-site-packages` to inherit that build. Default provider is
**Qwen2.5-Coder-7B-Instruct**, loaded 4-bit via bitsandbytes (~5GB VRAM), run through
`src/askwarehouse/providers/local.py`. `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` in `.env` transparently switch
to a hosted provider behind the same interface if the user adds one later — useful for the cost/accuracy
comparison the eval table calls for.

## Why DuckDB + dbt-duckdb for the hero warehouse

A flat CSV can't produce join-path or grain bugs. `dbt_project/` builds a real staging → dimensional model
→ semantic-view star schema so the failure modes the brief calls "the hard parts" (join-path selection in a
snowflaked schema, double-counting after a 1:many join, date/fiscal logic) actually occur.

## Safety as a database-level property, not a prompt instruction

The execution connection is opened `read_only=True` at the DuckDB level. The static guard stage parses the
generated SQL with `sqlglot` and rejects anything whose AST root isn't `SELECT`/`WITH` — this runs *before*
a connection is even opened, so a rejected query never reaches the database at all. Neither of these depends
on the model behaving.
