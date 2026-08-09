"""CLI entrypoint: `askwarehouse ask "<question>"` or `askwarehouse` for an
interactive REPL. Prints the NL answer, the SQL that was actually run, row
count, latency, any sanity findings, and saves the chart (if any) to a PNG."""
import argparse
import base64
import os
import sys

from askwarehouse.core.agent import AskWarehouseAgent
from askwarehouse.core.chart import render_chart
from askwarehouse.core.nl_answer import generate_nl_answer
from askwarehouse.core.pipeline_config import PipelineConfig
from askwarehouse.core.verify import verify
from askwarehouse.providers.registry import get_provider

CHART_DIR = "logs/charts"


def _print_response(agent, question, resp, chart_out_dir=CHART_DIR, do_verify=False):
    print(f"\nQ: {question}")

    if resp.status == "clarification_needed":
        print(f"\n  This question is ambiguous: {resp.ambiguity.reason}")
        print(f"  -> {resp.clarifying_question}")
        return

    if resp.status == "failed":
        print(f"\n  Failed after {len(resp.attempts)} attempt(s).")
        for a in resp.attempts:
            print(f"   attempt {a.attempt_number} [{a.stage}/{a.outcome}]: {a.error}")
        print(f"  Last SQL tried:\n  {resp.sql}")
        return

    attempt_summary = "cache hit" if resp.cache_hit else f"{len(resp.attempts)} attempt(s)"
    print(f"\n  SQL ({attempt_summary}):")
    print(f"  {resp.sql}")

    r = resp.result
    print(f"\n  rows: {r.row_count}   latency: {r.latency_ms:.0f}ms   total: {resp.total_latency_ms:.0f}ms   llm_calls: {resp.llm_calls}")

    answer = generate_nl_answer(agent.provider, question, r.columns, r.rows)
    print(f"\n  Answer: {answer}")

    if resp.sanity_findings:
        print("\n  Sanity checks:")
        for f in resp.sanity_findings:
            print(f"   [{f.severity}] {f.code}: {f.message}")

    chart = render_chart(r.columns, r.rows, title=question)
    if chart.png_base64:
        os.makedirs(chart_out_dir, exist_ok=True)
        path = os.path.join(chart_out_dir, "".join(c if c.isalnum() else "_" for c in question)[:60] + ".png")
        with open(path, "wb") as f:
            f.write(base64.b64decode(chart.png_base64))
        print(f"\n  Chart ({chart.kind}) saved to {path}")
    else:
        print(f"\n  Chart: {chart.note}")

    if do_verify:
        print("\n  Verifying with a paraphrased, independent re-generation...")
        v = verify(agent, question, resp.sql, r.columns, r.rows)
        print(f"  Paraphrase: {v.verify_question}")
        print(f"  Match: {v.match} -- {v.detail}")


def main():
    parser = argparse.ArgumentParser(prog="askwarehouse", description="Ask business questions over the AskWarehouse demo warehouse.")
    parser.add_argument("question", nargs="?", help="question to ask; omit for an interactive REPL")
    parser.add_argument("--provider", default=None, help="local | anthropic | openai (default: auto-detect from .env)")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--no-repair", action="store_true")
    parser.add_argument("--no-critique", action="store_true")
    parser.add_argument("--verify", action="store_true", help="also run the verify-mismatch check")
    args = parser.parse_args()

    provider = get_provider(args.provider)
    pipeline_config = PipelineConfig(
        use_cache=not args.no_cache,
        use_repair_loop=not args.no_repair,
        use_self_critique=not args.no_critique,
    )

    print("Loading model and building schema/value indexes (first call only)...")
    agent = AskWarehouseAgent(provider, dialect="duckdb", pipeline_config=pipeline_config)
    print("Ready.")

    if args.question:
        resp = agent.ask(args.question)
        _print_response(agent, args.question, resp, do_verify=args.verify)
        return

    print("\nInteractive mode. Type a question, or 'exit' to quit.\n")
    while True:
        try:
            q = input("askwarehouse> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            continue
        if q.lower() in ("exit", "quit"):
            break
        resp = agent.ask(q)
        _print_response(agent, q, resp)


if __name__ == "__main__":
    sys.exit(main())
