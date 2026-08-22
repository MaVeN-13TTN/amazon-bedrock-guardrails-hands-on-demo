"use client";

import { useState } from "react";
import { HitBadge } from "./HitBadge";
import { JsonPanel } from "./JsonPanel";
import type { Stage, StageResult } from "@/lib/types";

const META: Record<Stage, { n: number; title: string; api: string }> = {
  screen: { n: 1, title: "Screen", api: "ApplyGuardrail · no model" },
  answer: { n: 2, title: "Answer", api: "Converse + guardrailConfig" },
  verify: { n: 3, title: "Verify", api: "ApplyGuardrail · no model" },
};

/** A stage that ran. Every value is rendered as the response carried it. */
export function StageEntry({ result }: { result: StageResult }) {
  const meta = META[result.stage];
  const inputHits = result.hits.filter((h) => h.where === "input");
  const secondEvaluation = result.stage === "answer" && inputHits.length > 0;

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-white">
      <div
        className={`flex flex-wrap items-baseline justify-between gap-2 border-b border-line px-4 py-2.5 ${
          result.intervened ? "bg-red-50" : "bg-green-50"
        }`}
      >
        <h3 className="text-stage font-bold text-ink">
          {meta.n} · {meta.title}
        </h3>
        {/* The label carries the finding, not the colour: remove colour and
            "Intervened" versus "Passed" still reads. */}
        <span
          className={`text-finding font-bold ${result.intervened ? "text-stop" : "text-go"}`}
        >
          {result.intervened ? "Intervened" : "Passed"}
        </span>
      </div>

      <div className="space-y-2 px-4 py-3">
        <p className="text-stage font-mono text-dim">
          {result.model_invoked ? "Converse · model called" : "ApplyGuardrail · no model"}
        </p>
        <p className="text-finding text-dim">
          {result.latency_ms ?? 0}ms
          {result.stop_reason ? ` · stopReason ${result.stop_reason}` : ""}
        </p>

        {result.replayed ? (
          <p className="rounded-md border border-amber-200 bg-amber-50 px-2 py-1 text-finding font-semibold text-warn">
            {result.stop_reason === "fallback_no_model"
              ? `No model was invoked — bedrock:InvokeModel is unavailable in this account, so this
                 answer is a canned response drawn from Extension Bulletin 14. Stages 1 and 3 ran
                 live against guardrail version ${result.replayed.guardrail_version}.`
              : `Replayed from a recorded fixture — captured ${result.replayed.captured_utc} in
                 ${result.replayed.region}, tier ${result.replayed.tier}, guardrail version
                 ${result.replayed.guardrail_version}`}
          </p>
        ) : null}

        {secondEvaluation ? (
          <p className="rounded-md border border-line bg-[#f5f7f4] px-2 py-1 text-finding text-dim">
            These input findings are a second evaluation of the same submitted text — stage 1
            screened it already. In production you would pick one.
          </p>
        ) : null}

        {result.hits.length ? (
          <div className="space-y-1.5">
            {result.hits.map((hit, i) => (
              <HitBadge key={i} hit={hit} />
            ))}
          </div>
        ) : (
          <p className="text-finding text-dim">No policy fired.</p>
        )}

        {result.stage === "screen" && result.text && !result.intervened ? (
          <ForwardedText text={result.text} />
        ) : null}

        <RawPanel raw={result.raw} stage={result.stage} />
      </div>
    </div>
  );
}

/** The text the model actually received, after any masking. */
function ForwardedText({ text }: { text: string }) {
  const LIMIT = 400;
  const truncated = text.length > LIMIT;
  return (
    <div className="rounded-md border border-dashed border-line bg-[#fafbfa] px-2.5 py-2">
      <p className="pb-0.5 text-finding font-semibold text-dim">Text forwarded to the model</p>
      <p className="whitespace-pre-wrap break-words font-mono text-finding text-ink">
        {truncated ? `${text.slice(0, LIMIT)}` : text}
        {truncated ? <span className="text-dim"> … (truncated for display)</span> : null}
      </p>
    </div>
  );
}

function RawPanel({ raw, stage }: { raw: Record<string, unknown> | null; stage: Stage }) {
  const [open, setOpen] = useState(false);
  const [large, setLarge] = useState(false);

  return (
    <div className="pt-1">
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="rounded-md border border-line px-2 py-1 text-finding text-dim hover:border-info hover:text-info"
        >
          {open ? "Hide" : "Show"} raw assessment
        </button>
        {open ? (
          <button
            type="button"
            onClick={() => setLarge((v) => !v)}
            className="rounded-md border border-line px-2 py-1 text-finding text-dim hover:border-info hover:text-info"
          >
            {large ? "Normal size" : "Enlarge for the room"}
          </button>
        ) : null}
      </div>
      {open ? (
        <div className="pt-2">
          <JsonPanel value={raw} large={large} label={`${stage} raw assessment`} />
        </div>
      ) : null}
    </div>
  );
}

/** A pipeline stage that never ran, because an earlier stage halted the request. */
export function StageNotRun({ stage, haltedAt }: { stage: Stage; haltedAt: Stage | null }) {
  const meta = META[stage];
  return (
    <div className="overflow-hidden rounded-xl border border-dashed border-line bg-[#fafbfa]">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line px-4 py-2.5">
        <h3 className="text-stage font-bold text-dim">
          {meta.n} · {meta.title}
        </h3>
        <span className="text-finding font-bold text-dim">Not run</span>
      </div>
      <div className="px-4 py-3">
        <p className="text-finding text-dim">
          {haltedAt
            ? `The ${haltedAt} stage halted the request, so this stage never ran — and cost nothing.`
            : "This stage did not run."}
        </p>
      </div>
    </div>
  );
}
