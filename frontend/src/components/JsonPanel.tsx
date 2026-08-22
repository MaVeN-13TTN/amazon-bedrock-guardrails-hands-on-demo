export function JsonPanel({
  value,
  large,
  label,
}: {
  value: unknown;
  /** Enlarged for a projected room, under Requirement 6.10. */
  large?: boolean;
  label?: string;
}) {
  return (
    <pre
      aria-label={label}
      className={`max-h-80 overflow-auto rounded-lg bg-[#111a16] px-4 py-3.5 font-mono leading-relaxed text-[#cfe0d4] ${
        large ? "text-raw-lg" : "text-raw"
      }`}
    >
      {JSON.stringify(value ?? {}, null, 2)}
    </pre>
  );
}

export function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-3.5 overflow-hidden rounded-xl border border-line bg-white">
      <h2 className="border-b border-line px-4 py-3 text-finding font-bold uppercase tracking-wider text-dim">
        {title}
      </h2>
      {children}
    </section>
  );
}
