"""Reads eval/results/*.json + eval/failure_taxonomy/taxonomy.json and
renders the markdown tables that get spliced into README.md at the
<!-- TAG --> placeholders."""
import json
import re

CONFIG_LABELS = {
    "1_single_shot_full_schema": "Single-shot, full schema",
    "2_plus_schema_retrieval": "+ schema retrieval",
    "3_plus_value_index": "+ value index",
    "4_plus_self_critique": "+ self-critique",
    "5_plus_repair_loop": "+ repair loop",
}


def bird_table() -> str:
    with open("eval/results/bird_ablation.json") as f:
        configs = json.load(f)
    lines = [
        "| Config | BIRD-dev exec acc (n=100) | Valid SQL % | Avg attempts | p50 latency | p95 latency | Avg LLM calls |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in configs:
        label = CONFIG_LABELS.get(c["config_name"], c["config_name"])
        lines.append(
            f"| {label} | {c['exec_accuracy']:.1%} | {c['valid_sql_pct']:.1%} | "
            f"{c['avg_attempts']:.2f} | {c['p50_latency_ms']:.0f} ms | {c['p95_latency_ms']:.0f} ms | "
            f"{c['avg_llm_calls']:.1f} |"
        )
    lines.append("")
    lines.append("$/query: $0.00 (local model, no API cost -- see README for GPU-time-as-cost-proxy note).")

    # marginal value of the repair loop, computed from attempt-level data if available
    return "\n".join(lines)


def own_warehouse_table() -> str:
    with open("eval/results/own_warehouse_eval.json") as f:
        s = json.load(f)
    lines = [
        f"**Overall**: exec accuracy = {s['exec_accuracy']:.1%}, valid SQL % = {s['valid_sql_pct']:.1%}, "
        f"avg attempts = {s['avg_attempts']:.2f}, p95 latency = {s['p95_latency_ms']:.0f} ms "
        f"(n={s['n_total']})",
        "",
        "| Question category | n | Exec accuracy |",
        "|---|---|---|",
    ]
    for tag, stats in sorted(s["by_tag"].items(), key=lambda kv: -kv[1]["exec_accuracy"]):
        lines.append(f"| {tag} | {stats['n']} | {stats['exec_accuracy']:.1%} |")
    return "\n".join(lines)


def ambiguity_table() -> str:
    with open("eval/results/ambiguity_eval.json") as f:
        s = json.load(f)
    lines = [
        f"| Metric | Value |",
        f"|---|---|",
        f"| Accuracy | {s['accuracy']:.1%} |",
        f"| Precision | {s['precision']:.1%} |",
        f"| Recall | {s['recall']:.1%} |",
        f"| **Over-ask rate** (asked on a clear question) | {s['over_ask_rate']:.1%} |",
        f"| **Under-ask rate** (guessed on an ambiguous question) | {s['under_ask_rate']:.1%} |",
        "",
        f"Confusion: TP={s['confusion']['tp']} FN={s['confusion']['fn']} FP={s['confusion']['fp']} TN={s['confusion']['tn']} (n={s['n_total']})",
    ]
    return "\n".join(lines)


def failure_taxonomy_section() -> str:
    with open("eval/failure_taxonomy/taxonomy.json") as f:
        s = json.load(f)
    lines = [
        f"{s['n_failures']} failures categorized (BIRD ablation config 5 + own-warehouse gold eval):",
        "",
        "| Category | Count | % of failures |",
        "|---|---|---|",
    ]
    for cat, pct in sorted(s["category_pct"].items(), key=lambda kv: -kv[1]):
        n = s["category_counts"][cat]
        lines.append(f"| {cat} | {n} | {pct:.1%} |")
    return "\n".join(lines)


def main():
    with open("README.md") as f:
        readme = f.read()

    replacements = {
        "<!-- BIRD_TABLE -->": bird_table(),
        "<!-- OWN_WAREHOUSE_TABLE -->": own_warehouse_table(),
        "<!-- AMBIGUITY_TABLE -->": ambiguity_table(),
        "<!-- FAILURE_TAXONOMY -->": failure_taxonomy_section(),
    }
    for tag, content in replacements.items():
        readme = readme.replace(tag, content)

    with open("README.md", "w") as f:
        f.write(readme)
    print("README.md updated with eval tables")


if __name__ == "__main__":
    main()
