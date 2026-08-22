import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GroundingTool } from "./GroundingTool";
import { GROUNDING_CASES } from "@/lib/samples";
import { CONTEXT } from "@/test/fixtures";
import type { StageResult } from "@/lib/types";

const verify = vi.fn();
vi.mock("@/lib/api", () => ({
  verify: (q: string, a: string) => verify(q, a),
  apiBaseUrl: "http://localhost:8000",
  ApiError: class ApiError extends Error {},
}));

const PASSED: StageResult = {
  stage: "verify",
  intervened: false,
  hits: [
    { policy: "grounding", detail: "score 0.94 vs threshold 0.7", action: "NONE", where: "output", score: 0.94, threshold: 0.7, passed: true },
    { policy: "relevance", detail: "score 0.91 vs threshold 0.7", action: "NONE", where: "output", score: 0.91, threshold: 0.7, passed: true },
  ],
  text: null,
  reason: null,
  stop_reason: null,
  model_invoked: false,
  latency_ms: 210,
  raw: { assessments: [] },
  replayed: null,
};

const RELEVANCE_FAILED: StageResult = {
  ...PASSED,
  intervened: true,
  hits: [
    { policy: "grounding", detail: "score 0.96 vs threshold 0.7", action: "NONE", where: "output", score: 0.96, threshold: 0.7, passed: true },
    { policy: "relevance", detail: "score 0.12 vs threshold 0.7", action: "BLOCKED", where: "output", score: 0.12, threshold: 0.7, passed: false },
  ],
};

beforeEach(() => verify.mockReset());

describe("the grounding tool", () => {
  it("presents the bulletin as the grounding source", () => {
    render(<GroundingTool ctx={CONTEXT} />);
    expect(screen.getByText(/Collection points at Kangema and Kiriaini/)).toBeInTheDocument();
    expect(screen.getByText(/grounding ≥ 0.7 · relevance ≥ 0.7/)).toBeInTheDocument();
  });

  it("presents all three committed cases with their expected outcome as text", () => {
    render(<GroundingTool ctx={CONTEXT} />);
    expect(GROUNDING_CASES).toHaveLength(3);
    for (const c of GROUNDING_CASES) {
      expect(screen.getByRole("button", { name: c.label })).toBeInTheDocument();
      expect(screen.getByText(`expect: ${c.expect}`)).toBeInTheDocument();
    }
  });

  it("reports both scores, both thresholds and a pass indicator per filter", async () => {
    verify.mockResolvedValue(PASSED);
    render(<GroundingTool ctx={CONTEXT} />);

    await userEvent.click(screen.getByRole("button", { name: /Check grounding/ }));

    await waitFor(() => expect(screen.getByText("Passed both checks")).toBeInTheDocument());
    expect(screen.getByText(/score 0.94 · threshold 0.7/)).toBeInTheDocument();
    expect(screen.getByText(/score 0.91 · threshold 0.7/)).toBeInTheDocument();
    expect(screen.getAllByText("passed")).toHaveLength(2);
  });

  it("shows grounding passing while relevance fails — two independent checks", async () => {
    verify.mockResolvedValue(RELEVANCE_FAILED);
    render(<GroundingTool ctx={CONTEXT} />);

    await userEvent.click(screen.getByRole("button", { name: /Check grounding/ }));

    await waitFor(() => expect(screen.getByText("Blocked — a check failed")).toBeInTheDocument());
    expect(screen.getByText("passed")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();
  });

  it("submits the selected case's question and answer", async () => {
    verify.mockResolvedValue(PASSED);
    render(<GroundingTool ctx={CONTEXT} />);

    const c = GROUNDING_CASES[2];
    await userEvent.click(screen.getByRole("button", { name: c.label }));

    await waitFor(() => expect(verify).toHaveBeenCalledWith(c.question, c.answer));
  });

  it("retains the previous result when a call fails", async () => {
    verify.mockResolvedValueOnce(PASSED).mockRejectedValueOnce(new Error("ThrottlingException"));
    render(<GroundingTool ctx={CONTEXT} />);

    await userEvent.click(screen.getByRole("button", { name: /Check grounding/ }));
    await waitFor(() => expect(screen.getByText("Passed both checks")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: /Check grounding/ }));
    await waitFor(() => expect(screen.getByText(/ThrottlingException/)).toBeInTheDocument());

    // The comparison the presenter was making survives the failure.
    expect(screen.getByText("Passed both checks")).toBeInTheDocument();
    expect(screen.getByText(/api\/verify/)).toBeInTheDocument();
  });

  it("accepts an operator-entered question and answer", async () => {
    verify.mockResolvedValue(PASSED);
    render(<GroundingTool ctx={CONTEXT} />);

    const question = screen.getByLabelText(/Question asked/);
    await userEvent.clear(question);
    await userEvent.type(question, "Do I need a member number?");
    await userEvent.click(screen.getByRole("button", { name: /Check grounding/ }));

    await waitFor(() =>
      expect(verify).toHaveBeenCalledWith("Do I need a member number?", expect.any(String)),
    );
  });

  it("rejects an empty field without calling the API", async () => {
    render(<GroundingTool ctx={CONTEXT} />);

    await userEvent.clear(screen.getByLabelText(/Answer under test/));
    await userEvent.click(screen.getByRole("button", { name: /Check grounding/ }));

    expect(verify).not.toHaveBeenCalled();
    expect(screen.getByText(/Both a question and a candidate answer are required/)).toBeInTheDocument();
  });
});
