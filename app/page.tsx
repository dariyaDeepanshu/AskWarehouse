"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Sidebar from "@/components/Sidebar";
import AnswerCard from "@/components/AnswerCard";
import { ask, getConfig, getExamples } from "@/lib/api";
import {
  DEFAULT_PIPELINE,
  type AskResponse,
  type LlmSettings,
  type PipelineConfig,
  type ServerConfig,
} from "@/lib/types";

type Turn = { question: string; resp?: AskResponse; error?: string };

const LS_LLM = "askwarehouse.llm.v1";
const LS_PIPE = "askwarehouse.pipeline.v1";

function loadLs<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? { ...fallback, ...JSON.parse(raw) } : fallback;
  } catch {
    return fallback;
  }
}

export default function Page() {
  const [pipeline, setPipeline] = useState<PipelineConfig>(DEFAULT_PIPELINE);
  const [llm, setLlm] = useState<LlmSettings>({ provider: "", key: "", model: "" });
  const [config, setConfig] = useState<ServerConfig | null>(null);
  const [examples, setExamples] = useState<string[]>([]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const sessionId = useRef<string>(
    typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : String(Math.random()),
  );
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setPipeline(loadLs(LS_PIPE, DEFAULT_PIPELINE));
    setLlm(loadLs(LS_LLM, { provider: "", key: "", model: "" }));
    getConfig().then(setConfig).catch(() => {});
    getExamples().then(setExamples).catch(() => {});
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(LS_PIPE, JSON.stringify(pipeline));
    } catch {}
  }, [pipeline]);
  useEffect(() => {
    try {
      window.localStorage.setItem(LS_LLM, JSON.stringify(llm));
    } catch {}
  }, [llm]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, busy]);

  const submit = useCallback(
    async (q: string) => {
      const question = q.trim();
      if (!question || busy) return;
      setDraft("");
      setBusy(true);
      setTurns((t) => [...t, { question }]);
      try {
        const resp = await ask(question, pipeline, llm, sessionId.current);
        setTurns((t) => {
          const copy = [...t];
          copy[copy.length - 1] = { question, resp };
          return copy;
        });
      } catch (e: any) {
        setTurns((t) => {
          const copy = [...t];
          copy[copy.length - 1] = { question, error: e.message || "request failed" };
          return copy;
        });
      } finally {
        setBusy(false);
      }
    },
    [busy, pipeline, llm],
  );

  return (
    <div className="layout">
      <Sidebar
        pipeline={pipeline}
        setPipeline={setPipeline}
        llm={llm}
        setLlm={setLlm}
        config={config}
      />

      <main className="main">
        <div className="main-inner">
          {turns.length === 0 && (
            <div className="intro">
              <h2>Ask a business question about the warehouse</h2>
              <p>
                It checks whether the question is ambiguous, retrieves just the relevant part of the
                schema, plans the join path and grain, writes DuckDB SQL, critiques it, runs it in a
                read-only sandbox, repairs its own errors from the database's feedback, runs sanity
                checks, and returns a chart plus the exact SQL.
              </p>
              <div className="examples">
                {examples.map((ex) => (
                  <button key={ex} className="example-chip" onClick={() => submit(ex)}>
                    {ex}
                  </button>
                ))}
              </div>
            </div>
          )}

          {turns.map((t, i) => (
            <div className="turn" key={i}>
              <div className="q-row">
                <div className="q-bubble">{t.question}</div>
              </div>
              {t.resp && <AnswerCard resp={t.resp} pipeline={pipeline} llm={llm} />}
              {t.error && <div className="err-banner">{t.error}</div>}
              {!t.resp && !t.error && (
                <div className="card">
                  <div className="thinking">
                    <span className="dot" />
                    <span className="dot" style={{ animationDelay: "0.15s" }} />
                    <span className="dot" style={{ animationDelay: "0.3s" }} />
                    <span>
                      running the pipeline — ambiguity → plan → generate → critique → guard → execute
                      → repair
                    </span>
                  </div>
                </div>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        <div className="composer">
          <div className="composer-inner">
            <textarea
              rows={1}
              placeholder="e.g. What's our monthly revenue trend for the last 12 months?"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit(draft);
                }
              }}
            />
            <button className="send-btn" disabled={busy || !draft.trim()} onClick={() => submit(draft)}>
              {busy ? <span className="spinner" /> : "Ask"}
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}
