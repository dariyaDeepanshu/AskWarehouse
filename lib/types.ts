export type PipelineConfig = {
  use_schema_retrieval: boolean;
  use_value_index: boolean;
  use_self_critique: boolean;
  use_repair_loop: boolean;
  use_semantic_layer: boolean;
  use_cache: boolean;
  use_ambiguity_check: boolean;
};

export const DEFAULT_PIPELINE: PipelineConfig = {
  use_schema_retrieval: true,
  use_value_index: true,
  use_self_critique: true,
  use_repair_loop: true,
  use_semantic_layer: true,
  use_cache: true,
  use_ambiguity_check: true,
};

export type Attempt = {
  attempt_number: number;
  sql: string;
  stage: string;
  outcome: string;
  error: string | null;
  latency_ms: number;
};

export type SanityFinding = { code: string; severity: string; message: string };

export type QueryResult = {
  success: boolean;
  row_count: number;
  columns: string[];
  rows: (string | number | boolean | null)[][];
  latency_ms: number;
  error: string | null;
  timed_out: boolean;
};

export type ChartData = {
  kind: "single_value" | "bar" | "line" | "table_only";
  x_label: string;
  y_label: string;
  labels: string[];
  values: number[];
  note: string;
};

export type AskResponse = {
  question: string;
  status: "answered" | "clarification_needed" | "failed";
  sql: string;
  result: QueryResult | null;
  attempts: Attempt[];
  sanity_findings: SanityFinding[];
  clarifying_question: string | null;
  ambiguity: { is_ambiguous: boolean; reason: string; clarifying_question: string | null } | null;
  cache_hit: boolean;
  schema_context: string;
  value_hints: string;
  plan_text: string;
  total_latency_ms: number;
  llm_calls: number;
  nl_answer?: string | null;
  chart?: ChartData;
};

export type VerifyResponse = {
  match: boolean;
  verify_question: string;
  verify_sql: string;
  original_summary: string;
  verify_summary: string;
  detail: string;
};

export type LlmSettings = {
  provider: "" | "gemini" | "groq" | "anthropic" | "openai";
  key: string;
  model: string;
};

export type ServerConfig = {
  server_key_present: boolean;
  default_models: Record<string, string>;
  rate_limit_per_min: number;
  allowed_schemas: string[];
  pii_denylist: string[];
  max_rows: number;
  statement_timeout_seconds: number;
  max_repair_attempts: number;
};
