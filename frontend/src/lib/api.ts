import type { AppContext, AskResponse, StageResult } from "./types";

const BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

/** Surfaces the backend's `detail` string, which carries the real AWS error. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
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
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* keep the status line */
    }
    throw new ApiError(detail, res.status);
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
