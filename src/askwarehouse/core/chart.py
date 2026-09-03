"""Auto chart selection + rendering. Deliberately simple, rule-based
selection (not another LLM call) -- what chart to draw is fully determined
by the shape of the result set, so there's no ambiguity for a model to
resolve here."""
import base64
import io
from dataclasses import dataclass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from askwarehouse.core.chart_spec import DATE_HINT_NAMES, choose_chart_kind  # noqa: F401


@dataclass
class ChartResult:
    kind: str  # 'single_value' | 'bar' | 'line' | 'table_only'
    png_base64: str | None = None
    note: str = ""


def render_chart(columns: list, rows: list, title: str = "") -> ChartResult:
    kind = choose_chart_kind(columns, rows)

    if kind == "single_value":
        return ChartResult(kind="single_value", note=f"{columns[0]} = {rows[0][0]}")
    if kind == "table_only":
        return ChartResult(kind="table_only", note="Result shape isn't a simple 2-column series; showing as a table.")

    labels = [str(r[0]) for r in rows]
    values = [r[1] if r[1] is not None else 0 for r in rows]

    fig, ax = plt.subplots(figsize=(7, 4), dpi=110)
    if kind == "line":
        ax.plot(labels, values, marker="o", linewidth=1.8)
        ax.tick_params(axis="x", rotation=45)
    else:
        ax.bar(labels, values)
        if len(labels) > 8:
            ax.tick_params(axis="x", rotation=60)

    ax.set_xlabel(columns[0])
    ax.set_ylabel(columns[1])
    if title:
        ax.set_title(title, fontsize=11)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return ChartResult(kind=kind, png_base64=base64.b64encode(buf.read()).decode("ascii"))
