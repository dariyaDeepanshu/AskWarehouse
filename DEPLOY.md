# Deploying AskWarehouse to Vercel

The repo is a single Vercel project: a **Next.js** front end (`app/`, `components/`,
`lib/`) plus one **Python serverless function** (`api/index.py`) that runs the full
`askwarehouse` text-to-SQL pipeline.

```
question ─▶ /api/ask (Python)
            schema retrieval (BM25) ─▶ ambiguity gate ─▶ plan ─▶ generate
            ─▶ self-critique ─▶ static sqlglot guards ─▶ read-only DuckDB execute
            ─▶ repair loop ─▶ sanity checks ─▶ NL answer + chart spec + SQL
```

## What changed from the local project

Vercel is serverless — no GPU, a read-only bundle, an ephemeral `/tmp`, a 60 s
request cap. So:

| Local | Deployed |
|---|---|
| Qwen2.5-Coder-7B on GPU (`providers/local.py`) | a hosted free-tier model — Gemini or Groq (`providers/hosted.py`) |
| MiniLM embedding schema retrieval | BM25 over the same schema text (`retrieval/schema_index.py`) — still never dumps the whole schema |
| MiniLM value-index fuzzy match | deterministic alias table + token/`difflib` matching (`retrieval/value_index.py`) |
| 16 M-row warehouse built by `dbt run` | a ~120 k-order warehouse **committed at `data/warehouse/warehouse.duckdb`**, built by `scripts/build_demo_warehouse.py` (same staging → marts → semantic SQL) |
| persistent audit/cache DuckDB | best-effort in `/tmp` (per-instance); the authoritative trace is returned in each API response |
| matplotlib PNG | chart spec returned as JSON, drawn client-side as SVG |

Every pipeline stage, every safety guard (`read_only=True`, the AST allowlist, the
PII denylist, the `EXPLAIN` cost check, the forced `LIMIT` / timeout / audit) is
otherwise unchanged and shared with the CLI and the eval harness.

## Deploy

### 1. Get a free model API key

- **Gemini** (recommended): https://aistudio.google.com/apikey
- **Groq**: https://console.groq.com/keys

### 2. Push this repo to GitHub / GitLab / Bitbucket

```bash
git init && git add -A && git commit -m "AskWarehouse web deployment"
git remote add origin <your remote> && git push -u origin main
```

The 22 MB `data/warehouse/warehouse.duckdb` is committed on purpose — Vercel needs
it in the function bundle. (To rebuild it: `pip install -r requirements.txt` then
`python scripts/build_demo_warehouse.py --scale small`.)

### 3. Import the project in Vercel

- **New Project → import the repo.** Framework preset auto-detects as **Next.js**.
- Vercel picks up `vercel.json` (Python function config: `maxDuration` 60 s,
  1024 MB, `includeFiles` for `src/`, the dbt YAML, and the warehouse file) and
  `api/requirements.txt` (the slim runtime deps — no torch/dbt/matplotlib).
- **Environment variables** → add one of:

  | Name | Value |
  |---|---|
  | `GEMINI_API_KEY` | your key |
  | *or* `GROQ_API_KEY` | your key |

  Optional: `ASKWAREHOUSE_PROVIDER` (`gemini` \| `groq` \| …),
  `ASKWAREHOUSE_MODEL`, `ASKWAREHOUSE_RL_PER_MIN` (default 6 questions/min/IP on
  the shared key).

- **Deploy.**

If you set **no** server key, the site still deploys — every visitor just has to
paste their own key in the Settings panel (it's stored only in their browser and
sent per-request; those requests aren't rate-limited).

### 4. Verify

- `https://<your-app>/api/health` → `{"ok": true, "readonly_enforced": true, ...}`
- Open the site, click an example question.

## Local development

```bash
# front end (API calls 404 unless you also run `vercel dev`)
npm install && npm run dev

# full stack locally
npm i -g vercel && vercel dev        # serves Next + the Python function together

# offline checks (no API key needed)
python scripts/smoke_test_web.py     # catalog + retrieval + guards + execute
python scripts/smoke_test_api.py     # the FastAPI app end to end, canned model
```

> Note: `next build` fails locally on **Node 22.14.0 for Windows** due to an
> `fs.readlink` regression in that exact Node build (fixed in 22.15). `next dev`,
> `tsc`, and Vercel's Linux build are unaffected. Upgrade Node to 22.15+ or 20 LTS
> if you need a local production build.

## Notes / limits

- The warehouse is generated relative to its build date; "last 90 days" style
  questions drift as wall-clock time passes. Rebuild and redeploy to refresh.
- Free-tier models are weaker than GPT-4-class on hard multi-join SQL — the repair
  loop and sanity checks matter more here, which is rather the point of the demo.
- Cold starts copy the 22 MB DB to `/tmp` (~1 s) and build the BM25 + value
  indexes (~1 s).
