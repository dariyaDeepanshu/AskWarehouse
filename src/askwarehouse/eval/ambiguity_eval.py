"""Scores the ambiguity checker against eval/ambiguity/labeled_set.json.
Reports precision/recall plus, explicitly, the over-ask rate (false
positives on genuinely clear questions) and under-ask rate (false negatives
on genuinely ambiguous ones) -- the brief calls out that over-asking is as
bad as guessing, so both directions need their own number, not just
accuracy."""
import json
from dataclasses import asdict, dataclass

from askwarehouse.core.ambiguity import AmbiguityChecker
from askwarehouse.retrieval.schema_index import SchemaIndex


@dataclass
class AmbiguityEvalRow:
    id: int
    question: str
    true_label: str
    predicted_label: str
    correct: bool
    reason_given: str
    model_reason: str


def run_ambiguity_eval(labeled_path: str = "eval/ambiguity/labeled_set.json",
                        out_path: str = "eval/results/ambiguity_eval.json") -> dict:
    from askwarehouse.providers.local import LocalProvider

    with open(labeled_path) as f:
        labeled = json.load(f)

    provider = LocalProvider()
    checker = AmbiguityChecker(provider)
    schema_index = SchemaIndex()

    rows = []
    for item in labeled:
        schema_context = schema_index.render_prompt_schema(item["question"], top_k=4)
        result = checker.check(item["question"], schema_context)
        predicted = "ambiguous" if result.is_ambiguous else "clear"
        rows.append(AmbiguityEvalRow(
            id=item["id"], question=item["question"], true_label=item["label"],
            predicted_label=predicted, correct=(predicted == item["label"]),
            reason_given=item["reason"], model_reason=result.reason,
        ))
        print(f"  #{item['id']:2d} true={item['label']:9s} pred={predicted:9s} "
              f"{'OK' if predicted == item['label'] else 'MISS'}  {item['question'][:60]}")

    tp = sum(1 for r in rows if r.true_label == "ambiguous" and r.predicted_label == "ambiguous")
    fn = sum(1 for r in rows if r.true_label == "ambiguous" and r.predicted_label == "clear")
    fp = sum(1 for r in rows if r.true_label == "clear" and r.predicted_label == "ambiguous")
    tn = sum(1 for r in rows if r.true_label == "clear" and r.predicted_label == "clear")

    n_ambiguous = tp + fn
    n_clear = fp + tn
    summary = {
        "n_total": len(rows),
        "n_ambiguous": n_ambiguous,
        "n_clear": n_clear,
        "accuracy": (tp + tn) / len(rows),
        "precision": tp / (tp + fp) if (tp + fp) else None,
        "recall": tp / (tp + fn) if (tp + fn) else None,
        "over_ask_rate": fp / n_clear if n_clear else None,   # asked when it shouldn't have
        "under_ask_rate": fn / n_ambiguous if n_ambiguous else None,  # guessed when it should have asked
        "confusion": {"tp": tp, "fn": fn, "fp": fp, "tn": tn},
        "rows": [asdict(r) for r in rows],
    }

    import os
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\naccuracy={summary['accuracy']:.2%}  precision={summary['precision']:.2%}  "
          f"recall={summary['recall']:.2%}")
    print(f"over_ask_rate={summary['over_ask_rate']:.2%}  under_ask_rate={summary['under_ask_rate']:.2%}")
    return summary


if __name__ == "__main__":
    run_ambiguity_eval()
