"use client";

import { useState } from "react";
import type { AskResponse, LlmSettings, PipelineConfig, VerifyResponse } from "@/lib/types";
import { verify as verifyApi } from "@/lib/api";
import MiniChart, { fmt } from "./MiniChart";

function ResultTable({ columns, rows }: { columns: string[]; rows: any[][] }) {
  const shown = rows.slice(0, 50);
  return (
    <table className="result">
      <thead>
        <tr>{columns.map((c, i) => <th key={i}>{c}</th>)}</tr>
      </thead>
      <tbody>
        {shown.map((r, i) => (
          <tr key={i}>
            {r.map((v, j) => (
              <td key={j}>{v === null ? "—" : typeof v === "number" ? fmt(v) : String(v)}</td>
            ))}
          </tr>
        ))}
      </tbody>
      {rows.length > shown.length && (
        <tfoot>
          <tr>
            <td colSpan={columns.length} style={{ color: "#5b636e" }}>
              …{rows.length - shown.length} more rows
            </td>
          </tr>
        </tfoot>
      )}
    </table>
  );
}

export default function AnswerCard({
  resp,
  pipeline,
  llm,
}: {
  resp: AskResponse;
  pipeline: PipelineConfig;
  llm: LlmSettings;
}) {
  const [verifying, setVerifying] = useState(false);
  const [verifyRes, setVerifyRes] = useState<VerifyResponse | null>(null);
  const [verifyErr, setVerifyErr] = useState<string | null>(null);

  if (resp.status === "clarification_needed") {
    return (
      <div className="card">
        <div className="notice clarify">
          <strong>This question is ambiguous.</strong> {resp.ambiguity?.reason}
        </div>
        <p style={{ marginBottom: 0 }}>{resp.clarifying_question}</p>
        {resp.value_hints && (
          <details className="disclosure">
            <summary>value hints</summary>
            <pre className="trace">{resp.value_hints}</pre>
          </details>
        )}
      </div>
    );
  }

  if (resp.status === "failed") {
    return (
      <div className="card">
        <div className="notice fail">
          Couldn't produce a working query after {resp.attempts.length} attempt(s).
        </div>
        {resp.attempts.map((a, i) => (
          <div className="attempt-line" key={i}>
            <span className="st">
              #{a.attempt_number} [{a.stage}/{a.outcome}]
            </span>{" "}
            {a.error}
          </div>
        ))}
        {resp.sql && <pre className="sql">{resp.sql}</pre>}
      </div>
    );
  }

  const r = resp.result!;
  const chart = resp.chart;

  return (
    <div className="card">
      {resp.nl_answer && <div className="answer-text">{resp.nl_answer}</div>}

      {chart?.kind === "single_value" && r.rows.length === 1 && (
        <div className="big-value">
          {typeof r.rows[0][0] === "number" ? fmt(r.rows[0][0] as number) : String(r.rows[0][0])}
          <span className="unit">{r.columns[0]}</span>
        </div>
      )}

      {chart && (chart.kind === "bar" || chart.kind === "line") && <MiniChart chart={chart} />}

      {(chart?.kind === "table_only" || (!chart && r.rows.length > 0)) && (
        <ResultTable columns={r.columns} rows={r.rows} />
      )}

      <div className="metrics">
        <div className="metric">
          <div className="k">Rows</div>
          <div className="v">{r.row_count}</div>
        </div>
        <div className="metric">
          <div className="k">Query</div>
          <div className="v">{Math.round(r.latency_ms)} ms</div>
        </div>
        <div className="metric">
          <div className="k">End to end</div>
          <div className="v">{(resp.total_latency_ms / 1000).toFixed(1)} s</div>
        </div>
        <div className="metric">
          <div className="k">LLM calls</div>
          <div className="v">{resp.llm_calls}</div>
        </div>
        <div className="metric">
          <div className="k">Attempts</div>
          <div className="v">{resp.cache_hit ? "cache" : resp.attempts.length}</div>
        </div>
      </div>

      {resp.sanity_findings.map((f, i) => (
        <div className={`finding ${f.severity}`} key={i}>
          <code>{f.code}</code> — {f.message}
        </div>
      ))}

      <details className="disclosure">
        <summary>SQL that ran{resp.cache_hit ? " (cache hit)" : ""} · plan · trace</summary>
        <pre className="sql">{resp.sql}</pre>
        {resp.plan_text && (
          <>
            <div style={{ fontSize: 12, color: "#5b636e", marginTop: 6 }}>Plan</div>
            <pre className="trace">{resp.plan_text}</pre>
          </>
        )}
        {resp.value_hints && (
          <>
            <div style={{ fontSize: 12, color: "#5b636e", marginTop: 6 }}>Value hints</div>
            <pre className="trace">{resp.value_hints}</pre>
          </>
        )}
        {resp.attempts.length > 1 && (
          <>
            <div style={{ fontSize: 12, color: "#5b636e", marginTop: 6 }}>Attempts</div>
            {resp.attempts.map((a, i) => (
              <div className="attempt-line" key={i}>
                <span className="st">
                  #{a.attempt_number} [{a.stage}/{a.outcome}]
                </span>{" "}
                {a.error || "ok"}
              </div>
            ))}
          </>
        )}
        {resp.schema_context && (
          <>
            <div style={{ fontSize: 12, color: "#5b636e", marginTop: 6 }}>
              Retrieved schema (what the model saw)
            </div>
            <pre className="trace">{resp.schema_context}</pre>
          </>
        )}
      </details>

      <button
        className="verify-btn"
        disabled={verifying}
        onClick={async () => {
          setVerifying(true);
          setVerifyErr(null);
          try {
            const v = await verifyApi(resp.question, resp.sql, r.columns, r.rows, pipeline, llm);
            setVerifyRes(v);
          } catch (e: any) {
            setVerifyErr(e.message || "verification failed");
          } finally {
            setVerifying(false);
          }
        }}
      >
        {verifying ? "re-running an independent query…" : "Verify this"}
      </button>

      {verifyErr && <div className="err-banner">{verifyErr}</div>}
      {verifyRes && (
        <div className={`verify-result ${verifyRes.match ? "ok" : "bad"}`}>
          {verifyRes.match ? "✓ " : "✗ "}
          Paraphrased as “{verifyRes.verify_question}” — {verifyRes.detail}
          <details className="disclosure" style={{ borderTop: "none", paddingTop: 4 }}>
            <summary>verification SQL</summary>
            <pre className="sql">{verifyRes.verify_sql}</pre>
          </details>
        </div>
      )}
    </div>
  );
}
