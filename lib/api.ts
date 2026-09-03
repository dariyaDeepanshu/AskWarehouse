import type {
  AskResponse,
  LlmSettings,
  PipelineConfig,
  ServerConfig,
  VerifyResponse,
} from "./types";

function llmHeaders(llm: LlmSettings): Record<string, string> {
  const h: Record<string, string> = { "content-type": "application/json" };
  if (llm.key.trim()) {
    h["x-llm-key"] = llm.key.trim();
    if (llm.provider) h["x-llm-provider"] = llm.provider;
    if (llm.model.trim()) h["x-llm-model"] = llm.model.trim();
  }
  return h;
}

async function parse<T>(res: Response): Promise<T> {
  const text = await res.text();
  let body: any = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    /* non-JSON error page */
  }
  if (!res.ok) {
    const detail = body?.detail || body?.error || text || `HTTP ${res.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body as T;
}

export async function ask(
  question: string,
  pipeline: PipelineConfig,
  llm: LlmSettings,
  sessionId: string,
): Promise<AskResponse> {
  const res = await fetch("/api/ask", {
    method: "POST",
    headers: llmHeaders(llm),
    body: JSON.stringify({ question, pipeline, session_id: sessionId }),
  });
  return parse<AskResponse>(res);
}

export async function verify(
  question: string,
  sql: string,
  columns: string[],
  rows: any[][],
  pipeline: PipelineConfig,
  llm: LlmSettings,
): Promise<VerifyResponse> {
  const res = await fetch("/api/verify", {
    method: "POST",
    headers: llmHeaders(llm),
    body: JSON.stringify({ question, sql, columns, rows, pipeline }),
  });
  return parse<VerifyResponse>(res);
}

export async function getConfig(): Promise<ServerConfig> {
  return parse<ServerConfig>(await fetch("/api/config"));
}

export async function getExamples(): Promise<string[]> {
  const body = await parse<{ examples: string[] }>(await fetch("/api/examples"));
  return body.examples;
}

export async function getAudit(limit = 20): Promise<Record<string, any>[]> {
  const body = await parse<{ rows: Record<string, any>[] }>(
    await fetch(`/api/audit?limit=${limit}`),
  );
  return body.rows;
}
