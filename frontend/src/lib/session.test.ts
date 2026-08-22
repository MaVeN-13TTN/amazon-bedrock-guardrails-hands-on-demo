import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MAX_INPUT_CHARS, useSession } from "./session";
import { ANSWERED, REFUSED } from "@/test/fixtures";

const ask = vi.fn();
vi.mock("@/lib/api", () => ({
  ask: (text: string) => ask(text),
  apiBaseUrl: "http://localhost:8000",
  ApiError: class ApiError extends Error {},
}));

beforeEach(() => ask.mockReset());

describe("one request, one response", () => {
  it("issues exactly one POST per submitted message", async () => {
    ask.mockResolvedValue(ANSWERED);
    const { result } = renderHook(() => useSession());

    await act(() => result.current.submit("When do points open?"));

    expect(ask).toHaveBeenCalledTimes(1);
    expect(ask).toHaveBeenCalledWith("When do points open?");
  });

  it("selecting a retained response issues no further request", async () => {
    ask.mockResolvedValue(ANSWERED);
    const { result } = renderHook(() => useSession());

    await act(() => result.current.submit("first"));
    await act(() => result.current.submit("second"));
    expect(ask).toHaveBeenCalledTimes(2);

    act(() => result.current.select("x1"));

    // The Background_View reads the retained object; it never re-evaluates, so
    // the two views cannot disagree about a probabilistic classification.
    expect(ask).toHaveBeenCalledTimes(2);
    expect(result.current.selected?.memberText).toBe("first");
  });

  it("appends the member turn before the call resolves", async () => {
    let release: (v: unknown) => void = () => {};
    ask.mockReturnValue(new Promise((r) => (release = r)));
    const { result } = renderHook(() => useSession());

    act(() => {
      void result.current.submit("pending question");
    });

    await waitFor(() => expect(result.current.exchanges).toHaveLength(1));
    expect(result.current.exchanges[0].memberText).toBe("pending question");
    expect(result.current.exchanges[0].status).toBe("pending");
    expect(result.current.inFlight).toBe(true);

    await act(async () => {
      release(ANSWERED);
    });
    expect(result.current.exchanges[0].status).toBe("done");
  });

  it("holds at most one request in flight", async () => {
    let release: (v: unknown) => void = () => {};
    ask.mockReturnValue(new Promise((r) => (release = r)));
    const { result } = renderHook(() => useSession());

    act(() => {
      void result.current.submit("first");
    });
    await waitFor(() => expect(result.current.inFlight).toBe(true));

    await act(() => result.current.submit("second"));
    expect(ask).toHaveBeenCalledTimes(1);

    await act(async () => {
      release(ANSWERED);
    });
  });
});

describe("history", () => {
  it("retains every exchange in order", async () => {
    ask.mockResolvedValue(ANSWERED);
    const { result } = renderHook(() => useSession());

    await act(() => result.current.submit("one"));
    await act(() => result.current.submit("two"));
    await act(() => result.current.submit("three"));

    expect(result.current.exchanges.map((x) => x.memberText)).toEqual(["one", "two", "three"]);
  });

  it("selects the newest exchange by default", async () => {
    ask.mockResolvedValue(REFUSED);
    const { result } = renderHook(() => useSession());

    await act(() => result.current.submit("one"));
    await act(() => result.current.submit("two"));

    expect(result.current.selected?.memberText).toBe("two");
  });
});

describe("validation", () => {
  it("rejects an empty message without calling the API", async () => {
    const { result } = renderHook(() => useSession());
    await act(() => result.current.submit("   "));

    expect(ask).not.toHaveBeenCalled();
    expect(result.current.validationError).toMatch(/Type a question/);
  });

  it("rejects an over-long message naming the limit", async () => {
    const { result } = renderHook(() => useSession());
    await act(() => result.current.submit("x".repeat(MAX_INPUT_CHARS + 1)));

    expect(ask).not.toHaveBeenCalled();
    expect(result.current.validationError).toContain(String(MAX_INPUT_CHARS));
  });

  it("accepts a message at exactly the limit", async () => {
    ask.mockResolvedValue(ANSWERED);
    const { result } = renderHook(() => useSession());
    await act(() => result.current.submit("x".repeat(MAX_INPUT_CHARS)));

    expect(ask).toHaveBeenCalledTimes(1);
    expect(result.current.validationError).toBeNull();
  });
});

describe("failure", () => {
  it("records the endpoint and error, retaining prior turns", async () => {
    ask.mockResolvedValueOnce(ANSWERED).mockRejectedValueOnce(new Error("ThrottlingException"));
    const { result } = renderHook(() => useSession());

    await act(() => result.current.submit("first"));
    await act(() => result.current.submit("second"));

    expect(result.current.exchanges).toHaveLength(2);
    expect(result.current.exchanges[0].status).toBe("done");
    expect(result.current.exchanges[1].status).toBe("failed");
    expect(result.current.exchanges[1].error).toContain("/api/ask");
    expect(result.current.exchanges[1].error).toContain("ThrottlingException");
  });

  it("clears the in-flight flag after a failure", async () => {
    ask.mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useSession());

    await act(() => result.current.submit("a question"));
    expect(result.current.inFlight).toBe(false);
  });
});
