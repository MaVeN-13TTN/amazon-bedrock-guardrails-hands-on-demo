/** Mirrors backend/app/schemas.py. Keep the two in step. */

export type Stage = "screen" | "answer" | "verify";

export interface PolicyHit {
  policy: string;
  detail: string | null;
  action: string | null;
  where: "input" | "output";
  score: number | string | null;
  threshold: number | null;
  passed: boolean | null;
}

export interface StageResult {
  stage: Stage;
  intervened: boolean;
  hits: PolicyHit[];
  text: string | null;
  reason: string | null;
  stop_reason: string | null;
  model_invoked: boolean;
  latency_ms: number | null;
  raw: Record<string, unknown> | null;
}

export interface AskResponse {
  stages: StageResult[];
  final: string;
  stopped_at: Stage | null;
  total_latency_ms: number;
}

export interface AppContext {
  org: string;
  assistant: string;
  county: string;
  region: string;
  model: string;
  guardrail_id: string | null;
  guardrail_version: string | null;
  guardrail_active: boolean;
  bulletin: string;
  denied_topics: string[];
  blocked_words: string[];
  grounding_threshold: number;
  relevance_threshold: number;
}
