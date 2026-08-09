"""Runs the full agent (all pipeline stages on, including the semantic
layer) against the 100+ hand-written gold questions for the AskWarehouse
demo warehouse, and scores execution accuracy the same way the BIRD harness
does. This is the number the brief calls for separately from BIRD/Spider,
since benchmark databases are much smaller than a real warehouse."""
import json
import os
from dataclasses import asdict, dataclass

from askwarehouse.core.agent import AskWarehouseAgent
from askwarehouse.core.pipeline_config import PipelineConfig
from askwarehouse.eval.bird_pipeline import results_match
from askwarehouse.execution.connection import readonly_connection


@dataclass
class GoldOutcome:
    id: int
    question: str
    tag: str
    gold_sql: str
    pred_sql: str
    status: str
    exec_correct: bool
    attempts_used: int
    llm_calls: int
    latency_ms: float
    sanity_findings: list


def run_own_warehouse_eval(gold_path: str = "eval/gold/own_warehouse_gold.json",
                            out_path: str = "eval/results/own_warehouse_eval.json") -> dict:
    from askwarehouse.providers.local import LocalProvider

    with open(gold_path) as f:
        gold = json.load(f)

    provider = LocalProvider()
    agent = AskWarehouseAgent(provider, dialect="duckdb", pipeline_config=PipelineConfig())

    outcomes = []
    for item in gold:
        resp = agent.ask(item["question"], skip_ambiguity=True)

        exec_correct = False
        pred_sql = resp.sql
        if resp.status == "answered" and resp.result and resp.result.success:
            with readonly_connection() as con:
                gold_rows = con.execute(item["gold_sql"]).fetchall()
            exec_correct = results_match(resp.result.rows, gold_rows)

        outcomes.append(GoldOutcome(
            id=item["id"], question=item["question"], tag=item["tag"],
            gold_sql=item["gold_sql"], pred_sql=pred_sql, status=resp.status,
            exec_correct=exec_correct, attempts_used=len(resp.attempts),
            llm_calls=resp.llm_calls, latency_ms=resp.total_latency_ms,
            sanity_findings=[f.code for f in resp.sanity_findings],
        ))
        mark = "OK" if exec_correct else "MISS"
        print(f"  #{item['id']:3d} [{mark}] ({resp.status}) {item['question'][:70]}")

    n = len(outcomes)
    latencies = sorted(o.latency_ms for o in outcomes)
    p95 = latencies[min(len(latencies) - 1, int(round(0.95 * (len(latencies) - 1))))]
    summary = {
        "n_total": n,
        "exec_accuracy": sum(o.exec_correct for o in outcomes) / n,
        "valid_sql_pct": sum(o.status == "answered" for o in outcomes) / n,
        "avg_attempts": sum(o.attempts_used for o in outcomes) / n,
        "avg_llm_calls": sum(o.llm_calls for o in outcomes) / n,
        "p95_latency_ms": p95,
        "by_tag": {},
        "outcomes": [asdict(o) for o in outcomes],
    }

    tags = sorted(set(o.tag for o in outcomes))
    for tag in tags:
        tag_outcomes = [o for o in outcomes if o.tag == tag]
        summary["by_tag"][tag] = {
            "n": len(tag_outcomes),
            "exec_accuracy": sum(o.exec_correct for o in tag_outcomes) / len(tag_outcomes),
        }

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\nexec_accuracy={summary['exec_accuracy']:.2%}  valid_sql_pct={summary['valid_sql_pct']:.2%}  "
          f"avg_attempts={summary['avg_attempts']:.2f}  p95_latency={summary['p95_latency_ms']:.0f}ms")
    return summary


if __name__ == "__main__":
    run_own_warehouse_eval()
