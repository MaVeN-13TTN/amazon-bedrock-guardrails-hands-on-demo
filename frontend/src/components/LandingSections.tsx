import type { AppContext } from "@/lib/types";

/**
 * The co-operative as a member would meet it. Every word here arrives from
 * `GET /api/context`, which reads `shared/scenario.json` — the frontend holds no
 * scenario text of its own, so an edit to the bulletin cannot leave this page
 * stating something the co-operative's own document does not.
 */
export function LandingSections({
  ctx,
  ctxError,
}: {
  ctx: AppContext | null;
  ctxError: string | null;
}) {
  if (ctxError) {
    return (
      <div className="space-y-3">
        <p className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-finding text-stop">
          Could not load co-operative information from{" "}
          <span className="font-mono">/api/context</span> — {ctxError}
        </p>
        {/* Marked unavailable rather than filled with substitute content: a
            plausible-looking page built from defaults would be worse than a
            visibly broken one. */}
        {["Who we are", "What we do for members", "Collection points", "Payments"].map((title) => (
          <Section key={title} title={title}>
            <p className="text-finding italic text-dim">
              Unavailable — see the error above.
            </p>
          </Section>
        ))}
      </div>
    );
  }

  if (!ctx) {
    return <p className="text-finding text-dim">Loading co-operative information…</p>;
  }

  const f = ctx.bulletin_facts;

  return (
    <div className="space-y-3">
      {ctx.about_sections.map((s) => (
        <Section key={s.title} title={s.title}>
          <p className="text-finding">{s.body}</p>
        </Section>
      ))}

      <Section title="Collection points">
        <ul className="space-y-1 text-finding">
          <li>
            <strong>Where:</strong> {f.collection_points.join(" and ")}
          </li>
          <li>
            <strong>Open:</strong> {f.collection_opens} to {f.collection_closes}
          </li>
          <li>
            <strong>Days:</strong> {f.collection_days.join(" and ")} only
          </li>
          <li>
            <strong>Bring:</strong> {f.gate_requirement}
          </li>
        </ul>
      </Section>

      <Section title="Payments">
        <p className="text-finding">
          Payment for delivered produce is {f.payment_release} — {f.payment_delay_days} days.{" "}
          {f.payment_note}
        </p>
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-line bg-white px-4 py-3">
      <h3 className="pb-1.5 text-finding font-bold text-ink">{title}</h3>
      {children}
    </section>
  );
}
