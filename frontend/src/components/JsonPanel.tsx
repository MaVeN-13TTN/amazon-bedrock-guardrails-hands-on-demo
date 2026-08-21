export function JsonPanel({ value }: { value: unknown }) {
  return (
    <pre className="max-h-80 overflow-auto rounded-b-xl bg-[#111a16] px-4 py-3.5 font-mono text-[11.5px] leading-relaxed text-[#cfe0d4]">
      {JSON.stringify(value ?? {}, null, 2)}
    </pre>
  );
}

export function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-3.5 overflow-hidden rounded-xl border border-line bg-white">
      <h2 className="border-b border-line px-4 py-3 text-[11.5px] font-bold uppercase tracking-wider text-dim">
        {title}
      </h2>
      {children}
    </section>
  );
}
