import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fc from "fast-check";
import { describe, expect, it, vi } from "vitest";
import { BackgroundView } from "./BackgroundView";
import { ChatWindow } from "./ChatWindow";
import type { Exchange } from "@/lib/session";
import type { AskResponse } from "@/lib/types";
import { ANSWERED, CONTEXT, MASKED, REFUSED, UNGROUNDED, stage } from "@/test/fixtures";

function done(memberText: string, response: AskResponse, id = "x1"): Exchange {
  return { id, memberText, status: "done", response, error: null, replayed: null };
}

function renderBg(exchanges: Exchange[], selectedIndex = 0) {
  const onSelect = vi.fn();
  const result = render(
    <BackgroundView
      exchanges={exchanges}
      selected={exchanges[selectedIndex] ?? null}
      ctx={CONTEXT}
      onSelect={onSelect}
    />,
  );
  return { onSelect, ...result };
}

describe("stage entries", () => {
  it("renders one entry per element of the stages array", () => {
    renderBg([done("a question", ANSWERED)]);
    expect(screen.getByText("1 · Screen")).toBeInTheDocument();
    expect(screen.getByText("2 · Answer")).toBeInTheDocument();
    expect(screen.getByText("3 · Verify")).toBeInTheDocument();
  });

  it("names stages that never ran and the stage that halted the request", () => {
    renderBg([done("how much fungicide?", REFUSED)]);

    expect(screen.getAllByText("Not run")).toHaveLength(2);
    // Work that did not happen, not missing interface.
    expect(
      screen.getAllByText(/The screen stage halted the request, so this stage never ran/),
    ).toHaveLength(2);
  });

  it("labels a stage that invoked no model", () => {
    renderBg([done("a question", ANSWERED)]);
    expect(screen.getAllByText("ApplyGuardrail · no model")).toHaveLength(2);
    expect(screen.getByText("Converse · model called")).toBeInTheDocument();
  });

  it("distinguishes intervened from passed in text, not only colour", () => {
    renderBg([done("how much fungicide?", REFUSED)]);
    expect(screen.getByText("Intervened")).toBeInTheDocument();
  });

  it("renders policy values verbatim, without rewording", () => {
    renderBg([done("how much fungicide?", REFUSED)]);
    // BLOCKED, not "blocked"; the reader can diff this against the raw payload.
    expect(screen.getByText(/denied topic/)).toBeInTheDocument();
    expect(screen.getByText(/Agrochemical Dosing/)).toBeInTheDocument();
    expect(screen.getByText(/BLOCKED/)).toBeInTheDocument();
  });

  it("shows the forwarded text and the rules that matched, for masking", () => {
    renderBg([done("I am Grace Wanjiku…", MASKED)]);

    expect(screen.getByText("Text forwarded to the model")).toBeInTheDocument();
    expect(screen.getByText(/\{NAME\}/)).toBeInTheDocument();
    expect(screen.getByText(/Co-op Member Number/)).toBeInTheDocument();
    expect(screen.getAllByText(/ANONYMIZED/).length).toBeGreaterThanOrEqual(3);
  });

  it("reports grounding scores against their thresholds", () => {
    renderBg([done("when do points open?", UNGROUNDED)]);
    expect(screen.getByText(/score 0.31 vs threshold 0.7/)).toBeInTheDocument();
  });

  it("labels answer-stage input findings as a second evaluation", () => {
    const twice: AskResponse = {
      ...ANSWERED,
      stages: [
        ANSWERED.stages[0],
        stage({
          stage: "answer",
          hits: [
            {
              policy: "content filter",
              detail: "PROMPT_ATTACK",
              action: "NONE",
              where: "input",
              score: "LOW",
              threshold: null,
              passed: null,
            },
          ],
        }),
        ANSWERED.stages[2],
      ],
    };
    renderBg([done("a question", twice)]);
    expect(
      screen.getByText(/second evaluation of the same submitted text/),
    ).toBeInTheDocument();
  });

  it("marks a replayed stage with its capture date and Region", () => {
    const replayed: AskResponse = {
      ...ANSWERED,
      stages: [
        stage({
          stage: "screen",
          replayed: {
            captured_utc: "2026-08-20",
            region: "eu-west-1",
            tier: "STANDARD",
            guardrail_version: "DRAFT",
          },
        }),
      ],
    };
    renderBg([done("a question", replayed)]);
    expect(screen.getByText(/Replayed from a recorded fixture/)).toBeInTheDocument();
    expect(screen.getByText(/2026-08-20/)).toBeInTheDocument();
  });
});

describe("attribution and provenance", () => {
  it("names the guardrail, version, Region and model", () => {
    renderBg([done("a question", ANSWERED)]);
    expect(screen.getByText(/abcd1234efgh/)).toBeInTheDocument();
    expect(screen.getByText(/eu-west-1/)).toBeInTheDocument();
    expect(screen.getByText(/claude-haiku-4-5/)).toBeInTheDocument();
  });

  it("shows stopped_at and total latency as visible text", () => {
    renderBg([done("how much fungicide?", REFUSED)]);
    expect(screen.getByText(/stopped at screen/)).toBeInTheDocument();
    expect(screen.getByText(/120ms total/)).toBeInTheDocument();
  });

  it("shows the member turn the findings belong to", () => {
    renderBg([done("how much fungicide?", REFUSED)]);
    expect(screen.getByText("The member asked")).toBeInTheDocument();
    expect(screen.getByText("how much fungicide?")).toBeInTheDocument();
  });

  it("keeps raw payloads collapsed until asked for", async () => {
    renderBg([done("a question", ANSWERED)]);
    expect(screen.queryByLabelText(/raw assessment/)).toBeNull();

    await userEvent.click(screen.getAllByRole("button", { name: /Show raw assessment/ })[0]);
    expect(screen.getByLabelText("screen raw assessment")).toBeInTheDocument();
  });

  it("offers a keyboard-operable control that enlarges the raw panel", async () => {
    renderBg([done("a question", ANSWERED)]);
    await userEvent.click(screen.getAllByRole("button", { name: /Show raw assessment/ })[0]);

    const panel = screen.getByLabelText("screen raw assessment");
    expect(panel.className).toContain("text-raw");

    await userEvent.click(screen.getByRole("button", { name: /Enlarge for the room/ }));
    expect(screen.getByLabelText("screen raw assessment").className).toContain("text-raw-lg");
  });
});

describe("selection and empty state", () => {
  it("states that nothing has been sent, naming the control that sends one", () => {
    renderBg([]);
    expect(screen.getByText(/No request has been sent yet/)).toBeInTheDocument();
    expect(screen.getByText(/Send button/)).toBeInTheDocument();
  });

  it("allows selection of a retained response by its member turn", async () => {
    const { onSelect } = renderBg([
      done("first question", ANSWERED, "x1"),
      done("second question", REFUSED, "x2"),
    ]);

    await userEvent.click(screen.getByRole("button", { name: "second question" }));
    expect(onSelect).toHaveBeenCalledWith("x2");
  });

  it("presents only the selected response's stages", () => {
    renderBg([done("first", ANSWERED, "x1"), done("second", REFUSED, "x2")], 1);
    // REFUSED carries one stage, so two must read as not run.
    expect(screen.getAllByText("Not run")).toHaveLength(2);
  });

  it("presents a failure with the failing stage named", () => {
    render(
      <BackgroundView
        exchanges={[
          {
            id: "x1",
            memberText: "a question",
            status: "failed",
            response: null,
            error: "http://localhost:8000/api/ask — answer stage: ThrottlingException",
            replayed: null,
          },
        ]}
        selected={{
          id: "x1",
          memberText: "a question",
          status: "failed",
          response: null,
          error: "http://localhost:8000/api/ask — answer stage: ThrottlingException",
          replayed: null,
        }}
        ctx={CONTEXT}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText("The request failed")).toBeInTheDocument();
    expect(screen.getByText(/answer stage: ThrottlingException/)).toBeInTheDocument();
  });
});

describe("the two views describe one request (invariants)", () => {
  const CASES = [ANSWERED, REFUSED, MASKED, UNGROUNDED];

  it("the assistant turn equals the final of the response the background renders", () => {
    fc.assert(
      fc.property(fc.constantFrom(...CASES), (response) => {
        const exchange = done("a question", response);

        const chat = render(
          <ChatWindow
            exchanges={[exchange]}
            inFlight={false}
            validationError={null}
            onSubmit={vi.fn()}
          />,
        );
        const turns = Array.from(chat.container.querySelectorAll("p.text-turn"))
          .map((n) => n.textContent ?? "")
          .join(" ");
        chat.unmount();

        const bg = render(
          <BackgroundView
            exchanges={[exchange]}
            selected={exchange}
            ctx={CONTEXT}
            onSelect={vi.fn()}
          />,
        );
        expect(turns).toContain(response.final);
        bg.unmount();
      }),
      { numRuns: 20 },
    );
  });

  it("the rendered entry count equals the stages length, matching by index", () => {
    fc.assert(
      fc.property(fc.constantFrom(...CASES), (response) => {
        const exchange = done("a question", response);
        const { container, unmount } = render(
          <BackgroundView
            exchanges={[exchange]}
            selected={exchange}
            ctx={CONTEXT}
            onSelect={vi.fn()}
          />,
        );

        const titles = Array.from(container.querySelectorAll("h3.text-stage"))
          .map((n) => n.textContent ?? "")
          .filter((t) => !t.includes("Not run"));
        const ran = titles.slice(0, response.stages.length);

        expect(ran).toHaveLength(response.stages.length);
        response.stages.forEach((s, i) => {
          expect(ran[i].toLowerCase()).toContain(s.stage);
        });
        unmount();
      }),
      { numRuns: 20 },
    );
  });
});
