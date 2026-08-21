"use client";

import { useState } from "react";
import { Card, JsonPanel } from "./JsonPanel";
import { StageCard } from "./StageCard";
import { ApiError, ask } from "@/lib/api";
import { PROMPT_GROUPS } from "@/lib/samples";
import type { AskResponse, Stage, StageResult } from "@/lib/types";

export function PipelineLane() {
  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<AskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(text: string) {
    const trimmed = text.trim();
    if (!trimmed || running) return;
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      setResult(await ask(trimmed));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  const byStage = new Map<Stage, StageResult>(
    (result?.stages ?? []).map((s) => [s.stage, s]),
  );

  return (
    <>
      <Card title="Ask the assistant">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run(input);
          }}
          className="flex gap-2.5 px-4 py-3.5"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="e.g. When are the collection points open?"
            className="min-w-0 flex-1 rounded-lg border border-line bg-[#fcfdfc] px-3.5 py-2.5 outline-none focus:border-transparent focus:ring-2 focus:ring-info"
          />
          <button
            type="submit"
            disabled={running}
            className="whitespace-nowrap rounded-lg bg-info px-5 py-2.5 font-semibold text-white disabled:opacity-50"
          >
            {running ? "Running…" : "Run pipeline"}
          </button>
        </form>

        <div className="space-y-1.5 px-4 pb-4">
          {PROMPT_GROUPS.map((g) => (
            <div key={g.label} className="flex flex-wrap items-baseline gap-1.5">
              <span className="min-w-[122px] font-mono text-[10.5px] font-bold uppercase tracking-wide text-dim">
                {g.label}
              </span>
              {g.prompts.map((p) => (
                <button
                  key={p}
                  type="button"
                  title={p}
                  onClick={() => {
                    setInput(p);
                    run(p);
                  }}
                  className="rounded-full border border-line bg-[#fcfdfc] px-2.5 py-1 text-left text-[12.5px] hover:border-info hover:text-info"
                >
                  {p.length > 64 ? `${p.slice(0, 62)}…` : p}
                </button>
              ))}
            </div>
          ))}
        </div>
      </Card>

      <div className="mb-3.5 grid gap-3 md:grid-cols-3">
        <StageCard stage="screen" result={byStage.get("screen")} running={running} />
        <StageCard stage="answer" result={byStage.get("answer")} running={running} />
        <StageCard stage="verify" result={byStage.get("verify")} running={running} />
      </div>

      <Card title="What the member sees">
        <div className="px-4 py-3.5">
          {error ? (
            <p className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 font-mono text-[12.5px] text-stop">
              {error}
            </p>
          ) : result ? (
            <>
              <p
                className={`whitespace-pre-wrap rounded-lg border px-4 py-3 ${
                  result.stopped_at
                    ? "border-red-200 bg-red-50 text-stop"
                    : "border-green-200 bg-green-50"
                }`}
              >
                {result.final || "(empty)"}
              </p>
              <p className="pt-2 font-mono text-[11px] text-dim">
                {result.stages.length} stage{result.stages.length === 1 ? "" : "s"} ·{" "}
                {result.total_latency_ms}ms total ·{" "}
                {result.stages.filter((s) => s.model_invoked).length} model call
                {result.stages.filter((s) => s.model_invoked).length === 1 ? "" : "s"}
                {result.stopped_at ? ` · stopped at ${result.stopped_at}` : ""}
              </p>
            </>
          ) : (
            <p className="text-[13px] text-dim">Nothing yet.</p>
          )}
        </div>
      </Card>

      <Card title="Raw assessments">
        <JsonPanel
          value={(result?.stages ?? []).map((s) => ({ stage: s.stage, raw: s.raw }))}
        />
      </Card>
    </>
  );
}
