"use client";

import { HitBadge } from "./HitBadge";
import type { StageResult } from "@/lib/types";

const META = {
  screen: { n: 1, title: "Screen", api: "ApplyGuardrail · no model" },
  answer: { n: 2, title: "Answer", api: "Converse + guardrailConfig" },
  verify: { n: 3, title: "Verify", api: "ApplyGuardrail · grounding" },
} as const;

interface Props {
  stage: keyof typeof META;
  result?: StageResult;
  running?: boolean;
}

/**
 * A stage in the pipeline. Dimmed until it runs, so a request rejected at
 * stage 1 visibly leaves stages 2 and 3 untouched.
 */
export function StageCard({ stage, result, running }: Props) {
  const meta = META[stage];
  const state = result ? (result.intervened ? "stop" : "pass") : "idle";

  const head =
    state === "pass"
      ? "bg-green-50 text-go"
      : state === "stop"
        ? "bg-red-50 text-stop"
        : "bg-white text-dim";

  return (
    <div
      className={`overflow-hidden rounded-xl border border-line bg-white transition-opacity ${
        result || running ? "opacity-100" : "opacity-40"
      }`}
    >
      <div className={`flex items-baseline justify-between gap-2 border-b border-line px-4 py-2.5 ${head}`}>
        <h3 className="text-xs font-bold uppercase tracking-wide">
          {meta.n} · {meta.title}
        </h3>
        <span className="font-mono text-[10.5px] opacity-80">{meta.api}</span>
      </div>

      <div className="min-h-[122px] space-y-1.5 px-4 py-3">
        {running && !result ? <p className="text-[13px] text-dim">Running…</p> : null}

        {!running && !result ? (
          <p className="text-[13px] italic text-dim">Not reached — the request stopped earlier.</p>
        ) : null}

        {result ? (
          <>
            <div className="flex items-center justify-between">
              <p className={`text-[13px] font-bold ${result.intervened ? "text-stop" : "text-go"}`}>
                {result.intervened ? "Intervened" : "Passed"}
              </p>
              <span className="font-mono text-[10.5px] text-dim">
                {result.model_invoked ? "model called" : "no model"}
                {result.latency_ms !== null ? ` · ${result.latency_ms}ms` : ""}
              </span>
            </div>

            {result.hits.length ? (
              result.hits.map((h, i) => <HitBadge key={i} hit={h} />)
            ) : (
              <p className="text-[12.5px] text-dim">No policy fired.</p>
            )}

            {result.stage === "screen" && result.text ? (
              <p className="pt-1 font-mono text-[11px] leading-snug text-dim">
                text passed on: {result.text.slice(0, 160)}
              </p>
            ) : null}
          </>
        ) : null}
      </div>
    </div>
  );
}
