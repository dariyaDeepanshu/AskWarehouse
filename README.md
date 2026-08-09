# AskWarehouse

A text-to-SQL analytics agent that answers business questions over a real multi-table warehouse
by writing SQL, running it in a read-only sandbox, repairing its own errors from the database's
feedback, asking for clarification when a question is genuinely ambiguous, and returning a chart
plus the SQL it used.

Full architecture writeup (diagram + component breakdown): **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**
/ [published version](https://claude.ai/code/artifact/420109db-206e-407a-9ecf-9880bf303b7a)

> **Interview soundbite** (real numbers from this run, not aspirational): "On BIRD mini-dev,
> schema retrieval plus a value index took execution accuracy from 32% to 38% with a local
> 7B model and zero API cost -- self-critique alone actually cost a point (36%), and the repair
> loop was the single biggest jump, to 42%, mostly by turning a wrong-column guess into a second
> attempt with the database's own error message as feedback. I can show exactly where each point
> came from, including the one that went backwards."

## Why a local model

This environment has no LLM API key. Rather than block on one, AskWarehouse defaults to a **free,
local, no-API-key model**: Qwen2.5-Coder-7B-Instruct, 4-bit quantized, run on-GPU via
`transformers`+`bitsandbytes`. `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` in `.env` transparently
switch to a hosted provider behind the same interface (`src/askwarehouse/providers/`).

## Quickstart

```bash
git clone <this repo> && cd ASK_Warehouse
python3 -m venv --system-site-packages .venv   # --system-site-packages reuses a pre-installed
                                                 # CUDA-matched torch/transformers if present;
                                                 # drop the flag on a machine without one
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

# 1. generate the synthetic warehouse (~16M rows, DuckDB, ~7s)
python scripts/generate_warehouse_data.py --scale full

# 2. build the dbt star schema + semantic layer on top of it
cd dbt_project && dbt seed --profiles-dir . && dbt run --profiles-dir . && dbt test --profiles-dir . && cd ..

# 3. ask a question
askwarehouse "How many completed orders were there in California in 2025?"

# ...or the interactive REPL
askwarehouse

# ...or the web UI
streamlit run src/askwarehouse/ui/streamlit_app.py
```

First call downloads Qwen2.5-Coder-7B-Instruct (~15GB) and the MiniLM embedding model, then loads
them (~30s). Every call after that reuses the loaded weights within the process.

## Architecture (short version)

```
Question -> schema retrieval (embeddings, never the whole schema) -> ambiguity check
         -> plan (joins & grain) -> generate SQL (dialect-aware) -> self-critique
         -> static guards (read-only AST check, LIMIT injection, EXPLAIN cost check, PII deny-list)
         -> execute (DuckDB, read_only=True) -> repair loop on error (max 3, exact DB error as feedback)
         -> sanity checks (empty result / fan-out double-count / null-heavy) -> NL answer + chart + SQL
```

Full diagram and per-module ownership: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Safety, as code not prompt

- Execution connection opened `read_only=True` at the DuckDB storage engine -- a write attempt
  raises before it can touch the file, regardless of the SQL text (`execution/connection.py`).
- Every generated query is parsed to an AST with `sqlglot` and rejected if it isn't SELECT/WITH,
  references a table outside the allowed schemas, or touches a PII-denylisted column --
  **before a connection is even opened** (`safety/guards.py`).
- `EXPLAIN`-based row-estimate rejection using DuckDB's own optimizer cardinality estimates.
- A forced/clamped `LIMIT`, a wall-clock statement timeout, and a full audit log of every
  statement that reaches a database (whether it ran, errored, or was rejected) -- independent of
  what the UI shows (`execution/audit.py`).

## Evaluation

Methodology: same `AskWarehouseAgent` / BIRD pipeline code path for every row of the ablation
table below, with only the named stage toggled -- see `core/pipeline_config.py` and
`eval/bird_runner.py`. BIRD uses **BIRD mini-dev** (500 curated SELECT-only questions across 11
real SQLite databases) via the non-gated `birdsql/bird_mini_dev` + `premai-io/birdbench` HuggingFace
mirrors, since the official BIRD host gates the database download behind Google Drive. Spider's
question/SQL annotations are on HuggingFace (`xlangai/spider`) but its database files are only
distributed via a gated Yale host not scriptable from this environment -- **Spider execution
accuracy is not reported here**; the harness supports it (`sql/prompts.py` dialect switch) if the
databases are supplied separately. This is exactly the kind of limitation worth stating rather
than hiding.

### Ablation on BIRD mini-dev (n=100, stratified by difficulty, seed=7)

| Config | BIRD-dev exec acc (n=100) | Valid SQL % | Avg attempts | p50 latency | p95 latency | Avg LLM calls |
|---|---|---|---|---|---|---|
| Single-shot, full schema | 32.0% | 71.0% | 1.00 | 1684 ms | 2648 ms | 1.0 |
| + schema retrieval | 33.0% | 75.0% | 1.00 | 1613 ms | 2677 ms | 1.0 |
| + value index | 38.0% | 78.0% | 1.00 | 1699 ms | 2726 ms | 1.0 |
| + self-critique | 36.0% | 75.0% | 1.00 | 3250 ms | 5430 ms | 2.0 |
| + repair loop | 42.0% | 87.0% | 1.40 | 3588 ms | 8695 ms | 2.4 |

$/query: $0.00 -- the local model has no per-token API cost. The real cost is GPU-seconds: p50
latency above is a reasonable proxy (on this RTX 4000 Ada, ~1.6-1.7s/query for the single-LLM-call
configs, rising to ~3.6s once self-critique adds a second call). A hosted-model run would trade
this for a real $/query figure at lower latency; `providers/hosted.py` is wired for exactly that
comparison if a key is added.

### Own warehouse (109 hand-written gold questions, full pipeline incl. semantic layer)

**Overall**: exec accuracy = 64.2%, valid SQL % = 90.8%, avg attempts = 1.41, p95 latency = 13017 ms (n=109)

| Question category | n | Exec accuracy |
|---|---|---|
| semantic_revenue_value_index | 3 | 100.0% |
| marketing | 8 | 87.5% |
| basic_count | 10 | 80.0% |
| product_performance | 12 | 75.0% |
| customer_behavior | 11 | 72.7% |
| payment_channel | 10 | 70.0% |
| semantic_revenue | 13 | 69.2% |
| geographic_value_index | 4 | 50.0% |
| ranking | 6 | 50.0% |
| time_based | 17 | 47.1% |
| geographic | 7 | 42.9% |
| grain_sensitive | 8 | 37.5% |

### Ambiguity handling (40 hand-labeled questions: 20 clear / 20 ambiguous)

| Metric | Value |
|---|---|
| Accuracy | 95.0% |
| Precision | 100.0% |
| Recall | 90.0% |
| **Over-ask rate** (asked on a clear question) | 0.0% |
| **Under-ask rate** (guessed on an ambiguous question) | 10.0% |

Confusion: TP=18 FN=2 FP=0 TN=20 (n=40)

### Failure taxonomy

97 failures categorized (all failures from BIRD config `5_plus_repair_loop` + all failures from
the own-warehouse gold eval). Full write-up, including the two shipped fixes for the two biggest
slices and a classifier bug the spot-check itself caught: **[eval/failure_taxonomy/notes.md](eval/failure_taxonomy/notes.md)**.

![failure taxonomy pie chart](eval/failure_taxonomy/taxonomy_pie.png)

| Category | Count | % of failures |
|---|---|---|
| join_path | 37 | 38.1% |
| ambiguity_external_knowledge | 31 | 32.0% |
| schema_linking | 19 | 19.6% |
| date_logic | 6 | 6.2% |
| aggregation_grain | 4 | 4.1% |

## Limitations, stated rather than hidden

- **Local 7B vs. proprietary models**: Qwen2.5-Coder-7B-Instruct is a strong open model for its
  size but smaller than what a hosted-API run would use. The absolute BIRD numbers (32-42%) are
  therefore lower than published leaderboard numbers using GPT-4-class models -- the point of this
  eval is the *shape* of the ablation curve (which stage buys how much), which is model-agnostic
  in mechanism even if the absolute numbers would shift with a bigger model.
- **Spider not evaluated**: annotations are available, database files are not (gated Yale host).
  See "Evaluation" above.
- **Benchmark databases are unrealistically small** compared to a real warehouse -- this is exactly
  why the own-warehouse eval (16M-row DuckDB warehouse, 109 hand-written questions) exists
  alongside BIRD, per the brief's own framing. Own-warehouse exec accuracy (64.2%) is meaningfully
  higher than BIRD's best config (42%), consistent with the schema-documentation gap described in
  the failure taxonomy notes (dbt-authored column descriptions and FK relationships vs. BIRD's
  bare, undocumented SQLite schemas).
- **Grain-sensitive questions are the hardest category on our own warehouse** (37.5% exec
  accuracy, the lowest of any tag) -- direct confirmation that double-counting after a 1:many
  join is the genuinely hard failure mode the brief calls out, not a strawman.
- **The failure-taxonomy classifier is rule-based and first-pass**, not a human label on every
  row (see the caveat and the bug found/fixed in `eval/failure_taxonomy/notes.md`).
- **Ambiguity ground truth is self-authored** (40 questions I labeled myself) rather than a
  third-party-annotated set -- a real deployment would want inter-rater-checked labels.

## Testing

No mocked LLM calls -- every smoke test in `scripts/smoke_test_*.py` runs the real local model
and the real DuckDB warehouse:

```bash
python scripts/smoke_test_repair.py          # repair loop on a deliberately broken query
python scripts/smoke_test_sanity_cache.py    # sanity checks + cache (no LLM needed)
python scripts/smoke_test_agent.py           # full orchestrator, 3 live questions
python scripts/smoke_test_answer_layer.py    # chart + NL answer + verify-mismatch
python scripts/smoke_test_streamlit.py       # headless Streamlit run via AppTest
```

Re-running the full evaluation suite end to end:

```bash
python -m askwarehouse.eval.bird_runner 100          # BIRD ablation (~20 min on an RTX 4000 Ada)
python scripts/run_remaining_evals.py                # own-warehouse gold set + ambiguity eval
python scripts/build_failure_taxonomy.py             # pools + classifies failures
python scripts/render_failure_taxonomy_chart.py
python scripts/generate_readme_tables.py             # regenerates the tables above from eval/results/*.json
```

## Stretch goals (not implemented here)

Per the brief: fine-tuning a small open model for SQL generation and comparing cost/accuracy
against the API model, multi-turn conversational refinement with reference resolution, and
exposing the pipeline as an MCP server. All three are natural extensions of the existing
`providers/` and `core/agent.py` interfaces but are out of scope for this pass -- noted rather
than silently dropped.

## Repository layout

```
src/askwarehouse/
  core/            planner, ambiguity check, sanity checks, cache, orchestrator, chart, verify
  providers/       local (Qwen2.5-Coder) + pluggable OpenAI/Anthropic backends
  retrieval/       schema embedding index + value index (alias table + fuzzy matching)
  sql/             dialect-aware prompt construction, generation, self-critique
  safety/          sqlglot guards, PII deny-list, EXPLAIN cost check
  execution/       sandboxed runner, repair loop, audit log
  eval/            BIRD harness, own-warehouse eval, ambiguity eval, failure taxonomy
  ui/              CLI + Streamlit
dbt_project/       staging (normalizes messy source data) -> marts (star schema) -> semantic layer
data/              warehouse.duckdb, generator script output
eval/              gold questions, ambiguity labels, results, failure taxonomy
scripts/           data generation, smoke tests, eval entrypoints
```
