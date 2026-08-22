import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fc from "fast-check";
import { describe, expect, it, vi } from "vitest";
import { ChatWindow } from "./ChatWindow";
import { PROMPT_GROUPS } from "@/lib/samples";
import type { Exchange } from "@/lib/session";
import { ANSWERED, MASKED, REFUSED, UNGROUNDED, policyVocabulary, stage } from "@/test/fixtures";
import type { AskResponse } from "@/lib/types";

function done(memberText: string, response: AskResponse): Exchange {
  return { id: "x1", memberText, status: "done", response, error: null, replayed: null };
}

function renderChat(exchanges: Exchange[], overrides = {}) {
  const onSubmit = vi.fn();
  render(
    <ChatWindow
      exchanges={exchanges}
      inFlight={false}
      validationError={null}
      onSubmit={onSubmit}
      {...overrides}
    />,
  );
  return { onSubmit };
}

describe("the member's view", () => {
  it("renders the answer as the response's final value, verbatim", () => {
    renderChat([done("When are the collection points open?", ANSWERED)]);
    expect(screen.getByText(ANSWERED.final)).toBeInTheDocument();
  });

  it("renders a refusal in the same treatment as an answer", () => {
    const { container: refused } = render(
      <ChatWindow
        exchanges={[done("how much fungicide?", REFUSED)]}
        inFlight={false}
        validationError={null}
        onSubmit={vi.fn()}
      />,
    );
    const refusalClasses = refused.querySelectorAll("p.text-turn")[1]?.className;

    const { container: answered } = render(
      <ChatWindow
        exchanges={[done("when do points open?", ANSWERED)]}
        inFlight={false}
        validationError={null}
        onSubmit={vi.fn()}
      />,
    );
    const answerClasses = answered.querySelectorAll("p.text-turn")[1]?.className;

    // A member must not be able to tell a block from an answer by its styling.
    expect(refusalClasses).toBe(answerClasses);
  });

  it("shows no sign that masking occurred", () => {
    const typed = "I am Grace Wanjiku, member HG-004182, my number is 0722135790.";
    const { container } = render(
      <ChatWindow
        exchanges={[done(typed, MASKED)]}
        inFlight={false}
        validationError={null}
        onSubmit={vi.fn()}
      />,
    );
    const turns = Array.from(container.querySelectorAll("p.text-turn"))
      .map((n) => n.textContent ?? "")
      .join(" ");

    // The member turn is what they typed; the reply looks ordinary.
    expect(turns).toContain(typed);
    expect(turns).toContain(MASKED.final);
    // No placeholder token, no rule name, no action.
    expect(turns).not.toContain("{NAME}");
    expect(turns).not.toContain("ANONYMIZED");
    expect(turns).not.toContain("Co-op Member Number");
  });

  it("delivers a grounding failure as the safe fallback", () => {
    renderChat([done("when do points open?", UNGROUNDED)]);
    expect(screen.getByText(UNGROUNDED.final)).toBeInTheDocument();
    expect(screen.queryByText(/0.31/)).toBeNull();
    expect(screen.queryByText(/grounding/i)).toBeNull();
  });

  it("leaks no policy vocabulary, for any response (invariant)", () => {
    fc.assert(
      fc.property(
        fc.constantFrom(ANSWERED, REFUSED, MASKED, UNGROUNDED),
        (response) => {
          const { container, unmount } = render(
            <ChatWindow
              exchanges={[done("a question", response)]}
              inFlight={false}
              validationError={null}
              onSubmit={vi.fn()}
            />,
          );
          const turns = Array.from(container.querySelectorAll("p.text-turn"))
            .map((n) => n.textContent ?? "")
            .join(" ");

          expect(turns).toContain(response.final);
          for (const word of policyVocabulary(response)) {
            // The final text itself may legitimately contain a number; only
            // check vocabulary that is not part of what the member reads.
            if (response.final.includes(word)) continue;
            expect(turns).not.toContain(word);
          }
          unmount();
        },
      ),
      { numRuns: 20 },
    );
  });

  it("keeps the member turn visible while a request is in flight", () => {
    render(
      <ChatWindow
        exchanges={[
          { id: "x1", memberText: "pending question", status: "pending", response: null, error: null, replayed: null },
        ]}
        inFlight
        validationError={null}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByText("pending question")).toBeInTheDocument();
    expect(screen.getByText(/Typing/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Sending/ })).toBeDisabled();
  });

  it("names the endpoint and error when the call failed", () => {
    render(
      <ChatWindow
        exchanges={[
          {
            id: "x1",
            memberText: "a question",
            status: "failed",
            response: null,
            error: "http://localhost:8000/api/ask — ThrottlingException",
            replayed: null,
          },
        ]}
        inFlight={false}
        validationError={null}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByText(/api\/ask/)).toBeInTheDocument();
    expect(screen.getByText(/ThrottlingException/)).toBeInTheDocument();
    expect(screen.getByText("a question")).toBeInTheDocument();
  });

  it("hints that no real personal information should be entered", () => {
    renderChat([]);
    expect(screen.getByText(/Do not enter real personal information/)).toBeInTheDocument();
  });

  it("reports a validation problem without calling the API", () => {
    renderChat([], { validationError: "That message is 2001 characters. The limit is 2000." });
    expect(screen.getByText(/2001 characters/)).toBeInTheDocument();
  });
});

async function openExamples() {
  await userEvent.click(screen.getByRole("button", { name: /Show examples/ }));
}

describe("sample prompts", () => {
  it("presents every committed prompt as its own control", async () => {
    renderChat([]);
    await openExamples();
    const total = PROMPT_GROUPS.reduce((n, g) => n + g.prompts.length, 0);
    expect(total).toBe(9);
    for (const group of PROMPT_GROUPS) {
      expect(screen.getByText(group.label)).toBeInTheDocument();
      for (const prompt of group.prompts) {
        expect(screen.getByRole("button", { name: prompt })).toBeInTheDocument();
      }
    }
  });

  it("names how many examples are available before opening them", () => {
    renderChat([]);
    expect(screen.getByRole("button", { name: /Show examples \(9\)/ })).toBeInTheDocument();
  });

  it("closes the examples once a prompt is fired", async () => {
    renderChat([]);
    await openExamples();
    const prompt = PROMPT_GROUPS[0].prompts[0];
    await userEvent.click(screen.getByRole("button", { name: prompt }));
    expect(screen.getByRole("button", { name: /Show examples/ })).toBeInTheDocument();
  });

  it("retains the eight committed group labels", () => {
    expect(PROMPT_GROUPS.map((g) => g.label)).toEqual([
      "in scope",
      "dosing",
      "land",
      "credit",
      "internal leak",
      "PII",
      "prompt attack",
      "tier gap",
    ]);
  });

  it("submits the prompt text character for character", async () => {
    const { onSubmit } = renderChat([]);
    await openExamples();
    const prompt = PROMPT_GROUPS[1].prompts[0];
    await userEvent.click(screen.getByRole("button", { name: prompt }));
    expect(onSubmit).toHaveBeenCalledWith(prompt);
  });

  it("renders prompt labels in full, without truncation", async () => {
    renderChat([]);
    await openExamples();
    const long = PROMPT_GROUPS.flatMap((g) => g.prompts).reduce((a, b) =>
      a.length > b.length ? a : b,
    );
    const button = screen.getByRole("button", { name: long });
    expect(button.textContent).toBe(long);
    expect(button.textContent).not.toContain("…");
  });

  it("makes no call while a request is in flight", async () => {
    const onSubmit = vi.fn();
    render(
      <ChatWindow exchanges={[]} inFlight validationError={null} onSubmit={onSubmit} />,
    );
    await openExamples();
    const prompt = PROMPT_GROUPS[0].prompts[0];
    await userEvent.click(screen.getByRole("button", { name: prompt }));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("carries only invented values in the PII prompt", () => {
    const pii = PROMPT_GROUPS.find((g) => g.label === "PII")!.prompts[0];
    expect(pii).toContain("Grace Wanjiku");
    expect(pii).toContain("HG-004182");
    expect(pii).toContain("0722135790");
  });
});

describe("typed submission", () => {
  it("sends what was typed and clears the field", async () => {
    const { onSubmit } = renderChat([]);
    const field = screen.getByLabelText(/Your message/);
    await userEvent.type(field, "When do I get paid?");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith("When do I get paid?"));
    expect(field).toHaveValue("");
  });
});

describe("turn history", () => {
  it("presents member and assistant turns in the order they occurred", () => {
    render(
      <ChatWindow
        exchanges={[
          done("first question", ANSWERED),
          { ...done("second question", REFUSED), id: "x2" },
        ]}
        inFlight={false}
        validationError={null}
        onSubmit={vi.fn()}
      />,
    );
    const text = document.body.textContent ?? "";
    expect(text.indexOf("first question")).toBeLessThan(text.indexOf("second question"));
    expect(text.indexOf(ANSWERED.final)).toBeLessThan(text.indexOf(REFUSED.final));
  });

  it("labels each turn by its speaker", () => {
    renderChat([done("a question", ANSWERED)]);
    expect(screen.getByText("You")).toBeInTheDocument();
    expect(screen.getByText("Kilimo Desk")).toBeInTheDocument();
  });
});
