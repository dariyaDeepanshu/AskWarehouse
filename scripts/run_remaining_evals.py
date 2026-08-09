"""Runs the own-warehouse gold eval and the ambiguity eval back-to-back.
Meant to be launched right after the BIRD ablation run finishes (same GPU,
sequential to avoid contention)."""
from askwarehouse.eval.own_warehouse_eval import run_own_warehouse_eval
from askwarehouse.eval.ambiguity_eval import run_ambiguity_eval

print("=" * 80)
print("OWN WAREHOUSE GOLD EVAL")
print("=" * 80)
run_own_warehouse_eval()

print()
print("=" * 80)
print("AMBIGUITY EVAL")
print("=" * 80)
run_ambiguity_eval()

print("\nALL REMAINING EVALS DONE")
