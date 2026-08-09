import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

with open("eval/failure_taxonomy/taxonomy.json") as f:
    data = json.load(f)

counts = data["category_counts"]
labels = list(counts.keys())
values = [counts[k] for k in labels]
colors = ["#b5561d", "#d97a34", "#e8a165", "#5b6472", "#9aa4b2", "#c7ccd3"]

fig, ax = plt.subplots(figsize=(6.5, 6.5), dpi=130)
wedges, texts, autotexts = ax.pie(
    values, labels=[f"{l}\n({v})" for l, v in zip(labels, values)],
    autopct="%1.0f%%", colors=colors[:len(labels)], startangle=90,
    textprops={"fontsize": 10},
)
ax.set_title(f"Failure taxonomy (n={data['n_failures']}, BIRD config-5 + own-warehouse gold)", fontsize=11)
fig.tight_layout()
fig.savefig("eval/failure_taxonomy/taxonomy_pie.png")
print("saved eval/failure_taxonomy/taxonomy_pie.png")
