"""The orchestrator: wires schema retrieval -> ambiguity check -> plan ->
generate -> self-critique -> guards+execute+repair -> sanity checks into one
call. Every stage is gated by a PipelineConfig flag so this exact code path
is what both the interactive CLI/UI and the ablation eval harness run --
the eval table measures this pipeline, not a separate reimplementation."""
import time
import uuid
from dataclasses import dataclass, field

from askwarehouse.core.ambiguity import AmbiguityChecker, AmbiguityResult
from askwarehouse.core.cache import SQLCache
from askwarehouse.core.planner import Planner
from askwarehouse.core.pipeline_config import PipelineConfig
from askwarehouse.core.sanity import run_sanity_checks, SanityFinding
from askwarehouse.execution.audit import AuditLogger
from askwarehouse.execution.repair import run_with_repair, AttemptRecord
from askwarehouse.execution.sandbox import ExecutionResult
from askwarehouse.providers.base import Provider
from askwarehouse.retrieval.catalog import build_catalog
from askwarehouse.retrieval.schema_index import SchemaIndex
from askwarehouse.retrieval.value_index import ValueIndex
from askwarehouse.safety.config import SafetyConfig, DEFAULT_SAFETY_CONFIG
from askwarehouse.sql.generate import SQLGenerator


@dataclass
class AgentResponse:
    question: str
    status: str  # 'answered' | 'clarification_needed' | 'failed'
    sql: str = ""
    result: ExecutionResult | None = None
    attempts: list = field(default_factory=list)          # list[AttemptRecord]
    sanity_findings: list = field(default_factory=list)    # list[SanityFinding]
    ambiguity: AmbiguityResult | None = None
    clarifying_question: str | None = None
    cache_hit: bool = False
    schema_context: str = ""
    value_hints: str = ""
    plan_text: str = ""
    total_latency_ms: float = 0.0
    llm_calls: int = 0


class AskWarehouseAgent:
    def __init__(self, provider: Provider, dialect: str = "duckdb",
                 config: SafetyConfig = DEFAULT_SAFETY_CONFIG,
                 pipeline_config: PipelineConfig = PipelineConfig(),
                 schema_index: SchemaIndex | None = None,
                 value_index: ValueIndex | None = None,
                 audit: AuditLogger | None = None):
        self.provider = provider
        self.dialect = dialect
        self.config = config
        self.pipeline_config = pipeline_config
        self.audit = audit or AuditLogger(config)

        schemas_override = None
        if not pipeline_config.use_semantic_layer:
            schemas_override = set(config.allowed_schemas) - {"main_semantic"}

        self.catalog = build_catalog(config, schemas_override=schemas_override)
        self.known_tables = {t.name.lower() for t in self.catalog} | {"us_states"}

        # built regardless of use_schema_retrieval: it's also what powers
        # render_full_schema() for the "no retrieval" ablation arm
        self.schema_index = schema_index or SchemaIndex(tables=self.catalog)

        self.value_index = None
        if pipeline_config.use_value_index:
            self.value_index = value_index or ValueIndex(config)

        self.ambiguity_checker = AmbiguityChecker(provider)
        self.planner = Planner(provider)
        self.generator = SQLGenerator(provider, dialect=dialect)
        self.cache = SQLCache(config) if pipeline_config.use_cache else None

    def ask(self, question: str, session_id: str | None = None,
            skip_ambiguity: bool = False) -> AgentResponse:
        session_id = session_id or str(uuid.uuid4())
        t_start = time.perf_counter()
        llm_calls = 0
        pc = self.pipeline_config

        if pc.use_schema_retrieval:
            schema_context = self.schema_index.render_prompt_schema(question, top_k=pc.top_k_tables)
        else:
            schema_context = self.schema_index.render_full_schema()

        value_hints = self.value_index.render_prompt_hints(question) if pc.use_value_index else ""

        if self.cache is not None:
            cached = self.cache.get(question)
            if cached is not None:
                repair_result = run_with_repair(
                    question, cached.sql_text, schema_context, self.known_tables,
                    self.generator, self.config, self.audit, session_id,
                )
                findings = run_sanity_checks(repair_result.final_sql, repair_result.final, self.dialect) \
                    if repair_result.final else []
                return AgentResponse(
                    question=question, status="answered" if repair_result.succeeded else "failed",
                    sql=repair_result.final_sql, result=repair_result.final,
                    attempts=repair_result.attempts, sanity_findings=findings, cache_hit=True,
                    schema_context=schema_context, value_hints=value_hints,
                    total_latency_ms=(time.perf_counter() - t_start) * 1000, llm_calls=0,
                )

        ambiguity_result = None
        if pc.use_ambiguity_check and not skip_ambiguity:
            ambiguity_result = self.ambiguity_checker.check(question, schema_context)
            llm_calls += 1
            if ambiguity_result.is_ambiguous:
                return AgentResponse(
                    question=question, status="clarification_needed", ambiguity=ambiguity_result,
                    clarifying_question=ambiguity_result.clarifying_question,
                    schema_context=schema_context, value_hints=value_hints,
                    total_latency_ms=(time.perf_counter() - t_start) * 1000, llm_calls=llm_calls,
                )

        plan_text = ""
        plan = self.planner.plan(question, schema_context, value_hints)
        llm_calls += 1
        plan_text = plan.text

        gen = self.generator.generate(question, schema_context, value_hints, plan_text)
        llm_calls += 1
        sql = gen.sql

        if pc.use_self_critique:
            crit = self.generator.critique(question, schema_context, value_hints, plan_text, sql)
            llm_calls += 1
            sql = crit.sql

        effective_config = self.config if pc.use_repair_loop else SafetyConfig(
            **{**self.config.__dict__, "max_repair_attempts": 1}
        )

        repair_result = run_with_repair(
            question, sql, schema_context, self.known_tables, self.generator,
            effective_config, self.audit, session_id,
        )
        llm_calls += max(0, repair_result.attempts_used - 1)  # each retry = 1 more generation call

        if repair_result.succeeded and self.cache is not None:
            self.cache.put(question, repair_result.final_sql)

        findings = run_sanity_checks(repair_result.final_sql, repair_result.final, self.dialect) \
            if repair_result.final else []

        return AgentResponse(
            question=question,
            status="answered" if repair_result.succeeded else "failed",
            sql=repair_result.final_sql,
            result=repair_result.final,
            attempts=repair_result.attempts,
            sanity_findings=findings,
            ambiguity=ambiguity_result,
            schema_context=schema_context,
            value_hints=value_hints,
            plan_text=plan_text,
            total_latency_ms=(time.perf_counter() - t_start) * 1000,
            llm_calls=llm_calls,
        )
