"use client";

import { useEffect, useRef, useState } from "react";
import { MAX_INPUT_CHARS, type Exchange } from "@/lib/session";
import { PROMPT_GROUPS } from "@/lib/samples";

interface Props {
  exchanges: Exchange[];
  inFlight: boolean;
  validationError: string | null;
  onSubmit: (text: string) => void;
  /**
   * True while an engineer-facing panel is open below. The history tightens so
   * the member's turn and the stage findings are visible together at 1280x720,
   * which is what Requirement 6 asks for and what a screen share actually shows.
   */
  compact?: boolean;
}

/**
 * What a co-operative member sees. No policy names, no stage names, no scores, no
 * latencies, no AWS identifiers.
 *
 * The assistant turn is rendered by exactly one expression — `{final}` — with no
 * conditional styling keyed off `stopped_at`. That is what makes a refusal
 * indistinguishable in form from an answer, and a grounding failure
 * indistinguishable from both. A member cannot tell which happened, and not being
 * able to tell is the lesson the Background_View then unpacks.
 */
export function ChatWindow({ exchanges, inFlight, validationError, onSubmit, compact }: Props) {
  const [draft, setDraft] = useState("");
  const [showExamples, setShowExamples] = useState(false);
  const promptCount = PROMPT_GROUPS.reduce((n, g) => n + g.prompts.length, 0);
  const historyRef = useRef<HTMLDivElement>(null);

  // The newest turn is what the member is reading, so keep it in view inside the
  // capped history rather than letting it fall below the fold.
  useEffect(() => {
    const el = historyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [exchanges]);

  function send(text: string) {
    if (inFlight) return;
    onSubmit(text);
    setDraft("");
    setShowExamples(false);
  }

  return (
    <section className="rounded-xl border border-line bg-white">
      <header className="border-b border-line px-4 py-3">
        <h2 className="text-stage font-semibold text-ink">Ask Kilimo Desk</h2>
        {compact ? null : (
          <p className="text-finding text-dim">
            Member support — collection days, payments, and growing guidance.
          </p>
        )}
      </header>

      {/* Capped and scrollable: the conversation grows, but the composer, the
          hint and the reveal control below must stay on a 720px screen. Only the
          history scrolls — never the page.

          Focusable and labelled, because a scroll region a keyboard user cannot
          reach is a WCAG 2.1.1 failure — axe caught exactly that when the cap
          was first added. */}
      <div
        ref={historyRef}
        tabIndex={0}
        role="log"
        aria-label="Conversation with Kilimo Desk"
        className={`space-y-3 overflow-y-auto px-4 py-4 focus-visible:ring-2 focus-visible:ring-info ${
          compact ? "max-h-[132px] min-h-[80px]" : "max-h-[268px] min-h-[160px]"
        }`}
      >
        {exchanges.length === 0 ? (
          <p className="text-finding text-dim">
            No messages yet. Ask a question, or pick one of the examples below.
          </p>
        ) : null}

        {exchanges.map((exchange) => (
          <div key={exchange.id} className="space-y-2">
            <Turn speaker="You" tone="member">
              {exchange.memberText}
            </Turn>

            {exchange.status === "pending" ? (
              <Turn speaker="Kilimo Desk" tone="assistant">
                <span className="text-dim">Typing…</span>
              </Turn>
            ) : null}

            {exchange.status === "failed" ? (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3.5 py-2.5">
                <p className="text-turn text-stop">
                  Sorry — the assistant could not be reached. {exchange.error}
                </p>
              </div>
            ) : null}

            {exchange.status === "done" && exchange.response ? (
              <Turn speaker="Kilimo Desk" tone="assistant">
                {exchange.response.final}
              </Turn>
            ) : null}
          </div>
        ))}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(draft);
        }}
        className="border-t border-line px-4 py-3"
      >
        <div className="flex gap-2.5">
          <label htmlFor="message" className="sr-only">
            Your message to Kilimo Desk
          </label>
          <input
            id="message"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            maxLength={MAX_INPUT_CHARS + 1}
            placeholder="e.g. When are the collection points open?"
            className="min-w-0 flex-1 rounded-lg border border-line bg-[#fcfdfc] px-3.5 py-2.5 text-turn outline-none focus:border-transparent focus:ring-2 focus:ring-info"
          />
          <button
            type="submit"
            disabled={inFlight}
            className="whitespace-nowrap rounded-lg bg-info px-5 py-2.5 text-turn font-semibold text-white disabled:opacity-50"
          >
            {inFlight ? "Sending…" : "Send"}
          </button>
        </div>

        {compact ? null : (
          <p className="pt-1.5 text-finding text-dim">
            Use an example below, or invented details. Do not enter real personal information.
          </p>
        )}
        {validationError ? (
          <p className="pt-1 text-finding font-semibold text-stop">{validationError}</p>
        ) : null}
      </form>

      <div className="border-t border-line px-4 py-3">
        <button
          type="button"
          onClick={() => setShowExamples((v) => !v)}
          aria-expanded={showExamples}
          className="text-finding font-semibold text-dim hover:text-info"
        >
          {showExamples ? "Hide examples" : "Show examples"} ({promptCount})
        </button>

        {/* Collapsed by default. Expanded, the eight groups run to ~350px of a
            720px viewport, which pushed the reveal control and the answer off a
            1280x720 screen share — the exact thing Requirement 6 forbids. The
            presenter opens it, fires a prompt, and it closes on submission. */}
        {showExamples ? (
          <div className="space-y-1.5 pt-2">
            {PROMPT_GROUPS.map((group) => (
              <div key={group.label} className="flex flex-wrap items-baseline gap-1.5">
                <span className="min-w-[104px] text-finding font-semibold text-dim">
                  {group.label}
                </span>
                {group.prompts.map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    disabled={inFlight}
                    onClick={() => send(prompt)}
                    className="max-w-full rounded-full border border-line bg-[#fcfdfc] px-2.5 py-1 text-left text-finding hover:border-info hover:text-info disabled:opacity-50"
                  >
                    {/* Rendered in full and wrapped: no ellipsis, so the audience
                        reads the whole question that was asked. */}
                    {prompt}
                  </button>
                ))}
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function Turn({
  speaker,
  tone,
  children,
}: {
  speaker: string;
  tone: "member" | "assistant";
  children: React.ReactNode;
}) {
  return (
    <div
      className={
        tone === "member"
          ? "ml-auto max-w-[85%] rounded-lg border border-line bg-[#f5f7f4] px-3.5 py-2.5"
          : "max-w-[85%] rounded-lg border border-line bg-white px-3.5 py-2.5"
      }
    >
      <p className="pb-0.5 text-finding font-semibold text-dim">{speaker}</p>
      <p className="whitespace-pre-wrap break-words text-turn text-ink">{children}</p>
    </div>
  );
}
