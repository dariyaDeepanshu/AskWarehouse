"""
Safety configuration for AskWarehouse.

DuckDB has no Postgres-style GRANT/role system, so "read-only at the database
level" here means two concrete, code-enforced things instead of a prompt
instruction:

  1. The execution connection is opened with `read_only=True` (see
     execution/connection.py). This is enforced by DuckDB's storage engine:
     any write attempt raises before it can touch the file, regardless of
     what SQL text reaches the connection.
  2. Every query is parsed to an AST with sqlglot (see safety/guards.py)
     before a connection is ever opened, and rejected if its root is not
     SELECT/WITH, if it references a schema outside ALLOWED_SCHEMAS, or if
     it touches a column on PII_DENYLIST.

Both checks are independent of the model's behavior -- a compromised or
badly-prompted model cannot bypass either one from the SQL text alone.
"""
import os
from dataclasses import dataclass, field

# Paths are env-overridable so the serverless deployment can point the
# warehouse at a bundled read-only file and the (ephemeral) audit/cache DBs
# at a writable /tmp location.
WAREHOUSE_PATH = os.environ.get("ASKWAREHOUSE_WAREHOUSE_PATH", "data/warehouse/warehouse.duckdb")
AUDIT_DB_PATH = os.environ.get("ASKWAREHOUSE_AUDIT_DB_PATH", "data/warehouse/audit.duckdb")
CACHE_DB_PATH = os.environ.get("ASKWAREHOUSE_CACHE_DB_PATH", "data/warehouse/cache.duckdb")

# Only these schemas are queryable by the agent. `main_staging` and the raw
# `raw` schema are deliberately excluded -- they hold pre-normalization data
# (mixed date formats, dirty casing) and un-curated metric logic; the agent
# should only ever see the modeled star schema and the semantic layer.
ALLOWED_SCHEMAS = {"main_marts", "main_semantic", "main"}  # "main" = seeds (us_states)

# (table, column) pairs the agent may never select, filter on, or return.
# email/phone/birth_date are direct-contact / sensitive-identity PII and are
# blocked outright. full_name/first_name/last_name are allowed because
# legitimate business questions ("who are the top 10 customers by revenue")
# need a human-readable identifier -- blocking those would just make the
# agent paraphrase the question incorrectly, not protect anyone.
PII_DENYLIST = {
    ("dim_customers", "email"),
    ("dim_customers", "phone"),
    ("dim_customers", "birth_date"),
}

MAX_ROWS = 5_000              # LIMIT injected if the query has none or a higher one
STATEMENT_TIMEOUT_SECONDS = 15
MAX_EXPLAIN_ROW_ESTIMATE = 50_000_000  # reject on EXPLAIN if DuckDB estimates more rows than this
MAX_REPAIR_ATTEMPTS = 3
MAX_STATEMENTS_PER_QUERY = 1  # sqlglot must parse exactly one statement


@dataclass(frozen=True)
class SafetyConfig:
    warehouse_path: str = WAREHOUSE_PATH
    audit_db_path: str = AUDIT_DB_PATH
    cache_db_path: str = CACHE_DB_PATH
    allowed_schemas: frozenset = field(default_factory=lambda: frozenset(ALLOWED_SCHEMAS))
    pii_denylist: frozenset = field(default_factory=lambda: frozenset(PII_DENYLIST))
    max_rows: int = MAX_ROWS
    statement_timeout_seconds: int = STATEMENT_TIMEOUT_SECONDS
    max_explain_row_estimate: int = MAX_EXPLAIN_ROW_ESTIMATE
    max_repair_attempts: int = MAX_REPAIR_ATTEMPTS
    max_statements_per_query: int = MAX_STATEMENTS_PER_QUERY


DEFAULT_SAFETY_CONFIG = SafetyConfig()
