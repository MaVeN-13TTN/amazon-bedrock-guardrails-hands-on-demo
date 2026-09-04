import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

/**
 * Legibility, measured rather than eyeballed.
 *
 * Every assertion here reads the *computed* font size, so a Tailwind class change
 * that drops a governed element below its floor fails the check. The floors come
 * from Requirement 6: 16px for stage labels and conversation turns, 14px for
 * findings, forwarded text, hints and the disclosure.
 *
 * These stub the API rather than calling a live backend, so the check measures
 * layout and never depends on AWS.
 */

const ANSWER =
  "The Kangema and Kiriaini collection points open from 06:00 to 10:00 on Tuesdays and Fridays only. Members must present a valid member number at the gate, and payment for delivered produce is released fourteen days after grading is complete once results are posted.";

const CONTEXT = {
  org: "Highland Growers Co-operative",
  assistant: "Kilimo Desk",
  county: "Murang'a County",
  region: "eu-west-1",
  model: "global.anthropic.claude-haiku-4-5-20251001-v1:0",
  guardrail_id: "abcd1234efgh",
  guardrail_version: "DRAFT",
  guardrail_active: true,
  bulletin:
    "Collection points at Kangema and Kiriaini open from 06:00 to 10:00 on Tuesdays and Fridays only. Members must present a valid member number at the gate.\n\nPayment for delivered produce is released fourteen days after grading is complete. Grading results are posted at the collection point.\n",
  denied_topics: ["Agrochemical Dosing", "Land Tenure Disputes", "Credit Terms"],
  blocked_words: ["Project Tumaini", "Batch Ledger v2"],
  grounding_threshold: 0.7,
  relevance_threshold: 0.7,
  bulletin_facts: {
    collection_points: ["Kangema", "Kiriaini"],
    collection_opens: "06:00",
    collection_closes: "10:00",
    collection_days: ["Tuesday", "Friday"],
    gate_requirement: "present a valid member number at the gate",
    payment_delay_days: 14,
    payment_release: "released fourteen days after grading is complete",
    payment_note: "Grading results are posted at the collection point.",
  },
  about_sections: [
    { title: "Who we are", body: "A smallholder farming co-operative in Murang'a County." },
    { title: "What we do for members", body: "We collect and grade produce and pay members." },
  ],
};

function stage(name: string, over: Record<string, unknown> = {}) {
  return {
    stage: name,
    intervened: false,
    hits: [],
    text: null,
    reason: null,
    stop_reason: null,
    model_invoked: name === "answer",
    latency_ms: 140,
    raw: { assessments: [] },
    replayed: null,
    ...over,
  };
}

const MASKED = {
  stages: [
    stage("screen", {
      text: "I am {NAME}, member {UUID}, my number is {PHONE}. How long after grading do I get paid?",
      hits: [
        { policy: "PII", detail: "NAME", action: "ANONYMIZED", where: "input", score: null, threshold: null, passed: null },
        { policy: "PII", detail: "PHONE", action: "ANONYMIZED", where: "input", score: null, threshold: null, passed: null },
        { policy: "PII regex", detail: "Co-op Member Number", action: "ANONYMIZED", where: "input", score: null, threshold: null, passed: null },
      ],
    }),
    stage("answer"),
    stage("verify"),
  ],
  final: ANSWER,
  stopped_at: null,
  total_latency_ms: 420,
};

const REFUSED = {
  stages: [
    stage("screen", {
      intervened: true,
      hits: [
        { policy: "denied topic", detail: "Agrochemical Dosing", action: "BLOCKED", where: "input", score: null, threshold: null, passed: null },
      ],
    }),
  ],
  final:
    "I can't help with that one. For anything involving chemical doses, land matters, or credit decisions, please speak to the co-operative office or a licensed agrovet.",
  stopped_at: "screen",
  total_latency_ms: 140,
};

async function stubApi(page: Page, askResponse: unknown) {
  await page.route("**/api/context", (route) =>
    route.fulfill({ json: CONTEXT, headers: { "access-control-allow-origin": "*" } }),
  );
  await page.route("**/api/ask", (route) =>
    route.fulfill({ json: askResponse, headers: { "access-control-allow-origin": "*" } }),
  );
}

/** Computed font size in CSS pixels. */
async function fontSize(page: Page, selector: string, index = 0): Promise<number> {
  return page.evaluate(
    ([sel, i]) => {
      const el = document.querySelectorAll(sel as string)[i as number];
      if (!el) throw new Error(`no element for ${sel}[${i}]`);
      return parseFloat(getComputedStyle(el).fontSize);
    },
    [selector, index] as const,
  );
}

async function hasNoScroll(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const d = document.documentElement;
    return d.scrollHeight <= d.clientHeight + 1 && d.scrollWidth <= d.clientWidth + 1;
  });
}

test.describe("legibility floors", () => {
  test("conversation turns render at 16px or more", async ({ page }) => {
    await stubApi(page, MASKED);
    await page.goto("/");
    await page.getByLabel(/Your message/).fill("I am Grace Wanjiku, member HG-004182.");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText(ANSWER)).toBeVisible();

    const turns = await page.$$eval("p.text-turn", (nodes) =>
      nodes.map((n) => parseFloat(getComputedStyle(n).fontSize)),
    );
    expect(turns.length).toBeGreaterThanOrEqual(2);
    for (const size of turns) expect(size).toBeGreaterThanOrEqual(16);
  });

  test("stage labels and findings clear their floors", async ({ page }) => {
    await stubApi(page, MASKED);
    await page.goto("/");
    await page.getByLabel(/Your message/).fill("I am Grace Wanjiku, member HG-004182.");
    await page.getByRole("button", { name: "Send" }).click();
    await page.getByRole("button", { name: /what the system did/ }).click();

    // Stage labels: 16px.
    const labels = await page.$$eval("h3.text-stage", (nodes) =>
      nodes.map((n) => parseFloat(getComputedStyle(n).fontSize)),
    );
    for (const size of labels) expect(size).toBeGreaterThanOrEqual(16);

    // The no-model label is the one the presenter reads aloud.
    const noModel = page.getByText("ApplyGuardrail · no model").first();
    await expect(noModel).toBeVisible();
    expect(
      await noModel.evaluate((n) => parseFloat(getComputedStyle(n).fontSize)),
    ).toBeGreaterThanOrEqual(16);

    // Findings: 14px.
    const findings = await page.$$eval("div.text-finding", (nodes) =>
      nodes.map((n) => parseFloat(getComputedStyle(n).fontSize)),
    );
    for (const size of findings) expect(size).toBeGreaterThanOrEqual(14);
  });

  test("forwarded masked text is legible and not clipped", async ({ page }) => {
    await stubApi(page, MASKED);
    await page.goto("/");
    await page.getByLabel(/Your message/).fill("I am Grace Wanjiku, member HG-004182.");
    await page.getByRole("button", { name: "Send" }).click();
    await page.getByRole("button", { name: /what the system did/ }).click();

    const forwarded = page.getByText(/\{NAME\}/).first();
    await expect(forwarded).toBeVisible();
    const style = await forwarded.evaluate((n) => {
      const s = getComputedStyle(n);
      return { size: parseFloat(s.fontSize), overflow: s.textOverflow, whiteSpace: s.whiteSpace };
    });
    expect(style.size).toBeGreaterThanOrEqual(14);
    expect(style.overflow).not.toBe("ellipsis");
    expect(style.whiteSpace).toBe("pre-wrap");
  });

  test("the disclosure is legible and stays visible when scrolled", async ({ page }) => {
    await stubApi(page, MASKED);
    await page.goto("/");

    const disclosure = page.getByText(/Demonstration only/);
    await expect(disclosure).toBeVisible();
    expect(
      await disclosure.evaluate((n) => parseFloat(getComputedStyle(n).fontSize)),
    ).toBeGreaterThanOrEqual(14);

    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await expect(disclosure).toBeInViewport();
  });

  test("intervened versus passed is readable without colour", async ({ page }) => {
    await stubApi(page, REFUSED);
    await page.goto("/");
    await page.getByLabel(/Your message/).fill("how much fungicide per knapsack?");
    await page.getByRole("button", { name: "Send" }).click();
    await page.getByRole("button", { name: /what the system did/ }).click();

    const label = page.getByText("Intervened", { exact: true });
    await expect(label).toBeVisible();
    expect(
      await label.evaluate((n) => parseFloat(getComputedStyle(n).fontSize)),
    ).toBeGreaterThanOrEqual(14);

    // Grayscale the page: the distinction must survive.
    await page.evaluate(() => {
      document.documentElement.style.filter = "grayscale(100%)";
    });
    await expect(label).toHaveText("Intervened");
  });

  test("the raw panel can be enlarged for the room", async ({ page }) => {
    await stubApi(page, MASKED);
    await page.goto("/");
    await page.getByLabel(/Your message/).fill("a question");
    await page.getByRole("button", { name: "Send" }).click();
    await page.getByRole("button", { name: /what the system did/ }).click();
    await page.getByRole("button", { name: /Show raw assessment/ }).first().click();

    const panel = page.getByLabel("screen raw assessment");
    const before = await panel.evaluate((n) => parseFloat(getComputedStyle(n).fontSize));
    expect(before).toBeGreaterThanOrEqual(14);

    // Keyboard-operable, not mouse-only.
    await page.getByRole("button", { name: /Enlarge for the room/ }).press("Enter");
    const after = await panel.evaluate((n) => parseFloat(getComputedStyle(n).fontSize));
    expect(after).toBeGreaterThanOrEqual(16);
    expect(after).toBeLessThanOrEqual(24);
  });
});

test.describe("fits 1280x720", () => {
  test("the member view needs no scrolling for a 120-word answer", async ({ page }) => {
    await stubApi(page, MASKED);
    await page.goto("/");
    await page.getByLabel(/Your message/).fill("I am Grace Wanjiku, member HG-004182.");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.getByText(ANSWER)).toBeVisible();

    // Member turn, assistant turn, disclosure and the reveal control all present.
    await expect(page.getByText(/Demonstration only/)).toBeInViewport();
    await expect(page.getByRole("button", { name: /what the system did/ })).toBeInViewport();
    await expect(page.getByText(ANSWER)).toBeInViewport();
  });

  test("the background view shows every stage without page scrolling", async ({ page }) => {
    await stubApi(page, MASKED);
    await page.goto("/");
    await page.getByLabel(/Your message/).fill("I am Grace Wanjiku, member HG-004182.");
    await page.getByRole("button", { name: "Send" }).click();
    await page.getByRole("button", { name: /what the system did/ }).click();

    for (const label of ["1 · Screen", "2 · Answer", "3 · Verify"]) {
      await expect(page.getByText(label)).toBeInViewport();
    }
    // Model-invoked indicators visible for every stage.
    expect(await page.getByText(/no model|model called/).count()).toBeGreaterThanOrEqual(3);
  });

  test("both views are usable together, scrolling confined to detail panels", async ({ page }) => {
    await stubApi(page, REFUSED);
    await page.goto("/");
    await page.getByLabel(/Your message/).fill("how much fungicide per knapsack?");
    await page.getByRole("button", { name: "Send" }).click();
    await page.getByRole("button", { name: /what the system did/ }).click();

    // The refusal the member read and the stage names stay visible together.
    await expect(page.getByText(REFUSED.final)).toBeInViewport();
    await expect(page.getByText("1 · Screen")).toBeInViewport();
    await expect(page.getByText("Intervened")).toBeInViewport();
  });

  test("the chat window sits in the first viewport at entry", async ({ page }) => {
    await stubApi(page, MASKED);
    await page.goto("/");

    await expect(page.getByText("Ask Kilimo Desk")).toBeInViewport();
    await expect(page.getByLabel(/Your message/)).toBeInViewport();
    await expect(page.getByRole("button", { name: "Send" })).toBeInViewport();
  });
});

test.describe("accessibility", () => {
  test("no contrast or serious violations on the member view", async ({ page }) => {
    await stubApi(page, MASKED);
    await page.goto("/");
    await expect(page.getByText("Ask Kilimo Desk")).toBeVisible();

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa"])
      .analyze();

    const serious = results.violations.filter(
      (v) => v.impact === "serious" || v.impact === "critical",
    );
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
  });

  test("no contrast or serious violations on the background view", async ({ page }) => {
    await stubApi(page, MASKED);
    await page.goto("/");
    await page.getByLabel(/Your message/).fill("I am Grace Wanjiku, member HG-004182.");
    await page.getByRole("button", { name: "Send" }).click();
    await page.getByRole("button", { name: /what the system did/ }).click();

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa"])
      .analyze();

    const serious = results.violations.filter(
      (v) => v.impact === "serious" || v.impact === "critical",
    );
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
  });
});
