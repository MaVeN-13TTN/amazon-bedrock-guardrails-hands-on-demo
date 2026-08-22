import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Home from "./page";
import { ANSWERED, CONTEXT, REFUSED } from "@/test/fixtures";

const ask = vi.fn();
const getContext = vi.fn();
vi.mock("@/lib/api", () => ({
  ask: (text: string) => ask(text),
  getContext: () => getContext(),
  verify: vi.fn(),
  apiBaseUrl: "http://localhost:8000",
  ApiError: class ApiError extends Error {},
}));

beforeEach(() => {
  ask.mockReset();
  getContext.mockReset().mockResolvedValue(CONTEXT);
});

describe("the entry route", () => {
  it("opens on the member's view, not an engineering console", async () => {
    render(<Home />);

    await waitFor(() => expect(screen.getByText("Highland Growers Co-operative")).toBeInTheDocument());
    expect(screen.getByText("Ask Kilimo Desk")).toBeInTheDocument();
    // The co-op sections are visible; no stage cards are.
    expect(screen.getByText("Collection points")).toBeInTheDocument();
    expect(screen.queryByText("1 · Screen")).toBeNull();
  });

  it("presents exactly one free-text input and no sign-in", async () => {
    const { container } = render(<Home />);
    await waitFor(() => expect(screen.getByText("Ask Kilimo Desk")).toBeInTheDocument());

    const textInputs = container.querySelectorAll('input[type="text"], input:not([type])');
    expect(textInputs).toHaveLength(1);
    expect(container.querySelector('input[type="password"]')).toBeNull();
    expect(screen.queryByText(/sign in|log in|register/i)).toBeNull();
  });

  it("keeps the disclosure visible even when the context fails", async () => {
    getContext.mockRejectedValue(new Error("503 Service Unavailable"));
    render(<Home />);

    // The disclosure is rendered outside the conditional, so it survives.
    await waitFor(() =>
      expect(screen.getByText(/Demonstration only/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/the co-operative does not/)).toBeInTheDocument();
    expect(screen.getByText(/503 Service Unavailable/)).toBeInTheDocument();
  });
});

describe("one request, two views", () => {
  it("derives both views from a single response", async () => {
    ask.mockResolvedValue(REFUSED);
    render(<Home />);
    await waitFor(() => expect(screen.getByText("Ask Kilimo Desk")).toBeInTheDocument());

    await userEvent.type(screen.getByLabelText(/Your message/), "how much fungicide?");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(screen.getByText(REFUSED.final)).toBeInTheDocument());

    // The member reads the refusal first, with no policy name in sight.
    expect(screen.queryByText(/Agrochemical Dosing/)).toBeNull();
    expect(ask).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: /what the system did/ }));

    // The reveal, from the same response — no second call.
    expect(screen.getByText(/Agrochemical Dosing/)).toBeInTheDocument();
    expect(screen.getAllByText("Not run")).toHaveLength(2);
    expect(ask).toHaveBeenCalledTimes(1);
  });

  it("retains the message history across every view switch", async () => {
    ask.mockResolvedValue(ANSWERED);
    render(<Home />);
    await waitFor(() => expect(screen.getByText("Ask Kilimo Desk")).toBeInTheDocument());

    await userEvent.type(screen.getByLabelText(/Your message/), "when do points open?");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(screen.getByText(ANSWERED.final)).toBeInTheDocument());

    const cycle = async (name: RegExp) => {
      await userEvent.click(screen.getByRole("button", { name }));
      await userEvent.click(screen.getByRole("button", { name }));
    };

    await cycle(/what the system did/);
    await cycle(/grounding check/);

    // A presenter can move between views and come back without re-sending.
    expect(screen.getByText("when do points open?")).toBeInTheDocument();
    expect(screen.getByText(ANSWERED.final)).toBeInTheDocument();
    expect(ask).toHaveBeenCalledTimes(1);
  });

  it("replaces the co-op sections rather than stacking below them", async () => {
    ask.mockResolvedValue(ANSWERED);
    render(<Home />);
    await waitFor(() => expect(screen.getByText("Collection points")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: /what the system did/ }));

    // Both views fit at 1280×720 because only one panel occupies the space below
    // the chat window.
    expect(screen.queryByText("Collection points")).toBeNull();
    expect(screen.getByText("What the system did")).toBeInTheDocument();
  });

  it("opens the grounding tool, labelled as an engineer's tool", async () => {
    render(<Home />);
    await waitFor(() => expect(screen.getByText("Ask Kilimo Desk")).toBeInTheDocument());

    expect(screen.getByText("(engineer tool)")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /grounding check/ }));
    expect(screen.getByText(/Judge an answer against the bulletin/)).toBeInTheDocument();
  });
});
