"use client";

import { useEffect, useState } from "react";
import { BackgroundView } from "@/components/BackgroundView";
import { ChatWindow } from "@/components/ChatWindow";
import { Disclosure } from "@/components/Disclosure";
import { GroundingTool } from "@/components/GroundingTool";
import { LandingSections } from "@/components/LandingSections";
import { getContext } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { AppContext } from "@/lib/types";

type Panel = "none" | "background" | "grounding";

/**
 * The Landing_Page is the entry route: the first thing a visitor reaches is what a
 * co-operative member would see, not an engineering console.
 *
 * `useSession` is held here, above the panel switch, so opening or closing the
 * Background_View or the Grounding_Tool cannot unmount it and lose the
 * conversation. A presenter can move between views and come back to the member's
 * screen without re-sending the prompt.
 */
export default function Home() {
  const [ctx, setCtx] = useState<AppContext | null>(null);
  const [ctxError, setCtxError] = useState<string | null>(null);
  const [panel, setPanel] = useState<Panel>("none");
  const session = useSession();

  useEffect(() => {
    getContext()
      .then(setCtx)
      .catch((e) => setCtxError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <>
      <Disclosure replaying={session.selected?.replayed ?? null} />

      <header className="border-b border-line bg-white px-6 py-4">
        <h1 className="text-xl font-semibold text-ink">
          {ctx?.org ?? "Highland Growers Co-operative"}
        </h1>
        <p className="text-finding text-dim">
          {ctx ? `${ctx.county} · member support from ${ctx.assistant}` : "Member support"}
        </p>
      </header>

      <main className="mx-auto max-w-[1360px] px-6 pb-12 pt-4">
        <ChatWindow
          exchanges={session.exchanges}
          inFlight={session.inFlight}
          validationError={session.validationError}
          onSubmit={session.submit}
          compact={panel !== "none"}
        />

        <nav className="flex flex-wrap gap-2 py-4">
          <button
            type="button"
            onClick={() => setPanel(panel === "background" ? "none" : "background")}
            className={`rounded-lg border px-4 py-2 text-stage font-semibold ${
              panel === "background"
                ? "border-info bg-blue-50 text-info"
                : "border-line bg-white text-dim hover:border-info hover:text-info"
            }`}
          >
            {panel === "background" ? "Hide" : "Show"} what the system did
          </button>
          <button
            type="button"
            onClick={() => setPanel(panel === "grounding" ? "none" : "grounding")}
            className={`rounded-lg border px-4 py-2 text-stage font-semibold ${
              panel === "grounding"
                ? "border-info bg-blue-50 text-info"
                : "border-line bg-white text-dim hover:border-info hover:text-info"
            }`}
          >
            {panel === "grounding" ? "Hide" : "Open"} grounding check
            <span className="pl-1.5 text-finding font-normal">(engineer tool)</span>
          </button>
        </nav>

        {/* The panel replaces the co-op sections rather than stacking below them,
            so the member view and the background view fit side by side at
            1280×720 without scrolling past either. */}
        {panel === "background" ? (
          <BackgroundView
            exchanges={session.exchanges}
            selected={session.selected}
            ctx={ctx}
            onSelect={session.select}
          />
        ) : panel === "grounding" ? (
          <GroundingTool ctx={ctx} />
        ) : (
          <LandingSections ctx={ctx} ctxError={ctxError} />
        )}
      </main>
    </>
  );
}
