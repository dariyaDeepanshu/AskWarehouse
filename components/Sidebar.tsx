"use client";

import { useEffect, useState } from "react";
import type { LlmSettings, PipelineConfig, ServerConfig } from "@/lib/types";
import { getAudit } from "@/lib/api";

const STAGE_META: { key: keyof PipelineConfig; label: string; hint: string }[] = [
  { key: "use_ambiguity_check", label: "Ambiguity gate", hint: "Ask a clarifying question when the SQL genuinely forks" },
  { key: "use_schema_retrieval", label: "Schema retrieval", hint: "BM25 over the modeled schema — never dump the whole thing" },
  { key: "use_value_index", label: "Value index", hint: "Map “California” → the stored code “CA” before generation" },
  { key: "use_self_critique", label: "Self-critique pass", hint: "A second model pass checks grain / joins / filters" },
  { key: "use_repair_loop", label: "Repair loop", hint: "Feed the DB's exact error back and retry (max 3)" },
  { key: "use_semantic_layer", label: "Semantic layer", hint: "Expose the canonical metric_* views" },
  { key: "use_cache", label: "Fingerprint cache", hint: "Reuse SQL for a repeated question (schema-version aware)" },
];

export default function Sidebar({
  pipeline,
  setPipeline,
  llm,
  setLlm,
  config,
}: {
  pipeline: PipelineConfig;
  setPipeline: (p: PipelineConfig) => void;
  llm: LlmSettings;
  setLlm: (s: LlmSettings) => void;
  config: ServerConfig | null;
}) {
  const [audit, setAudit] = useState<Record<string, any>[]>([]);
  const [auditOpen, setAuditOpen] = useState(false);

  useEffect(() => {
    if (!auditOpen) return;
    getAudit(12).then(setAudit).catch(() => setAudit([]));
  }, [auditOpen]);

  return (
    <aside className="sidebar">
      <h1>AskWarehouse</h1>
      <div className="tag">text-to-SQL analytics agent, execution-verified</div>

      <section>
        <h2>Pipeline stages</h2>
        <div style={{ fontSize: 11.5, color: "#7d868f", marginBottom: 6 }}>
          The exact ablation matrix from the eval — toggle a stage and re-ask to watch behavior change.
        </div>
        {STAGE_META.map((s) => (
          <label className="toggle" key={s.key}>
            <input
              type="checkbox"
              checked={pipeline[s.key]}
              onChange={(e) => setPipeline({ ...pipeline, [s.key]: e.target.checked })}
            />
            <span className="lbl">
              {s.label}
              <span className="hint">{s.hint}</span>
            </span>
          </label>
        ))}
      </section>

      <section>
        <h2>Model</h2>
        {config && (
          <div style={{ marginBottom: 8 }}>
            {config.server_key_present ? (
              <span className="pill ok">shared key active · {config.rate_limit_per_min}/min</span>
            ) : (
              <span className="pill warn">no shared key — bring your own</span>
            )}
          </div>
        )}
        <div className="field">
          <label>Provider (leave blank = server default)</label>
          <select
            value={llm.provider}
            onChange={(e) => setLlm({ ...llm, provider: e.target.value as LlmSettings["provider"] })}
          >
            <option value="">server default</option>
            <option value="gemini">Gemini (free tier)</option>
            <option value="groq">Groq (free tier)</option>
            <option value="anthropic">Anthropic</option>
            <option value="openai">OpenAI</option>
          </select>
        </div>
        <div className="field">
          <label>Your API key (optional, stored in this browser only)</label>
          <input
            type="password"
            placeholder="paste to use your own credits"
            value={llm.key}
            onChange={(e) => setLlm({ ...llm, key: e.target.value })}
          />
        </div>
        <div className="field">
          <label>Model override (optional)</label>
          <input
            placeholder={
              (llm.provider && config?.default_models[llm.provider]) ||
              "e.g. gemini-2.0-flash"
            }
            value={llm.model}
            onChange={(e) => setLlm({ ...llm, model: e.target.value })}
          />
        </div>
      </section>

      <section>
        <h2>Safety (enforced as code)</h2>
        <div style={{ fontSize: 12, color: "#9aa4ae", lineHeight: 1.5 }}>
          Execution connection is opened <code style={{ color: "#cdd6df" }}>read_only=True</code> at
          the DuckDB storage engine. Every query is parsed to an AST and rejected before a connection
          opens if it isn't SELECT/WITH, touches a table outside{" "}
          {config ? config.allowed_schemas.join(", ") : "the modeled schema"}, or references a
          PII-denylisted column{config ? ` (${config.pii_denylist.join(", ")})` : ""}. A{" "}
          {config?.max_rows ?? 5000}-row LIMIT and a {config?.statement_timeout_seconds ?? 15}s
          timeout are forced.
        </div>
      </section>

      <section>
        <h2>Audit log</h2>
        <button className="mini-btn" onClick={() => setAuditOpen((v) => !v)}>
          {auditOpen ? "hide" : "show recent statements"}
        </button>
        {auditOpen && (
          <div style={{ marginTop: 10 }}>
            {audit.length === 0 && (
              <div style={{ fontSize: 11.5, color: "#7d868f" }}>
                nothing logged yet on this instance (the log is ephemeral in serverless).
              </div>
            )}
            {audit.map((r, i) => (
              <div className="audit-row" key={i}>
                <b>{r.stage}</b>{" "}
                <span className={`oc-${r.outcome}`}>{r.outcome}</span>
                {r.row_count != null ? ` · ${r.row_count} rows` : ""}
                {r.latency_ms != null ? ` · ${Math.round(r.latency_ms)}ms` : ""}
                <br />
                {(r.question || "").slice(0, 70)}
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2>About</h2>
        <div style={{ fontSize: 11.5, color: "#7d868f", lineHeight: 1.55 }}>
          Warehouse: a synthetic e-commerce star schema (~120k orders, 20k customers) built the same
          way the dbt project builds it. The local Qwen-7B model and MiniLM embeddings from the
          original are swapped for a hosted model and BM25 retrieval so it fits a serverless runtime;
          every pipeline stage and safety guard is otherwise unchanged.
        </div>
      </section>
    </aside>
  );
}
