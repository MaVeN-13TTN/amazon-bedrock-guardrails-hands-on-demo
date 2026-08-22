import type { AppContext, AskResponse, StageResult } from "@/lib/types";

/** A stage result with sensible defaults; override what the test is about. */
export function stage(overrides: Partial<StageResult> & { stage: StageResult["stage"] }): StageResult {
  return {
    intervened: false,
    hits: [],
    text: null,
    reason: null,
    stop_reason: null,
    model_invoked: overrides.stage === "answer",
    latency_ms: 120,
    raw: { assessments: [] },
    replayed: null,
    ...overrides,
  };
}

export const ANSWERED: AskResponse = {
  stages: [stage({ stage: "screen" }), stage({ stage: "answer" }), stage({ stage: "verify" })],
  final: "The Kangema and Kiriaini collection points open from 06:00 to 10:00 on Tuesdays and Fridays.",
  stopped_at: null,
  total_latency_ms: 360,
};

/** Blocked at screen: the member reads a refusal, and no model was invoked. */
export const REFUSED: AskResponse = {
  stages: [
    stage({
      stage: "screen",
      intervened: true,
      hits: [
        {
          policy: "denied topic",
          detail: "Agrochemical Dosing",
          action: "BLOCKED",
          where: "input",
          score: null,
          threshold: null,
          passed: null,
        },
      ],
    }),
  ],
  final:
    "I can't help with that one. For anything involving chemical doses, land matters, or credit decisions, please speak to the co-operative office or a licensed agrovet.",
  stopped_at: "screen",
  total_latency_ms: 120,
};

/** Masked, not blocked: the member sees nothing unusual. The largest gap. */
export const MASKED: AskResponse = {
  stages: [
    stage({
      stage: "screen",
      text: "I am {NAME}, member {UUID}, my number is {PHONE}. Has my payment gone out?",
      hits: [
        {
          policy: "PII",
          detail: "NAME",
          action: "ANONYMIZED",
          where: "input",
          score: null,
          threshold: null,
          passed: null,
        },
        {
          policy: "PII",
          detail: "PHONE",
          action: "ANONYMIZED",
          where: "input",
          score: null,
          threshold: null,
          passed: null,
        },
        {
          policy: "PII regex",
          detail: "Co-op Member Number",
          action: "ANONYMIZED",
          where: "input",
          score: null,
          threshold: null,
          passed: null,
        },
      ],
    }),
    stage({ stage: "answer" }),
    stage({ stage: "verify" }),
  ],
  final: "Payment is released fourteen days after grading is complete.",
  stopped_at: null,
  total_latency_ms: 400,
};

/** Grounding failed: the fallback reaches the member, not an invention. */
export const UNGROUNDED: AskResponse = {
  stages: [
    stage({ stage: "screen" }),
    stage({ stage: "answer" }),
    stage({
      stage: "verify",
      intervened: true,
      hits: [
        {
          policy: "grounding",
          detail: "score 0.31 vs threshold 0.7",
          action: "BLOCKED",
          where: "output",
          score: 0.31,
          threshold: 0.7,
          passed: false,
        },
      ],
    }),
  ],
  final:
    "I started to answer that but the response didn't meet our member-safety rules. Please contact the co-operative office.",
  stopped_at: "verify",
  total_latency_ms: 500,
};

export const CONTEXT: AppContext = {
  org: "Highland Growers Co-operative",
  assistant: "Kilimo Desk",
  county: "Murang'a County",
  region: "eu-west-1",
  model: "global.anthropic.claude-haiku-4-5-20251001-v1:0",
  guardrail_id: "abcd1234efgh",
  guardrail_version: "DRAFT",
  guardrail_active: true,
  bulletin:
    "Collection points at Kangema and Kiriaini open from 06:00 to 10:00 on Tuesdays and Fridays only. Members must present a valid member number at the gate.\n\nPayment for delivered produce is released fourteen days after grading is complete. Grading results are posted at the collection point.\n",
  denied_topics: ["Agrochemical Dosing", "Land Tenure Disputes", "Credit Terms"],
  blocked_words: ["Project Tumaini", "Batch Ledger v2"],
  grounding_threshold: 0.7,
  relevance_threshold: 0.7,
  bulletin_facts: {
    collection_points: ["Kangema", "Kiriaini"],
    collection_opens: "06:00",
    collection_closes: "10:00",
    collection_days: ["Tuesday", "Friday"],
    gate_requirement: "present a valid member number at the gate",
    payment_delay_days: 14,
    payment_release: "released fourteen days after grading is complete",
    payment_note: "Grading results are posted at the collection point.",
  },
  about_sections: [
    { title: "Who we are", body: "Highland Growers Co-operative is a smallholder farming co-operative in Murang'a County." },
    { title: "What we do for members", body: "We collect and grade produce, pay members for what they deliver." },
  ],
};

/** Every string a response carries that must never reach the member's eye. */
export function policyVocabulary(response: AskResponse): string[] {
  const words: string[] = [];
  for (const s of response.stages) {
    words.push(s.stage, String(s.model_invoked), String(s.latency_ms));
    for (const h of s.hits) {
      if (h.policy) words.push(h.policy);
      if (h.detail) words.push(h.detail);
      if (h.action) words.push(h.action);
      if (h.score !== null) words.push(String(h.score));
      if (h.threshold !== null) words.push(String(h.threshold));
    }
  }
  if (response.stopped_at) words.push(response.stopped_at);
  words.push(String(response.total_latency_ms));
  return words;
}
