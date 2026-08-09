"""Categorizes failing outcomes (from the BIRD ablation run and/or the own-
warehouse gold eval) into a fixed taxonomy: schema_linking, join_path,
aggregation_grain, date_logic, ambiguity_external_knowledge, dialect_syntax,
other. Rule-based on the failed SQL / error text / gold SQL diff -- this is
a first-pass classifier meant to be spot-checked and corrected by hand
(see docs/failure_taxonomy_notes.md for the manual review), not treated as
ground truth on its own."""
import json
import re
from collections import Counter

CATEGORIES = [
    "schema_linking", "join_path", "aggregation_grain", "date_logic",
    "ambiguity_external_knowledge", "dialect_syntax", "other",
]


def classify(pred_sql: str, gold_sql: str, error: str | None, exec_correct: bool) -> str:
    if exec_correct:
        return None

    err = (error or "").lower()
    pred = (pred_sql or "").lower()
    gold = (gold_sql or "").lower()

    # 1. schema linking: DB complains about an unknown column/table
    if re.search(r"(no such (column|table)|not found in|catalog error|binder error).*(column|table)", err) or \
       re.search(r"no such (column|table)", err):
        return "schema_linking"

    # 2. dialect / syntax: parser-level complaint, not a binder complaint
    if re.search(r"(syntax error|parser error|near \")", err):
        return "dialect_syntax"

    # 3. date logic: gold or predicted SQL uses date functions and they differ meaningfully,
    # or error mentions date/time conversion
    date_fns = ("strftime", "julianday", "date_trunc", "date_diff", "extract", "interval", "date(")
    if any(f in err for f in ("date", "time", "julian")) or \
       (any(f in gold for f in date_fns) and not any(f in pred for f in date_fns)):
        return "date_logic"

    # 4. join path: predicted SQL's join count/tables differ from gold's, or a join-related DB error
    if "join" in err or _join_signature(pred) != _join_signature(gold):
        return "join_path"

    # 5. aggregation grain: both queries touch the same tables/joins but aggregate functions differ,
    # or predicted result is an integer multiple of a plausible fan-out
    agg_fns = ("sum(", "avg(", "count(")
    if any(f in gold for f in agg_fns) and _agg_signature(pred) != _agg_signature(gold):
        return "aggregation_grain"

    # 6. no execution error at all but still wrong -> likely a values/semantics issue this
    # rule set can't disambiguate from external-knowledge / ambiguity without a human read
    if error is None:
        return "ambiguity_external_knowledge"

    return "other"


def _join_signature(sql: str) -> frozenset:
    # optional schema-qualifier (e.g. "main.comments") must not swallow the
    # table name into the wrong capture group -- take the segment after the
    # last dot, since predicted SQL is often schema-qualified and gold SQL
    # usually isn't (a naive capture makes every schema-qualified predicted
    # join look "different" from gold and floods this category)
    raw = re.findall(r"\bjoin\s+([a-z0-9_\".]+)", sql)
    return frozenset(t.strip('"').split(".")[-1] for t in raw)


def _agg_signature(sql: str) -> frozenset:
    return frozenset(re.findall(r"\b(sum|avg|count|min|max)\s*\(", sql))


def build_taxonomy(sources: list, out_path: str = "eval/failure_taxonomy/taxonomy.json") -> dict:
    """sources: list of (label, list_of_outcome_dicts) where each outcome
    dict has pred_sql/gold_sql/error/exec_correct keys (BIRD outcomes use
    'pred_sql'/'gold_sql'/error from attempts; own-warehouse outcomes match
    the same shape)."""
    all_rows = []
    for label, outcomes in sources:
        for o in outcomes:
            if o.get("exec_correct"):
                continue
            error = o.get("error")
            if error is None and o.get("attempts"):
                last = o["attempts"][-1]
                error = last.get("error") if isinstance(last, dict) else getattr(last, "error", None)
            cat = classify(o.get("pred_sql", ""), o.get("gold_sql", ""), error, False)
            all_rows.append({
                "source": label, "question": o.get("question"), "pred_sql": o.get("pred_sql"),
                "gold_sql": o.get("gold_sql"), "error": error, "category": cat,
            })

    counts = Counter(r["category"] for r in all_rows)
    summary = {
        "n_failures": len(all_rows),
        "category_counts": dict(counts),
        "category_pct": {k: v / len(all_rows) for k, v in counts.items()} if all_rows else {},
        "rows": all_rows,
    }

    import os
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"classified {len(all_rows)} failures:")
    for cat, n in counts.most_common():
        print(f"  {cat}: {n} ({n/len(all_rows):.1%})")
    return summary
