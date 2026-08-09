"""Runs the ablation ladder against a sampled subset of BIRD mini-dev.
Per-database catalog/schema-index/value-index are built once per db_id and
reused across every config and every question against that db -- only the
LLM-facing pipeline changes per config, matching how the ablation table is
supposed to isolate exactly one variable at a time."""
import glob
import json
import os
import random
import time
from dataclasses import asdict, dataclass, field

from askwarehouse.eval.bird_catalog import build_bird_catalog
from askwarehouse.eval.bird_pipeline import run_bird_question, execute_sqlite_readonly, results_match
from askwarehouse.eval.bird_value_index import BirdValueIndex
from askwarehouse.retrieval.schema_index import SchemaIndex
from askwarehouse.sql.generate import SQLGenerator

HF_CACHE = os.path.expanduser("~/.cache/huggingface/hub")
QUESTIONS_JSON = glob.glob(os.path.join(
    HF_CACHE, "datasets--birdsql--bird_mini_dev", "snapshots", "*", "data", "mini_dev_sqlite-00000-of-00001.json"
))[0]
DB_ROOT = glob.glob(os.path.join(
    HF_CACHE, "datasets--premai-io--birdbench", "snapshots", "*", "validation", "dev_databases"
))[0]

ABLATION_LADDER = [
    ("1_single_shot_full_schema", dict(use_schema_retrieval=False, use_value_index=False, use_self_critique=False, use_repair_loop=False)),
    ("2_plus_schema_retrieval", dict(use_schema_retrieval=True, use_value_index=False, use_self_critique=False, use_repair_loop=False)),
    ("3_plus_value_index", dict(use_schema_retrieval=True, use_value_index=True, use_self_critique=False, use_repair_loop=False)),
    ("4_plus_self_critique", dict(use_schema_retrieval=True, use_value_index=True, use_self_critique=True, use_repair_loop=False)),
    ("5_plus_repair_loop", dict(use_schema_retrieval=True, use_value_index=True, use_self_critique=True, use_repair_loop=True)),
]


def load_questions() -> list:
    with open(QUESTIONS_JSON) as f:
        return json.load(f)


def sample_questions(questions: list, n: int, seed: int = 7) -> list:
    rng = random.Random(seed)
    by_difficulty = {}
    for q in questions:
        by_difficulty.setdefault(q["difficulty"], []).append(q)
    total = len(questions)
    sampled = []
    for diff, group in by_difficulty.items():
        k = max(1, round(n * len(group) / total))
        sampled.extend(rng.sample(group, min(k, len(group))))
    rng.shuffle(sampled)
    return sampled[:n]


class DbResources:
    _cache: dict = {}

    @classmethod
    def get(cls, db_id: str):
        if db_id not in cls._cache:
            db_path = os.path.join(DB_ROOT, db_id, f"{db_id}.sqlite")
            catalog = build_bird_catalog(db_path)
            known_tables = {t.name.lower() for t in catalog}
            schema_index = SchemaIndex(tables=catalog)
            value_index = BirdValueIndex(db_path)
            cls._cache[db_id] = dict(db_path=db_path, catalog=catalog, known_tables=known_tables,
                                      schema_index=schema_index, value_index=value_index)
        return cls._cache[db_id]


@dataclass
class QuestionOutcome:
    question_id: int
    db_id: str
    difficulty: str
    question: str
    gold_sql: str
    pred_sql: str
    valid_sql: bool
    exec_correct: bool
    attempts_used: int
    llm_calls: int
    latency_ms: float


@dataclass
class ConfigSummary:
    config_name: str
    n_questions: int
    exec_accuracy: float
    valid_sql_pct: float
    avg_attempts: float
    p50_latency_ms: float
    p95_latency_ms: float
    avg_llm_calls: float
    outcomes: list = field(default_factory=list)  # list[QuestionOutcome]


def _percentile(values: list, p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))
    return s[idx]


def run_config(config_name: str, flags: dict, sampled_questions: list, generator: SQLGenerator,
               top_k: int = 4, progress_every: int = 10) -> ConfigSummary:
    outcomes = []
    t_start = time.time()
    for i, q in enumerate(sampled_questions):
        res = DbResources.get(q["db_id"])

        if flags["use_schema_retrieval"]:
            schema_context = res["schema_index"].render_prompt_schema(q["question"], top_k=top_k)
        else:
            schema_context = res["schema_index"].render_full_schema()

        value_hints = res["value_index"].render_prompt_hints(q["question"]) if flags["use_value_index"] else ""

        result = run_bird_question(
            question=q["question"], evidence=q.get("evidence", ""), db_id=q["db_id"],
            db_path=res["db_path"], question_id=q["question_id"], difficulty=q["difficulty"],
            known_tables=res["known_tables"], schema_context=schema_context, value_hints=value_hints,
            generator=generator, use_self_critique=flags["use_self_critique"],
            use_repair_loop=flags["use_repair_loop"],
        )

        gold_result = execute_sqlite_readonly(res["db_path"], q["SQL"])
        exec_correct = False
        if result.exec_result and result.exec_result.success and gold_result.success:
            exec_correct = results_match(result.exec_result.rows, gold_result.rows)

        outcomes.append(QuestionOutcome(
            question_id=q["question_id"], db_id=q["db_id"], difficulty=q["difficulty"],
            question=q["question"], gold_sql=q["SQL"], pred_sql=result.final_sql,
            valid_sql=result.valid_sql, exec_correct=exec_correct,
            attempts_used=len(result.attempts), llm_calls=result.llm_calls,
            latency_ms=result.total_latency_ms,
        ))

        if (i + 1) % progress_every == 0:
            elapsed = time.time() - t_start
            acc_so_far = sum(o.exec_correct for o in outcomes) / len(outcomes)
            print(f"  [{config_name}] {i+1}/{len(sampled_questions)}  "
                  f"acc_so_far={acc_so_far:.2%}  elapsed={elapsed:.0f}s", flush=True)

    n = len(outcomes)
    latencies = [o.latency_ms for o in outcomes]
    return ConfigSummary(
        config_name=config_name, n_questions=n,
        exec_accuracy=sum(o.exec_correct for o in outcomes) / n,
        valid_sql_pct=sum(o.valid_sql for o in outcomes) / n,
        avg_attempts=sum(o.attempts_used for o in outcomes) / n,
        p50_latency_ms=_percentile(latencies, 50),
        p95_latency_ms=_percentile(latencies, 95),
        avg_llm_calls=sum(o.llm_calls for o in outcomes) / n,
        outcomes=outcomes,
    )


def run_ablation(n_per_config: int = 100, out_path: str = "eval/results/bird_ablation.json"):
    from askwarehouse.providers.local import LocalProvider
    provider = LocalProvider()
    generator = SQLGenerator(provider, dialect="sqlite")

    questions = load_questions()
    sampled = sample_questions(questions, n_per_config)
    print(f"sampled {len(sampled)} questions across {len(set(q['db_id'] for q in sampled))} databases")

    summaries = []
    for config_name, flags in ABLATION_LADDER:
        print(f"\n=== running config: {config_name} ({flags}) ===")
        summary = run_config(config_name, flags, sampled, generator)
        print(f"  DONE {config_name}: exec_accuracy={summary.exec_accuracy:.2%} "
              f"valid_sql={summary.valid_sql_pct:.2%} avg_attempts={summary.avg_attempts:.2f} "
              f"p95_latency={summary.p95_latency_ms:.0f}ms")
        summaries.append(summary)

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w") as f:
            json.dump([asdict(s) for s in summaries], f, indent=2, default=str)

    return summaries


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    run_ablation(n_per_config=n)
