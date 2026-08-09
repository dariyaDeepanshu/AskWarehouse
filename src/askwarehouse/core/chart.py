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

DATE_HINT_NAMES = {"date", "order_date", "month", "day", "year", "quarter", "date_day", "month_name"}


@dataclass
class ChartResult:
    kind: str  # 'single_value' | 'bar' | 'line' | 'table_only'
    png_base64: str | None = None
    note: str = ""


def _is_numeric(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def choose_chart_kind(columns: list, rows: list) -> str:
    if not rows or not columns:
        return "table_only"
    if len(rows) == 1 and len(columns) <= 2:
        return "single_value"
    if len(columns) < 2:
        return "table_only"
    if len(rows) > 100:
        return "table_only"

    first_col_is_dateish = columns[0].lower() in DATE_HINT_NAMES or "date" in columns[0].lower()
    second_col_numeric = all(_is_numeric(r[1]) for r in rows if r[1] is not None)

    if not second_col_numeric:
        return "table_only"
    if first_col_is_dateish:
        return "line"
    return "bar"


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
