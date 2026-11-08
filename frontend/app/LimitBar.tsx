import { fmtDate, fmtNum, PERIOD_CURRENT, PERIOD_LABEL, type LimitStatus } from "./api";

const TONE = {
  ok: { bar: "bg-emerald-400", text: "text-emerald-300", badge: "border-emerald-500/60 bg-emerald-950/60 text-emerald-200", label: "Dentro del límite" },
  warning: { bar: "bg-amber-400", text: "text-amber-300", badge: "border-amber-500/60 bg-amber-950/60 text-amber-200", label: "Cerca del límite" },
  exceeded: { bar: "bg-red-500", text: "text-red-300", badge: "border-red-500/60 bg-red-950/60 text-red-200", label: "Límite superado" },
} as const;

export function LimitBar({ status: s }: { status: LimitStatus }) {
  const t = TONE[s.status] ?? TONE.ok;
  const pct = Number.isFinite(s.percent) ? s.percent : 0;
  const width = Math.max(0, Math.min(100, pct));
  const projPct = s.projected != null && s.limit > 0 ? (s.projected / s.limit) * 100 : null;
  const projOver = projPct != null && projPct > 100;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold text-slate-100">
          Límite {PERIOD_LABEL[s.period]?.toLowerCase() ?? s.period}: {fmtNum(s.limit)} {s.unit}
        </p>
        <span className={`rounded-full border px-2.5 py-0.5 text-xs font-bold ${t.badge}`}>{t.label}</span>
      </div>
      <div className="relative pt-1">
        <div
          className="h-3 overflow-hidden rounded-full bg-slate-800"
          role="progressbar"
          aria-valuenow={Math.round(pct)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`Consumo ${PERIOD_CURRENT[s.period] ?? ""}: ${fmtNum(pct, 0)}% del límite`}
        >
          <div className={`h-full ${t.bar} transition-[width]`} style={{ width: `${width}%` }} />
        </div>
        {projPct != null && (
          <div
            className="absolute top-0 h-5 w-0.5 bg-slate-100"
            style={{ left: `calc(${Math.min(100, Math.max(0, projPct))}% - 1px)` }}
            title={`Proyección al cierre del período: ${fmtNum(s.projected, 1)} ${s.unit}`}
            aria-hidden
          />
        )}
      </div>
      <div className="flex flex-wrap justify-between gap-x-4 gap-y-1 text-sm">
        <span className="text-slate-200">
          Usado {PERIOD_CURRENT[s.period] ?? ""}: <strong className={t.text}>{fmtNum(s.used)}</strong> de {fmtNum(s.limit)} {s.unit}
        </span>
        <span className={`font-semibold tabular-nums ${t.text}`}>{fmtNum(pct, 1)}%</span>
      </div>
      {s.projected != null && (
        <p className={`text-xs ${projOver ? "text-amber-300" : "text-slate-400"}`}>
          <span className="mr-1 inline-block h-2.5 w-0.5 bg-slate-100 align-middle" aria-hidden />
          Proyección al cierre: {fmtNum(s.projected, 1)} {s.unit}
          {projOver ? ` (superaría el límite en ${fmtNum((s.projected ?? 0) - s.limit, 1)} ${s.unit})` : ""}
        </p>
      )}
      <p className="text-xs text-slate-500">Período desde {fmtDate(s.period_start)}</p>
    </div>
  );
}
