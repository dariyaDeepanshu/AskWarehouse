"""Builds the queryable catalog: introspects DuckDB's information_schema for
the allowed schemas, and merges in the table/column descriptions written in
the dbt schema.yml files. This catalog is the ONLY thing schema retrieval
embeds -- the raw/staging schemas never enter it, so the agent structurally
cannot see them regardless of what the model tries."""
import glob
import os
from dataclasses import dataclass, field

import yaml

from askwarehouse.execution.connection import readonly_connection
from askwarehouse.safety.config import SafetyConfig, DEFAULT_SAFETY_CONFIG, PII_DENYLIST

DBT_MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "dbt_project", "models")


@dataclass
class ColumnInfo:
    name: str
    data_type: str
    description: str = ""
    sample_values: list = field(default_factory=list)
    distinct_count: int | None = None
    is_pii: bool = False


@dataclass
class TableInfo:
    schema: str
    name: str
    description: str = ""
    columns: list = field(default_factory=list)  # list[ColumnInfo]

    @property
    def qualified_name(self) -> str:
        return f"{self.schema}.{self.name}"

    def to_prompt_block(self) -> str:
        lines = [f"TABLE {self.qualified_name}"]
        if self.description:
            lines.append(f"  -- {self.description}")
        for c in self.columns:
            bits = [f"{c.name} {c.data_type}"]
            if c.description:
                bits.append(f"-- {c.description}")
            if c.sample_values:
                bits.append(f"[samples: {', '.join(str(v) for v in c.sample_values[:6])}]")
            lines.append("    " + " ".join(bits))
        return "\n".join(lines)


def _load_descriptions() -> dict:
    """Parses every schema.yml under dbt_project/models into
    {table_name: {"description": str, "columns": {col: desc}}}."""
    out = {}
    for path in glob.glob(os.path.join(DBT_MODELS_DIR, "**", "*.yml"), recursive=True):
        with open(path) as f:
            doc = yaml.safe_load(f) or {}
        for model in doc.get("models", []):
            cols = {}
            for c in model.get("columns", []):
                cols[c["name"]] = c.get("description", "")
            out[model["name"]] = {"description": model.get("description", ""), "columns": cols}
    return out


def build_catalog(config: SafetyConfig = DEFAULT_SAFETY_CONFIG,
                   sample_values_per_column: int = 6,
                   max_cardinality_for_samples: int = 500,
                   schemas_override: set | None = None) -> list:
    """Returns list[TableInfo] for every table/view in an allowed schema.
    schemas_override lets the ablation harness build a catalog with
    main_semantic excluded (the "no semantic layer" arm) without touching
    the safety config's own allowlist."""
    descriptions = _load_descriptions()
    tables: list[TableInfo] = []
    schemas = schemas_override if schemas_override is not None else config.allowed_schemas

    with readonly_connection(config) as con:
        rows = con.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema = ANY(?)
            ORDER BY table_schema, table_name
            """,
            [list(schemas)],
        ).fetchall()

        for table_schema, table_name in rows:
            if table_name == "us_states":
                continue  # handled specially by the value index, not shown as a queryable fact/dim
            meta = descriptions.get(table_name, {})
            cols_meta = meta.get("columns", {})

            col_rows = con.execute(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = ? AND table_name = ?
                ORDER BY ordinal_position
                """,
                [table_schema, table_name],
            ).fetchall()

            columns = []
            for col_name, data_type in col_rows:
                is_pii = (table_name, col_name) in PII_DENYLIST
                samples = []
                if not is_pii and data_type in ("VARCHAR", "BOOLEAN"):
                    try:
                        n_distinct = con.execute(
                            f'SELECT approx_count_distinct("{col_name}") FROM {table_schema}.{table_name}'
                        ).fetchone()[0]
                        if n_distinct and n_distinct <= max_cardinality_for_samples:
                            samples = [
                                r[0] for r in con.execute(
                                    f'SELECT DISTINCT "{col_name}" FROM {table_schema}.{table_name} '
                                    f'WHERE "{col_name}" IS NOT NULL LIMIT {sample_values_per_column}'
                                ).fetchall()
                            ]
                    except Exception:
                        pass
                columns.append(ColumnInfo(
                    name=col_name,
                    data_type=data_type,
                    description=cols_meta.get(col_name, ""),
                    sample_values=samples,
                    is_pii=is_pii,
                ))

            tables.append(TableInfo(
                schema=table_schema,
                name=table_name,
                description=meta.get("description", ""),
                columns=columns,
            ))

    return tables
