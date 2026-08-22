/**
 * The persistent notice. Sticky, so it is visible at every scroll position.
 *
 * The replay indicator lives here rather than inside the Chat_Window on purpose:
 * a "recorded" label attached to an assistant turn would show the audience
 * something no real member would ever see, which would undo the very thing the
 * member view exists to demonstrate. The audience is still told — just outside
 * the conversation.
 */
export function Disclosure({ replaying }: { replaying?: { captured_utc: string; region: string } | null }) {
  return (
    <div className="sticky top-0 z-20 border-b border-amber-200 bg-amber-50 px-4 py-2">
      <p className="text-finding text-ink">
        <strong>Demonstration only.</strong> Highland Growers Co-operative, Kilimo Desk, Project
        Tumaini, Batch Ledger v2 and Extension Bulletin 14 are fictional — the co-operative does not
        exist. The API serving this page performs no authentication.{" "}
        <strong>Do not enter real personal information.</strong>
      </p>
      {replaying ? (
        <p className="pt-1 text-finding font-semibold text-warn">
          Replaying a recorded result — captured {replaying.captured_utc} in {replaying.region}. No
          live AWS call was made for this answer.
        </p>
      ) : null}
    </div>
  );
}
