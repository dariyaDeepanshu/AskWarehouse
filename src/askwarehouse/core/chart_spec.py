"""Rule-based chart selection, with no rendering dependency.

The original build rendered a PNG server-side with matplotlib. The web
deployment instead returns this spec and the browser draws the chart, so
the serverless bundle carries no plotting stack. `chart.py` re-uses
`choose_chart_kind` from here for the CLI's PNG output.
"""
from dataclasses import dataclass, field

DATE_HINT_NAMES = {"date", "order_date", "month", "day", "year", "quarter", "date_day", "month_name"}


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


@dataclass
class ChartSpec:
    kind: str                       # 'single_value' | 'bar' | 'line' | 'table_only'
    x_label: str = ""
    y_label: str = ""
    labels: list = field(default_factory=list)
    values: list = field(default_factory=list)
    note: str = ""


def build_chart_spec(columns: list, rows: list) -> ChartSpec:
    kind = choose_chart_kind(columns, rows)
    if kind == "single_value":
        return ChartSpec(kind=kind, note=f"{columns[0]} = {rows[0][0]}")
    if kind == "table_only":
        return ChartSpec(kind=kind,
                         note="Result shape isn't a simple 2-column series; showing as a table.")
    return ChartSpec(
        kind=kind,
        x_label=columns[0],
        y_label=columns[1],
        labels=[str(r[0]) for r in rows],
        values=[r[1] if r[1] is not None else 0 for r in rows],
    )
