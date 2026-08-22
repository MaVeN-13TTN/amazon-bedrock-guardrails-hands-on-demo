"use client";

import { useCallback, useRef, useState } from "react";
import { ApiError, apiBaseUrl, ask } from "@/lib/api";
import type { AskResponse, ReplayMeta } from "@/lib/types";

export const MAX_INPUT_CHARS = 2000;

/**
 * One member message and everything that came back for it.
 *
 * The Chat_Window and the Background_View both read from this object. That is the
 * mechanism, not a convention: there is no second place either view could fetch
 * from, so the contrast being taught cannot be an artefact of two evaluations of
 * the same prompt disagreeing.
 */
export interface Exchange {
  id: string;
  memberText: string;
  status: "pending" | "done" | "failed";
  response: AskResponse | null;
  error: string | null;
  replayed: ReplayMeta | null;
}

export interface UseSession {
  exchanges: Exchange[];
  selected: Exchange | null;
  selectedId: string | null;
  inFlight: boolean;
  submit: (text: string) => Promise<void>;
  select: (id: string) => void;
  validationError: string | null;
}

function validate(text: string): string | null {
  const trimmed = text.trim();
  if (!trimmed) return "Type a question before sending.";
  if (trimmed.length > MAX_INPUT_CHARS) {
    return `That message is ${trimmed.length} characters. The limit is ${MAX_INPUT_CHARS}.`;
  }
  return null;
}

export function useSession(): UseSession {
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [inFlight, setInFlight] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const counter = useRef(0);

  const submit = useCallback(
    async (text: string) => {
      if (inFlight) return;

      const problem = validate(text);
      if (problem) {
        setValidationError(problem);
        return;
      }
      setValidationError(null);

      const trimmed = text.trim();
      const id = `x${++counter.current}`;

      // The member turn is appended before the call begins, so the pending state
      // is attached to a question the member can already see.
      setExchanges((prior) => [
        ...prior,
        { id, memberText: trimmed, status: "pending", response: null, error: null, replayed: null },
      ]);
      setSelectedId(id);
      setInFlight(true);

      try {
        const response = await ask(trimmed);
        setExchanges((prior) =>
          prior.map((x) =>
            x.id === id
              ? {
                  ...x,
                  status: "done",
                  response,
                  replayed: response.stages.find((s) => s.replayed)?.replayed ?? null,
                }
              : x,
          ),
        );
      } catch (e) {
        const detail = e instanceof ApiError ? e.message : String(e);
        setExchanges((prior) =>
          prior.map((x) =>
            x.id === id
              ? { ...x, status: "failed", error: `${apiBaseUrl}/api/ask — ${detail}` }
              : x,
          ),
        );
      } finally {
        setInFlight(false);
      }
    },
    [inFlight],
  );

  // Selection moves a pointer. It issues no request, so the Background_View can
  // never show a different evaluation from the one the member read.
  const select = useCallback((id: string) => setSelectedId(id), []);

  return {
    exchanges,
    selected: exchanges.find((x) => x.id === selectedId) ?? null,
    selectedId,
    inFlight,
    submit,
    select,
    validationError,
  };
}
