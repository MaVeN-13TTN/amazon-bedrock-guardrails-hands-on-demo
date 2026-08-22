import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Disclosure } from "./Disclosure";
import { LandingSections } from "./LandingSections";
import { CONTEXT } from "@/test/fixtures";

describe("the co-operative landing page", () => {
  it("presents between 3 and 6 titled sections", () => {
    const { container } = render(<LandingSections ctx={CONTEXT} ctxError={null} />);
    const titles = container.querySelectorAll("h3");
    expect(titles.length).toBeGreaterThanOrEqual(3);
    expect(titles.length).toBeLessThanOrEqual(6);
  });

  it("presents the collection-point facts from the bulletin", () => {
    render(<LandingSections ctx={CONTEXT} ctxError={null} />);
    expect(screen.getByText(/Kangema and Kiriaini/)).toBeInTheDocument();
    expect(screen.getByText(/06:00 to 10:00/)).toBeInTheDocument();
    expect(screen.getByText(/Tuesday and Friday only/)).toBeInTheDocument();
    expect(screen.getByText(/present a valid member number at the gate/)).toBeInTheDocument();
  });

  it("presents the payment facts from the bulletin", () => {
    render(<LandingSections ctx={CONTEXT} ctxError={null} />);
    expect(screen.getByText(/released fourteen days after grading is complete/)).toBeInTheDocument();
    expect(screen.getByText(/Grading results are posted at the collection point/)).toBeInTheDocument();
  });

  it("takes its prose from the context, holding no scenario text of its own", () => {
    render(<LandingSections ctx={CONTEXT} ctxError={null} />);
    for (const section of CONTEXT.about_sections) {
      expect(screen.getByText(section.title)).toBeInTheDocument();
      expect(screen.getByText(section.body)).toBeInTheDocument();
    }
  });

  it("every rendered fact appears in the bulletin the same response carried", () => {
    render(<LandingSections ctx={CONTEXT} ctxError={null} />);
    const f = CONTEXT.bulletin_facts;
    // A member could read the page and the bulletin side by side.
    for (const point of f.collection_points) {
      expect(CONTEXT.bulletin).toContain(point);
    }
    expect(CONTEXT.bulletin).toContain(f.gate_requirement);
    expect(CONTEXT.bulletin).toContain(f.payment_note);
  });

  it("marks sections unavailable on a context failure, without substitute content", () => {
    render(<LandingSections ctx={null} ctxError="503 Service Unavailable" />);

    expect(screen.getByText(/api\/context/)).toBeInTheDocument();
    expect(screen.getByText(/503 Service Unavailable/)).toBeInTheDocument();
    expect(screen.getAllByText("Unavailable — see the error above.")).toHaveLength(4);
    // No invented facts stand in for the real ones.
    expect(screen.queryByText(/Kangema/)).toBeNull();
    expect(screen.queryByText(/06:00/)).toBeNull();
  });
});

describe("the demo disclosure", () => {
  it("names everything fictional and warns against real personal information", () => {
    render(<Disclosure />);
    expect(screen.getByText(/the co-operative does not/)).toBeInTheDocument();
    expect(screen.getByText(/Project\s+Tumaini/)).toBeInTheDocument();
    expect(screen.getByText(/Batch Ledger v2/)).toBeInTheDocument();
    expect(screen.getByText(/Extension Bulletin 14/)).toBeInTheDocument();
    expect(screen.getByText(/Do not enter real personal information/)).toBeInTheDocument();
  });

  it("states that the API performs no authentication", () => {
    render(<Disclosure />);
    expect(screen.getByText(/performs no authentication/)).toBeInTheDocument();
  });

  it("remains visible at every scroll position", () => {
    const { container } = render(<Disclosure />);
    expect(container.firstElementChild?.className).toContain("sticky");
  });

  it("carries the replay indicator outside the chat window", () => {
    render(<Disclosure replaying={{ captured_utc: "2026-08-20", region: "eu-west-1" }} />);
    expect(screen.getByText(/Replaying a recorded result/)).toBeInTheDocument();
    expect(screen.getByText(/2026-08-20/)).toBeInTheDocument();
    expect(screen.getByText(/No live AWS call/)).toBeInTheDocument();
  });

  it("shows no replay indicator on a live run", () => {
    render(<Disclosure replaying={null} />);
    expect(screen.queryByText(/Replaying/)).toBeNull();
  });
});
