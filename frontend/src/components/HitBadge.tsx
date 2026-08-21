import type { PolicyHit } from "@/lib/types";

/** One policy finding. Masking is amber, blocking is red, a passed score is green. */
export function HitBadge({ hit }: { hit: PolicyHit }) {
  const tone =
    hit.passed === true
      ? "bg-green-50 text-go border-green-200"
      : hit.action === "ANONYMIZED"
        ? "bg-amber-50 text-warn border-amber-200"
        : "bg-red-50 text-stop border-red-200";

  return (
    <div className={`rounded-md border px-2 py-1 font-mono text-[11.5px] leading-snug ${tone}`}>
      <span className="font-semibold">{hit.policy}</span>
      {hit.detail ? <>: {hit.detail}</> : null}
      {hit.action ? <> → {hit.action}</> : null}
    </div>
  );
}
