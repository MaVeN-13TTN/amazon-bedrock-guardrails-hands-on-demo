/**
 * Mirrors backend/app/schemas.py. Keep the two in step.
 *
 * `backend/tests/test_contract.py` enforces this: it reads the FastAPI OpenAPI
 * schema and fails naming any field of AskResponse, StageResult, AppContext or
 * PolicyHit that is missing or type-incompatible here. The comment above used to
 * be a request; it is now checkable.
 */

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

/** Provenance of a stage served from a recorded fixture, under Replay_Mode. */
export interface ReplayMeta {
  captured_utc: string;
  region: string;
  tier: string;
  guardrail_version: string;
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
  replayed: ReplayMeta | null;
}

export interface AskResponse {
  stages: StageResult[];
  final: string;
  stopped_at: Stage | null;
  total_latency_ms: number;
}

/** One titled section of Landing_Page prose. */
export interface SectionText {
  title: string;
  body: string;
}

/** Extension Bulletin 14 as discrete facts, for the Landing_Page sections. */
export interface BulletinFacts {
  collection_points: string[];
  collection_opens: string;
  collection_closes: string;
  collection_days: string[];
  gate_requirement: string;
  payment_delay_days: number;
  payment_release: string;
  payment_note: string;
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
  bulletin_facts: BulletinFacts;
  about_sections: SectionText[];
}
