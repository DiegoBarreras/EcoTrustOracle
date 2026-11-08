import type { ReactNode } from "react";
import { ANOMALY_LABEL, fmtDate, fmtElapsed, fmtNum, fmtSigned, short, solscanTx, type NotificationResult, type Reading, type ReadingComparison } from "./api";
import { card, WarnIcon } from "./ui";

const ORIGIN: Record<string, string> = { history: "historial", client: "ingresada" };

/** Top-of-result alert: the suspicious reading was still recorded and anchored as evidence. */
export function AnomalyBanner({
  comparison: c,
  notification: n,
  simulated = false,
}: {
  comparison: ReadingComparison;
  notification: NotificationResult;
  simulated?: boolean;
}) {
  if (!c.anomaly) return null;
  const severe = c.anomaly === "reading_below_previous";
  const tg = !n.sent
    ? `no se pudo enviar la alerta por Telegram (${n.error || "sin detalle"}).`
    : n.is_mock
      ? "la alerta por Telegram se simuló (no hay bot configurado)."
      : "se envió la alerta por Telegram.";
  return (
    <div
      role="alert"
      className={`rounded-xl border-2 p-5 ${severe ? "border-red-500 bg-red-950/70 text-red-100" : "border-amber-500 bg-amber-950/70 text-amber-100"}`}
    >
      <div className="flex items-start gap-3">
        <WarnIcon className={`mt-0.5 h-7 w-7 shrink-0 ${severe ? "text-red-300" : "text-amber-300"}`} />
        <div className="min-w-0">
          <p className="text-lg font-bold">Posible alteración del medidor</p>
          <p className="mt-0.5 text-xs font-semibold uppercase tracking-wide opacity-80">{ANOMALY_LABEL[c.anomaly] ?? c.anomaly}</p>
          {c.anomaly_message && <p className="mt-2 text-sm">{c.anomaly_message}</p>}
          <p className="mt-2 text-sm">
            {simulated
              ? "La lectura se registró como evidencia; el anclaje fue SIMULADO (no está en Solana); "
              : "La lectura se registró y se ancló en Solana como evidencia; "}
            {tg}
          </p>
        </div>
      </div>
    </div>
  );
}

function Column({ title, value, unit, timestamp, extra, accent }: { title: string; value: number; unit: string; timestamp: string; extra?: ReactNode; accent?: boolean }) {
  return (
    <div className={`min-w-0 rounded-lg border p-3 ${accent ? "border-emerald-500/40 bg-emerald-950/20" : "border-slate-700 bg-slate-950/50"}`}>
      <p className="text-xs uppercase tracking-wide text-slate-400">{title}</p>
      <p className={`mt-1 break-words text-2xl font-bold tabular-nums ${accent ? "text-emerald-300" : "text-slate-100"}`}>
        {fmtNum(value, 4)} <span className="text-base font-semibold text-slate-300">{unit}</span>
      </p>
      <p className="mt-1 text-xs text-slate-400">{fmtDate(timestamp)}</p>
      {extra && <div className="mt-1 text-xs text-slate-400">{extra}</div>}
    </div>
  );
}

export function ComparisonPanel({ comparison: c, reading }: { comparison: ReadingComparison; reading: Reading }) {
  const p = c.previous;
  const negative = c.consumption < 0;
  const deltaTone = c.anomaly ? (negative ? "text-red-400" : "text-amber-300") : "text-emerald-400";
  const ratio = c.daily_rate != null && c.daily_rate >= 0 && c.typical_daily_rate != null && c.typical_daily_rate > 0 ? c.daily_rate / c.typical_daily_rate : null;
  const ratioTone = ratio == null ? "" : ratio >= 3 ? "text-red-300" : ratio >= 1.5 ? "text-amber-300" : "text-emerald-300";

  return (
    <section className={card} aria-label="Comparación con la lectura anterior">
      <h2 className="text-lg font-semibold">Comparación con la lectura anterior</h2>
      <div className="mt-3 grid grid-cols-2 gap-3">
        <Column
          title="Anterior"
          value={p.value}
          unit={p.unit}
          timestamp={p.timestamp}
          extra={
            <>
              <span className="rounded bg-slate-800 px-1.5 py-0.5 text-slate-300">{ORIGIN[p.origin] ?? p.origin}</span>
              {p.tx_signature && (
                <span className="ml-1">
                  {p.is_simulated ? (
                    <span className="text-amber-300">SIMULADO</span>
                  ) : (
                    <a href={solscanTx(p.tx_signature)} target="_blank" rel="noreferrer" className="text-emerald-300 underline hover:text-emerald-200" title={p.tx_signature}>
                      tx {short(p.tx_signature, 4)}
                    </a>
                  )}
                </span>
              )}
            </>
          }
        />
        <Column title="Actual" value={reading.value} unit={reading.unit} timestamp={reading.timestamp} accent />
      </div>

      <div className="mt-4 rounded-lg bg-slate-950/60 p-4 text-center">
        <p className="text-xs uppercase tracking-wide text-slate-400">Consumo desde la lectura anterior</p>
        <p className={`mt-1 text-4xl font-black tabular-nums ${deltaTone}`}>
          {fmtSigned(c.consumption, 4)} <span className="text-xl font-bold">{reading.unit}</span>
        </p>
        {negative && <p className="mt-1 text-xs text-red-300">El contador retrocedió: un medidor acumulativo no debería bajar.</p>}
      </div>

      <dl className="mt-4 grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-slate-800 p-3">
          <dt className="text-xs uppercase tracking-wide text-slate-400">Tiempo transcurrido</dt>
          <dd className="mt-1 text-lg font-semibold text-slate-100">{fmtElapsed(c.elapsed_hours)}</dd>
        </div>
        <div className="rounded-lg border border-slate-800 p-3">
          <dt className="text-xs uppercase tracking-wide text-slate-400">Ritmo diario</dt>
          <dd className="mt-1 text-lg font-semibold text-slate-100">
            {c.daily_rate == null ? "-" : `${fmtNum(c.daily_rate)} ${reading.unit}/día`}
          </dd>
        </div>
        <div className="rounded-lg border border-slate-800 p-3">
          <dt className="text-xs uppercase tracking-wide text-slate-400">Ritmo habitual</dt>
          <dd className="mt-1 text-lg font-semibold text-slate-100">
            {c.typical_daily_rate == null ? <span className="text-sm font-normal text-slate-400">Sin historial suficiente</span> : `${fmtNum(c.typical_daily_rate)} ${reading.unit}/día`}
          </dd>
        </div>
      </dl>
      {ratio != null && (
        <p className={`mt-3 text-sm font-semibold ${ratioTone}`}>
          {fmtNum(ratio, 1)} veces lo habitual
          <span className="ml-1 font-normal text-slate-400">(ritmo de este período frente a la mediana del historial)</span>
        </p>
      )}
    </section>
  );
}
