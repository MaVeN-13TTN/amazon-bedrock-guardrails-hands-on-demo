import type { PolicyHit } from "@/lib/types";

/**
 * One policy finding, rendered exactly as the response carried it. No mapping
 * table rewords BLOCKED to "blocked" or ANONYMIZED to "masked", so a reader can
 * diff this against the raw assessment of the same stage.
 */
export function HitBadge({ hit }: { hit: PolicyHit }) {
  const tone =
    hit.passed === true
      ? "bg-green-50 text-go border-green-200"
      : hit.action === "ANONYMIZED"
        ? "bg-amber-50 text-warn border-amber-200"
        : "bg-red-50 text-stop border-red-200";

  return (
    <div className={`rounded-md border px-2 py-1 font-mono text-finding leading-snug ${tone}`}>
      <span className="font-semibold">{hit.policy}</span>
      {hit.detail ? <>: {hit.detail}</> : null}
      {hit.action ? <> → {hit.action}</> : null}
      {/* No opacity here: dimming the amber tone took it to 3.32:1 against
          amber-50, under the 4.5:1 floor. Weight carries the de-emphasis
          instead of transparency. */}
      <span className="pl-1 font-normal">({hit.where})</span>
    </div>
  );
}
