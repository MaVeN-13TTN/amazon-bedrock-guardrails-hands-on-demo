"use client";

import { StageEntry, StageNotRun } from "./StageEntry";
import type { Exchange } from "@/lib/session";
import type { AppContext, Stage } from "@/lib/types";

const ALL_STAGES: Stage[] = ["screen", "answer", "verify"];

interface Props {
  exchanges: Exchange[];
  selected: Exchange | null;
  ctx: AppContext | null;
  onSelect: (id: string) => void;
}

/**
 * What the policy engine did for the request the member just sent.
 *
 * Everything here comes from the same response object the Chat_Window rendered.
 * Nothing in this component fetches, so the two views cannot disagree because a
 * second evaluation classified the prompt differently.
 */
export function BackgroundView({ exchanges, selected, ctx, onSelect }: Props) {
  const completed = exchanges.filter((x) => x.status !== "pending");

  if (completed.length === 0) {
    return (
      <section className="rounded-xl border border-line bg-white px-4 py-4">
        <h2 className="pb-1 text-stage font-semibold text-ink">What the system did</h2>
        <p className="text-finding text-dim">
          No request has been sent yet. Ask a question in the chat window — the Send button, or any
          example prompt — and the three pipeline stages will appear here.
        </p>
      </section>
    );
  }

  return (
    <section className="space-y-3">
      <header className="rounded-xl border border-line bg-white px-4 py-2">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3">
          <h2 className="text-stage font-semibold text-ink">What the system did</h2>
          {ctx ? (
            <p className="font-mono text-finding text-dim">
              guardrail {ctx.guardrail_id ?? "(none)"} v{ctx.guardrail_version ?? "—"} ·{" "}
              {ctx.region} · {ctx.model}
            </p>
          ) : null}
        </div>

        {completed.length > 1 ? (
          <div className="flex flex-wrap gap-1.5 pt-2">
            <span className="text-finding font-semibold text-dim">Request:</span>
            {completed.map((exchange) => (
              <button
                key={exchange.id}
                type="button"
                onClick={() => onSelect(exchange.id)}
                className={`max-w-[280px] truncate rounded-full border px-2.5 py-1 text-finding ${
                  exchange.id === selected?.id
                    ? "border-info bg-blue-50 text-info"
                    : "border-line bg-[#fcfdfc] text-dim hover:border-info"
                }`}
              >
                {exchange.memberText}
              </button>
            ))}
          </div>
        ) : null}
      </header>

      {selected ? <Detail exchange={selected} /> : null}
    </section>
  );
}

function Detail({ exchange }: { exchange: Exchange }) {
  const response = exchange.response;

  return (
    <>
      <div className="rounded-xl border border-line bg-white px-4 py-2">
        <p className="text-finding font-semibold text-dim">The member asked</p>
        <p className="whitespace-pre-wrap break-words text-turn text-ink">
          {exchange.memberText}
        </p>
        {response ? (
          <p className="font-mono text-finding text-dim">
            {response.stages.length} stage{response.stages.length === 1 ? "" : "s"} ·{" "}
            {response.total_latency_ms}ms total ·{" "}
            {response.stages.filter((s) => s.model_invoked).length} model call
            {response.stages.filter((s) => s.model_invoked).length === 1 ? "" : "s"} ·{" "}
            {response.stopped_at ? `stopped at ${response.stopped_at}` : "stopped_at null"}
          </p>
        ) : null}
      </div>

      {exchange.status === "failed" ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3">
          <p className="text-finding font-bold text-stop">The request failed</p>
          <p className="pt-1 font-mono text-finding text-stop">{exchange.error}</p>
        </div>
      ) : null}

      {response ? (
        <div className="grid gap-3 lg:grid-cols-3">
          {response.stages.map((stageResult) => (
            <StageEntry key={stageResult.stage} result={stageResult} />
          ))}
          {ALL_STAGES.filter(
            (name) => !response.stages.some((s) => s.stage === name),
          ).map((name) => (
            <StageNotRun key={name} stage={name} haltedAt={response.stopped_at} />
          ))}
        </div>
      ) : null}
    </>
  );
}
