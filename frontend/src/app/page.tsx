"use client";

import { useEffect, useState } from "react";
import { GroundingLane } from "@/components/GroundingLane";
import { PipelineLane } from "@/components/PipelineLane";
import { apiBaseUrl, getContext } from "@/lib/api";
import type { AppContext } from "@/lib/types";

type Tab = "pipeline" | "grounding";

export default function Home() {
  const [tab, setTab] = useState<Tab>("pipeline");
  const [ctx, setCtx] = useState<AppContext | null>(null);
  const [ctxError, setCtxError] = useState<string | null>(null);

  useEffect(() => {
    getContext()
      .then(setCtx)
      .catch((e) => setCtxError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <>
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-line bg-white px-6 py-3">
        <div>
          <h1 className="text-base font-semibold">
            {ctx?.assistant ?? "Kilimo Desk"}{" "}
            <span className="font-normal text-dim">
              · {ctx ? `${ctx.org}, ${ctx.county}` : "member support"}
            </span>
          </h1>
        </div>
        <div className="text-right font-mono text-[11.5px] leading-relaxed text-dim">
          {ctxError ? (
            <span className="text-stop">{ctxError}</span>
          ) : ctx ? (
            <>
              {ctx.region} · {ctx.model}
              <br />
              {ctx.guardrail_active ? (
                <>
                  guardrail {ctx.guardrail_id} v{ctx.guardrail_version}
                </>
              ) : (
                <span className="font-bold text-stop">no guardrail configured</span>
              )}
            </>
          ) : (
            <>connecting to {apiBaseUrl}…</>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-[1360px] px-6 pb-12 pt-4">
        <div className="mb-4 flex gap-1.5 border-b border-line">
          {(
            [
              ["pipeline", "Pipeline"],
              ["grounding", "Grounding check"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`-mb-px border-b-2 px-4 py-2.5 font-semibold ${
                tab === key ? "border-info text-ink" : "border-transparent text-dim"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {tab === "pipeline" ? <PipelineLane /> : <GroundingLane ctx={ctx} />}
      </main>
    </>
  );
}
