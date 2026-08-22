import type { AppContext, AskResponse, StageResult } from "./types";

const BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

/** Surfaces the backend's `detail`, which carries the real AWS error. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    /** Which pipeline stage failed, when the backend attributed it to one. */
    readonly stage?: string | null,
    /** `aws_error`, `timeout`, `parameter_validation`, or absent. */
    readonly kind?: string | null,
    readonly awsErrorCode?: string | null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(`Cannot reach the API at ${BASE}. Is the backend running?`, 0);
  }

  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    let stage: string | null = null;
    let kind: string | null = null;
    let awsErrorCode: string | null = null;
    try {
      const body = await res.json();
      const raw = body?.detail;
      if (typeof raw === "string") {
        // Configuration errors stay readable prose, e.g. "No guardrail configured".
        detail = raw;
      } else if (Array.isArray(raw)) {
        // FastAPI validation errors.
        detail = raw.map((d: { msg: string }) => d.msg).join("; ");
      } else if (raw && typeof raw === "object") {
        // A stage failure: the backend names the stage so the Background_View
        // does not have to parse a sentence to find it.
        detail = typeof raw.detail === "string" ? raw.detail : JSON.stringify(raw);
        stage = raw.stage ?? null;
        kind = raw.kind ?? null;
        awsErrorCode = raw.aws_error_code ?? null;
      }
    } catch {
      /* keep the status line */
    }
    throw new ApiError(detail, res.status, stage, kind, awsErrorCode);
  }
  return res.json() as Promise<T>;
}

export const getContext = () => request<AppContext>("/api/context");

export const ask = (input: string) =>
  request<AskResponse>("/api/ask", { method: "POST", body: JSON.stringify({ input }) });

export const verify = (question: string, answer: string) =>
  request<StageResult>("/api/verify", {
    method: "POST",
    body: JSON.stringify({ question, answer }),
  });

export const apiBaseUrl = BASE;
