"""Builds the 100-failure taxonomy: pools failing outcomes from the BIRD
ablation's best config (5_plus_repair_loop, the closest to the deployed
pipeline) and the own-warehouse gold eval, re-executes each failing
predicted SQL (cheap -- no LLM call, just SQLite/DuckDB) to recover the
actual DB error text that wasn't persisted in the summary JSON, then runs
the rule-based classifier over the pooled set."""
import glob
import json
import os
import random
import sqlite3

from askwarehouse.eval.failure_taxonomy import build_taxonomy
from askwarehouse.execution.connection import readonly_connection

HF_CACHE = os.path.expanduser("~/.cache/huggingface/hub")
DB_ROOT = glob.glob(os.path.join(
    HF_CACHE, "datasets--premai-io--birdbench", "snapshots", "*", "validation", "dev_databases"
))[0]


def recover_bird_error(db_id: str, pred_sql: str) -> str | None:
    db_path = os.path.join(DB_ROOT, db_id, f"{db_id}.sqlite")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        con.execute(pred_sql).fetchall()
        return None  # ran fine -- wrong answer, not a DB error
    except Exception as e:
        return str(e)
    finally:
        con.close()


def recover_own_warehouse_error(pred_sql: str) -> str | None:
    try:
        with readonly_connection() as con:
            con.execute(pred_sql).fetchall()
        return None
    except Exception as e:
        return str(e)


def main():
    with open("eval/results/bird_ablation.json") as f:
        bird_configs = json.load(f)
    best_config = next(c for c in bird_configs if c["config_name"] == "5_plus_repair_loop")
    bird_failures = [o for o in best_config["outcomes"] if not o["exec_correct"]]

    with open("eval/results/own_warehouse_eval.json") as f:
        own_wh = json.load(f)
    own_failures = [o for o in own_wh["outcomes"] if not o["exec_correct"]]

    print(f"BIRD failures available: {len(bird_failures)} / {best_config['n_questions']}")
    print(f"Own-warehouse failures available: {len(own_failures)} / {own_wh['n_total']}")

    rng = random.Random(7)
    n_target = 100
    # proportional sample from both pools, capped at what's available
    n_bird = min(len(bird_failures), round(n_target * len(bird_failures) / max(1, len(bird_failures) + len(own_failures))))
    n_own = min(len(own_failures), n_target - n_bird)
    sampled_bird = rng.sample(bird_failures, n_bird) if n_bird else []
    sampled_own = rng.sample(own_failures, n_own) if n_own else []
    print(f"sampling {len(sampled_bird)} BIRD + {len(sampled_own)} own-warehouse = {len(sampled_bird)+len(sampled_own)} failures")

    bird_rows = []
    for o in sampled_bird:
        err = recover_bird_error(o["db_id"], o["pred_sql"])
        bird_rows.append({
            "question": o["question"], "pred_sql": o["pred_sql"], "gold_sql": o["gold_sql"],
            "error": err, "exec_correct": False,
        })

    own_rows = []
    for o in sampled_own:
        err = recover_own_warehouse_error(o["pred_sql"])
        own_rows.append({
            "question": o["question"], "pred_sql": o["pred_sql"], "gold_sql": o["gold_sql"],
            "error": err, "exec_correct": False,
        })

    build_taxonomy([("bird_mini_dev", bird_rows), ("own_warehouse", own_rows)])


if __name__ == "__main__":
    main()
