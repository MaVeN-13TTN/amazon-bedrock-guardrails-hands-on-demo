"use client";

import { useState } from "react";
import { HitBadge } from "./HitBadge";
import { Card, JsonPanel } from "./JsonPanel";
import { ApiError, apiBaseUrl, verify } from "@/lib/api";
import { GROUNDING_CASES } from "@/lib/samples";
import type { AppContext, StageResult } from "@/lib/types";

const MAX_CHARS = 2000;

/**
 * An engineer's instrument, not part of the member path. It calls
 * `POST /api/verify` directly with a question and a candidate answer, so the
 * thresholds can be probed without going through a member request. The verify
 * stage of an actual member request appears in the Background_View instead.
 */
export function GroundingTool({ ctx }: { ctx: AppContext | null }) {
  const [question, setQuestion] = useState(GROUNDING_CASES[0].question);
  const [answer, setAnswer] = useState(GROUNDING_CASES[0].answer);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<StageResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function check(q = question, a = answer) {
    if (busy) return;
    if (!q.trim() || !a.trim()) {
      setError("Both a question and a candidate answer are required.");
      return;
    }
    if (q.length > MAX_CHARS || a.length > MAX_CHARS) {
      setError(`Each field takes at most ${MAX_CHARS} characters.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setResult(await verify(q, a));
    } catch (e) {
      // The previous result is deliberately retained: losing it on a transient
      // failure would cost the presenter the comparison they were making.
      setError(`${apiBaseUrl}/api/verify — ${e instanceof ApiError ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  const grounding = result?.hits.find((h) => h.policy === "grounding");
  const relevance = result?.hits.find((h) => h.policy === "relevance");

  return (
    <>
      <Card title="Reference document — Extension Bulletin 14">
        <div className="px-4 py-3.5">
          <pre className="whitespace-pre-wrap rounded-lg border border-dashed border-line bg-[#fafbfa] px-3.5 py-3 font-mono text-finding leading-relaxed text-ink">
            {ctx?.bulletin ?? "loading…"}
          </pre>
          {ctx ? (
            <p className="pt-2 font-mono text-finding text-dim">
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
              <label htmlFor="gq" className="mb-1.5 block text-finding font-bold text-dim">
                Question asked <span className="font-mono normal-case">(query)</span>
              </label>
              <input
                id="gq"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                maxLength={MAX_CHARS}
                className="w-full rounded-lg border border-line bg-[#fcfdfc] px-3.5 py-2.5 text-finding outline-none focus:border-transparent focus:ring-2 focus:ring-info"
              />
            </div>
            <div>
              <label htmlFor="ga" className="mb-1.5 block text-finding font-bold text-dim">
                Answer under test <span className="font-mono normal-case">(guard_content)</span>
              </label>
              <textarea
                id="ga"
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                maxLength={MAX_CHARS}
                rows={3}
                className="w-full rounded-lg border border-line bg-[#fcfdfc] px-3.5 py-2.5 text-finding outline-none focus:border-transparent focus:ring-2 focus:ring-info"
              />
            </div>
          </div>

          <div className="space-y-1.5 pt-3">
            {GROUNDING_CASES.map((c) => (
              <div key={c.label} className="flex flex-wrap items-baseline gap-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setQuestion(c.question);
                    setAnswer(c.answer);
                    check(c.question, c.answer);
                  }}
                  className="rounded-full border border-line bg-[#fcfdfc] px-2.5 py-1 text-finding hover:border-info hover:text-info disabled:opacity-50"
                >
                  {c.label}
                </button>
                {/* Visible text, not a title attribute: an expectation nobody can
                    read is not an expectation. */}
                <span className="text-finding text-dim">expect: {c.expect}</span>
              </div>
            ))}
          </div>

          <button
            type="button"
            onClick={() => check()}
            disabled={busy}
            className="mt-3.5 rounded-lg bg-info px-5 py-2.5 text-finding font-semibold text-white disabled:opacity-50"
          >
            {busy ? "Checking…" : "Check grounding & relevance"}
          </button>
        </div>
      </Card>

      <Card title="Verdict">
        <div className="space-y-2 px-4 py-3.5">
          {error ? <p className="font-mono text-finding text-stop">{error}</p> : null}

          {result ? (
            <>
              <p
                className={`text-stage font-bold ${result.intervened ? "text-stop" : "text-go"}`}
              >
                {result.intervened ? "Blocked — a check failed" : "Passed both checks"}
              </p>

              {/* Two independent checks, reported independently. The instructive
                  case is an answer that is grounded and still fails relevance. */}
              <div className="grid gap-2 sm:grid-cols-2">
                <ScoreLine
                  name="Grounding"
                  score={grounding?.score ?? null}
                  threshold={grounding?.threshold ?? ctx?.grounding_threshold ?? null}
                  passed={grounding?.passed ?? null}
                />
                <ScoreLine
                  name="Relevance"
                  score={relevance?.score ?? null}
                  threshold={relevance?.threshold ?? ctx?.relevance_threshold ?? null}
                  passed={relevance?.passed ?? null}
                />
              </div>

              {result.hits.map((h, i) => (
                <HitBadge key={i} hit={h} />
              ))}
            </>
          ) : (
            !error && <p className="text-finding text-dim">Nothing checked yet.</p>
          )}
        </div>
      </Card>

      <Card title="Raw assessment">
        <JsonPanel value={result?.raw} label="grounding raw assessment" />
      </Card>
    </>
  );
}

function ScoreLine({
  name,
  score,
  threshold,
  passed,
}: {
  name: string;
  score: number | string | null;
  threshold: number | null;
  passed: boolean | null;
}) {
  return (
    <div className="rounded-lg border border-line bg-[#fcfdfc] px-3 py-2">
      <p className="text-finding font-semibold text-ink">{name}</p>
      <p className="font-mono text-finding text-dim">
        score {score ?? "—"} · threshold {threshold ?? "—"}
      </p>
      <p
        className={`text-finding font-bold ${
          passed === null ? "text-dim" : passed ? "text-go" : "text-stop"
        }`}
      >
        {passed === null ? "not reported" : passed ? "passed" : "failed"}
      </p>
    </div>
  );
}
