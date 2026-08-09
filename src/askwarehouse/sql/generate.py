from dataclasses import dataclass

from askwarehouse.providers.base import Provider
from askwarehouse.sql.prompts import (
    DIALECT_NOTES, GENERATE_SYSTEM, CRITIQUE_SYSTEM,
    build_generate_user_prompt, build_critique_user_prompt, build_repair_user_prompt,
)
from askwarehouse.sql.util import clean_sql


@dataclass
class GenerationResult:
    sql: str
    raw: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float


class SQLGenerator:
    def __init__(self, provider: Provider, dialect: str = "duckdb"):
        assert dialect in DIALECT_NOTES, f"unsupported dialect {dialect}"
        self.provider = provider
        self.dialect = dialect

    def generate(self, question: str, schema_context: str, value_hints: str = "",
                 plan_text: str = "") -> GenerationResult:
        system = GENERATE_SYSTEM.format(dialect=self.dialect, dialect_note=DIALECT_NOTES[self.dialect])
        user = build_generate_user_prompt(question, schema_context, value_hints, plan_text)
        resp = self.provider.generate(system, user, max_tokens=500, temperature=0.0)
        return GenerationResult(
            sql=clean_sql(resp.text), raw=resp.text,
            prompt_tokens=resp.prompt_tokens, completion_tokens=resp.completion_tokens,
            latency_ms=resp.latency_ms,
        )

    def critique(self, question: str, schema_context: str, value_hints: str,
                 plan_text: str, sql: str) -> GenerationResult:
        user = build_critique_user_prompt(question, schema_context, value_hints, plan_text, sql)
        resp = self.provider.generate(CRITIQUE_SYSTEM, user, max_tokens=500, temperature=0.0)
        return GenerationResult(
            sql=clean_sql(resp.text), raw=resp.text,
            prompt_tokens=resp.prompt_tokens, completion_tokens=resp.completion_tokens,
            latency_ms=resp.latency_ms,
        )

    def repair(self, question: str, schema_context: str, failed_sql: str,
               error_message: str) -> GenerationResult:
        system = GENERATE_SYSTEM.format(dialect=self.dialect, dialect_note=DIALECT_NOTES[self.dialect])
        user = build_repair_user_prompt(question, schema_context, failed_sql, error_message)
        resp = self.provider.generate(system, user, max_tokens=500, temperature=0.0)
        return GenerationResult(
            sql=clean_sql(resp.text), raw=resp.text,
            prompt_tokens=resp.prompt_tokens, completion_tokens=resp.completion_tokens,
            latency_ms=resp.latency_ms,
        )
