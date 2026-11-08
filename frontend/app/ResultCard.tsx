"use client";

import { fmtNum, type AuditResponse } from "./api";
import { AnomalyBanner, ComparisonPanel } from "./ComparisonPanel";
import { LimitBar } from "./LimitBar";
import { Banner, card, ProofSection, Row, telegramText } from "./ui";

// Re-exported for older imports.
export { Banner } from "./ui";

const METER_TYPES: Record<string, string> = {
  multi_dial: "Diales circulares",
  cyclometer: "Rodillos (odómetro)",
  seven_segment: "Display digital",
  needle_gauge: "Manómetro de aguja",
  other: "Otro",
};

export function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  const color = value < 0.7 ? "bg-amber-400" : value < 0.9 ? "bg-slate-300" : "bg-emerald-400";
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs text-slate-400">
        <span>Confianza</span>
        <span className="font-semibold text-slate-100">{pct.toFixed(0)}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-800" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100} aria-label="Confianza">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      {value < 0.7 && <p className="mt-1 text-xs text-amber-300">Confianza baja: revisa la foto (reflejos, ángulo o suciedad).</p>}
    </div>
  );
}

export function VisionDetails({ vision, majority }: { vision: NonNullable<AuditResponse["vision"]>; majority: number }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-slate-400">Votos:</span>
        {Array.from({ length: vision.total_reads }, (_, i) => (
          <span key={i} className={`h-3.5 w-3.5 rounded-full border-2 ${i < vision.votes ? "border-emerald-400 bg-emerald-400" : "border-slate-500"}`} aria-hidden />
        ))}
        <span className="text-slate-200">
          {vision.votes}/{vision.total_reads} lecturas coinciden
        </span>
      </div>
      <dl className="space-y-1.5">
        <Row label="Tipo de medidor">{METER_TYPES[vision.meter_type ?? ""] ?? vision.meter_type ?? "-"}</Row>
        <Row label="Obstrucción">{vision.obstruction_ratio == null ? "-" : `${(vision.obstruction_ratio * 100).toFixed(0)}%`}</Row>
        <Row label="Modelo">
          <code>{vision.model}</code>
        </Row>
      </dl>
      {vision.rationale && (
        <blockquote className="border-l-4 border-emerald-500/60 bg-slate-800/60 px-3 py-2 text-sm italic text-slate-200">{vision.rationale}</blockquote>
      )}
      {vision.reads.length > 0 && (
        <details className="rounded-lg bg-slate-800/50 p-3 text-sm">
          <summary className="cursor-pointer font-medium text-slate-200">Ver las {vision.reads.length} lecturas</summary>
          <ol className="mt-2 space-y-2">
            {vision.reads.map((r, i) => {
              const dissent = r.error != null || r.value !== majority;
              return (
                <li key={i} className={`rounded-md border p-2 ${dissent ? "border-amber-500/50 bg-amber-950/30" : "border-slate-700"}`}>
                  <p className="font-semibold">
                    Lectura {i + 1}: {r.error ? <span className="text-red-300">error</span> : `${r.value ?? "-"} ${r.unit ?? ""}`}
                    {dissent && !r.error && <span className="ml-2 text-xs text-amber-300">(discrepa)</span>}
                  </p>
                  {(r.error || r.rationale) && <p className="mt-1 text-slate-300">{r.error ?? r.rationale}</p>}
                </li>
              );
            })}
          </ol>
        </details>
      )}
    </div>
  );
}

export function ResultCard({ result, onVerify }: { result: AuditResponse; onVerify: () => void }) {
  const { reading, oracle_proof: proof, notification: n, vision, comparison, limit_status } = result;
  const tg = telegramText(n);

  return (
    <div className="space-y-4">
      {comparison?.anomaly && <AnomalyBanner comparison={comparison} notification={n} />}

      <section className={card} aria-label="Lectura">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <p className="text-xs uppercase tracking-wide text-slate-400">Lectura certificada</p>
          {reading.device_id && <span className="rounded bg-slate-800 px-2 py-0.5 font-mono text-xs text-slate-200">{reading.device_id}</span>}
        </div>
        <p className="mt-1 break-words text-5xl font-bold tabular-nums text-emerald-400">
          {fmtNum(reading.value, 4)} <span className="text-2xl text-emerald-300">{reading.unit}</span>
        </p>
        {result.status === "partial_success" && (
          <p className="mt-2 text-xs text-amber-300">Auditoría parcial: alguna etapa (anclaje o notificación) no se completó del todo.</p>
        )}
        {result.compliance && (
          <div className="mt-3">
            {result.compliance.is_breach ? (
              <div className="rounded-lg border-2 border-red-500 bg-red-950/70 p-3.5 text-sm text-red-200">
                <div className="flex items-center justify-between font-bold text-red-100">
                  <span className="flex items-center gap-1.5">
                    Umbral mensual excedido (+{result.compliance.excess_percentage}%)
                  </span>
                  <span className="rounded bg-red-500 px-2 py-0.5 text-xs uppercase font-black text-white">Incumplimiento</span>
                </div>
                <p className="mt-1 text-xs text-red-300">
                  El consumo calculado ({result.compliance.consumption} {reading.unit}) superó el umbral de {result.compliance.threshold} {reading.unit}.
                  {result.oracle_proof.is_simulated
                    ? "Infracción registrada; el anclaje fue simulado (no está en Solana)."
                    : <>Infracción anclada en Solana con tag <code>:EXCEEDED</code>.</>}
                </p>
                <div className="mt-2.5 h-2 overflow-hidden rounded-full bg-slate-900">
                  <div className="h-full bg-red-500" style={{ width: "100%" }} />
                </div>
              </div>
            ) : (
              <div className="rounded-lg border border-emerald-500/60 bg-emerald-950/60 p-3.5 text-sm text-emerald-200">
                <div className="flex items-center justify-between font-bold text-emerald-100">
                  <span className="flex items-center gap-1.5">
                    Cumplimiento ESG conforme
                  </span>
                  <span className="rounded bg-emerald-500/20 px-2 py-0.5 text-xs uppercase font-bold text-emerald-300">En Regla</span>
                </div>
                <p className="mt-1 text-xs text-emerald-300">
                  Consumo ({result.compliance.consumption} {reading.unit}) dentro del umbral de {result.compliance.threshold} {reading.unit}.
                </p>
                <div className="mt-2.5 h-2 overflow-hidden rounded-full bg-slate-900">
                  <div
                    className="h-full bg-emerald-400"
                    style={{ width: `${Math.min(100, Math.round((result.compliance.consumption / result.compliance.threshold) * 100))}%` }}
                  />
                </div>
              </div>
            )}
          </div>
        )}
        <div className="mt-4">
          <ConfidenceBar value={reading.confidence} />
        </div>
        {vision?.is_mock && (
          <div className="mt-4">
            <Banner tone="amber">Lectura simulada: el servidor no tiene clave de IA</Banner>
          </div>
        )}
        {vision && !vision.is_mock && (
          <div className="mt-4">
            <VisionDetails vision={vision} majority={reading.value} />
          </div>
        )}
      </section>

      {comparison ? (
        <ComparisonPanel comparison={comparison} reading={reading} />
      ) : (
        <Banner tone="slate">
          <p className="font-semibold text-slate-200">Sin lectura anterior para comparar</p>
          <p className="mt-1">
            {reading.device_id
              ? "Es la primera lectura registrada de este medidor. La próxima se comparará automáticamente con esta."
              : "Escribe un ID de medidor para comparar automáticamente con su última lectura."}
          </p>
        </Banner>
      )}

      {limit_status && (
        <section className={card} aria-label="Límite de consumo">
          <h2 className="mb-3 text-lg font-semibold">Límite de consumo</h2>
          <LimitBar status={limit_status} />
        </section>
      )}

      <ProofSection
        proof={proof}
        onVerify={onVerify}
        extraRows={
          <>
            <Row label="Tiempo total">{(result.execution_time_ms / 1000).toFixed(1)} s</Row>
            <Row label="Telegram">
              <span className={tg.ok ? "" : "text-red-300"}>{tg.text}</span>
            </Row>
          </>
        }
      />
    </div>
  );
}
