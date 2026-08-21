"use client";

import { useState } from "react";
import { HitBadge } from "./HitBadge";
import { Card, JsonPanel } from "./JsonPanel";
import { ApiError, verify } from "@/lib/api";
import { GROUNDING_CASES } from "@/lib/samples";
import type { AppContext, StageResult } from "@/lib/types";

export function GroundingLane({ ctx }: { ctx: AppContext | null }) {
  const [question, setQuestion] = useState(GROUNDING_CASES[0].question);
  const [answer, setAnswer] = useState(GROUNDING_CASES[0].answer);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<StageResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function check(q = question, a = answer) {
    if (!q.trim() || !a.trim() || busy) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await verify(q, a));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Card title="Reference document — Extension Bulletin 14">
        <div className="px-4 py-3.5">
          <pre className="whitespace-pre-wrap rounded-lg border border-dashed border-line bg-[#fafbfa] px-3.5 py-3 font-mono text-[12px] leading-relaxed text-dim">
            {ctx?.bulletin ?? "loading…"}
          </pre>
          {ctx ? (
            <p className="pt-2 font-mono text-[11px] text-dim">
              thresholds — grounding ≥ {ctx.grounding_threshold} · relevance ≥{" "}
              {ctx.relevance_threshold}
            </p>
          ) : null}
        </div>
      </Card>

      <Card title="Judge an answer against the bulletin">
        <div className="px-4 py-3.5">
          <div className="grid gap-3.5 md:grid-cols-2">
            <div>
              <label htmlFor="gq" className="mb-1.5 block text-[11.5px] font-bold uppercase tracking-wider text-dim">
                Question asked <span className="font-mono normal-case">(query)</span>
              </label>
              <input
                id="gq"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                className="w-full rounded-lg border border-line bg-[#fcfdfc] px-3.5 py-2.5 outline-none focus:border-transparent focus:ring-2 focus:ring-info"
              />
            </div>
            <div>
              <label htmlFor="ga" className="mb-1.5 block text-[11.5px] font-bold uppercase tracking-wider text-dim">
                Answer under test <span className="font-mono normal-case">(guard_content)</span>
              </label>
              <textarea
                id="ga"
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                rows={3}
                className="w-full rounded-lg border border-line bg-[#fcfdfc] px-3.5 py-2.5 outline-none focus:border-transparent focus:ring-2 focus:ring-info"
              />
            </div>
          </div>

          <div className="flex flex-wrap gap-1.5 pt-3">
            {GROUNDING_CASES.map((c) => (
              <button
                key={c.label}
                type="button"
                title={`expect: ${c.expect}`}
                onClick={() => {
                  setQuestion(c.question);
                  setAnswer(c.answer);
                  check(c.question, c.answer);
                }}
                className="rounded-full border border-line bg-[#fcfdfc] px-2.5 py-1 text-[12.5px] hover:border-info hover:text-info"
              >
                {c.label}
              </button>
            ))}
          </div>

          <button
            type="button"
            onClick={() => check()}
            disabled={busy}
            className="mt-3.5 rounded-lg bg-info px-5 py-2.5 font-semibold text-white disabled:opacity-50"
          >
            {busy ? "Checking…" : "Check grounding & relevance"}
          </button>
        </div>
      </Card>

      <Card title="Verdict">
        <div className="space-y-1.5 px-4 py-3.5">
          {error ? (
            <p className="font-mono text-[12.5px] text-stop">{error}</p>
          ) : result ? (
            <>
              <p className={`text-[13px] font-bold ${result.intervened ? "text-stop" : "text-go"}`}>
                {result.intervened ? "Blocked — the answer failed a check" : "Passed both checks"}
              </p>
              {result.hits.map((h, i) => (
                <HitBadge key={i} hit={h} />
              ))}
            </>
          ) : (
            <p className="text-[13px] text-dim">Nothing checked yet.</p>
          )}
        </div>
      </Card>

      <Card title="Raw assessment">
        <JsonPanel value={result?.raw} />
      </Card>
    </>
  );
}
