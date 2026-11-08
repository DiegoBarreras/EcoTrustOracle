export type Stage = "idle" | "vision" | "anchor" | "notify" | "done" | "error";

const STEPS = [
  { key: "photo", title: "Foto", sub: "Medidor o sensor", active: "Enviando..." },
  { key: "vision", title: "IA x3", sub: "3 lecturas y votación", active: "IA leyendo" },
  { key: "anchor", title: "Solana", sub: "Huella SHA-256 en Memo", active: "Anclando" },
  { key: "notify", title: "Telegram", sub: "Certificado ESG", active: "Notificando" },
] as const;

const ORDER: Record<Stage, number> = { idle: -1, vision: 1, anchor: 2, notify: 3, done: 4, error: -1 };

type Status = "pending" | "active" | "done" | "failed" | "skipped";

function Icon({ status, n }: { status: Status; n: number }) {
  const base = "flex h-9 w-9 shrink-0 items-center justify-center rounded-full border-2 text-sm font-bold";
  if (status === "done")
    return (
      <span className={`${base} border-emerald-400 bg-emerald-400 text-slate-950`} aria-hidden>
        <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="3">
          <path d="M4 10l4 4 8-8" />
        </svg>
      </span>
    );
  if (status === "failed")
    return (
      <span className={`${base} border-red-400 bg-red-500 text-white`} aria-hidden>
        <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="3">
          <path d="M5 5l10 10M15 5L5 15" />
        </svg>
      </span>
    );
  if (status === "active")
    return (
      <span className={`${base} border-emerald-400 text-emerald-300`} aria-hidden>
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-emerald-400 border-t-transparent" />
      </span>
    );
  return (
    <span className={`${base} ${status === "skipped" ? "border-dashed border-slate-600 text-slate-500" : "border-slate-600 text-slate-400"}`} aria-hidden>
      {n}
    </span>
  );
}

export function Pipeline({ stage, failedAt, sensor, elapsed }: { stage: Stage; failedAt: number | null; sensor: boolean; elapsed: number }) {
  const current = ORDER[stage];
  const running = stage === "vision" || stage === "anchor" || stage === "notify";
  return (
    <section aria-label="Proceso de auditoría" className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <ol className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {STEPS.map((s, i) => {
          let status: Status = "pending";
          if (sensor && i === 1) status = "skipped";
          else if (stage === "error" && failedAt !== null) status = i < failedAt ? "done" : i === failedAt ? "failed" : "pending";
          else if (stage === "done" || i < current) status = "done";
          else if (i === current) status = "active";
          const tone =
            status === "active" ? "text-emerald-300" : status === "done" ? "text-slate-100" : status === "failed" ? "text-red-300" : "text-slate-400";
          return (
            <li key={s.key} className="flex items-center gap-3">
              <Icon status={status} n={i + 1} />
              <div className="min-w-0">
                <p className={`font-semibold ${tone}`}>{s.title}</p>
                <p className="text-xs text-slate-400">
                  {status === "skipped"
                    ? "No aplica a sensores"
                    : status === "active"
                      ? `${s.active}... ${elapsed} s`
                      : status === "failed"
                        ? "Falló aquí"
                        : s.sub}
                </p>
              </div>
            </li>
          );
        })}
      </ol>
      {running && (
        <p className="mt-3 text-xs text-slate-400">
          Progreso estimado (~): el servidor procesa todo en una sola petición. Tiempo transcurrido: {elapsed} s
        </p>
      )}
    </section>
  );
}
