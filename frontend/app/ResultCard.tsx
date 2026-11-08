"use client";

import { useState, type ReactNode } from "react";
import { short, type AuditResponse } from "./api";

const METER_TYPES: Record<string, string> = {
  multi_dial: "Diales circulares",
  cyclometer: "Rodillos (odómetro)",
  seven_segment: "Display digital",
  needle_gauge: "Manómetro de aguja",
  other: "Otro",
};

const card = "rounded-xl border border-slate-800 bg-slate-900 p-5";

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() =>
        navigator.clipboard
          .writeText(text)
          .then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          })
          .catch(() => setCopied(false))
      }
      className="rounded-md border border-slate-600 px-2 py-0.5 text-xs text-slate-200 hover:border-emerald-400 hover:text-emerald-300"
    >
      {copied ? "Copiado" : "Copiar"}
    </button>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 sm:flex-row sm:items-baseline sm:gap-3">
      <dt className="w-36 shrink-0 text-xs uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="min-w-0 break-all text-sm text-slate-100">{children}</dd>
    </div>
  );
}

export function Banner({ tone, children }: { tone: "amber" | "red"; children: ReactNode }) {
  const c = tone === "amber" ? "border-amber-500/50 bg-amber-950/60 text-amber-200" : "border-red-500/50 bg-red-950/60 text-red-200";
  return <div className={`rounded-lg border p-3 text-sm ${c}`}>{children}</div>;
}

function ConfidenceBar({ value }: { value: number }) {
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

export function ResultCard({ result, onVerify }: { result: AuditResponse; onVerify: () => void }) {
  const { reading, oracle_proof: proof, notification: n, vision } = result;
  const aiReal = vision && !vision.is_mock;
  const majority = reading.value;
  const telegram = n.sent ? (n.is_mock ? "simulado" : "enviado") : `fallo: ${n.error || "sin detalle"}`;

  return (
    <div className="space-y-4">
      <section className={card} aria-label="Lectura">
        <p className="text-xs uppercase tracking-wide text-slate-400">Lectura certificada</p>
        <p className="mt-1 text-5xl font-bold tabular-nums text-emerald-400">
          {reading.value} <span className="text-2xl text-emerald-300">{reading.unit}</span>
        </p>
        {result.consumption != null && (
          <p className="mt-2 text-sm text-slate-200">
            Consumo desde la lectura anterior: <strong>{result.consumption} {reading.unit}</strong>
          </p>
        )}
        {result.compliance && (
          <div className="mt-3">
            {result.compliance.is_breach ? (
              <div className="rounded-lg border-2 border-red-500 bg-red-950/70 p-3.5 text-sm text-red-200">
                <div className="flex items-center justify-between font-bold text-red-100">
                  <span className="flex items-center gap-1.5">
                    🚨 Umbral mensual excedido (+{result.compliance.excess_percentage}%)
                  </span>
                  <span className="rounded bg-red-500 px-2 py-0.5 text-xs uppercase font-black text-white">Incumplimiento</span>
                </div>
                <p className="mt-1 text-xs text-red-300">
                  El consumo calculado ({result.compliance.consumption} {reading.unit}) superó el umbral de {result.compliance.threshold} {reading.unit}.
                  Infracción anclada en Solana con tag <code>:EXCEEDED</code>.
                </p>
                <div className="mt-2.5 h-2 overflow-hidden rounded-full bg-slate-900">
                  <div className="h-full bg-red-500" style={{ width: "100%" }} />
                </div>
              </div>
            ) : (
              <div className="rounded-lg border border-emerald-500/60 bg-emerald-950/60 p-3.5 text-sm text-emerald-200">
                <div className="flex items-center justify-between font-bold text-emerald-100">
                  <span className="flex items-center gap-1.5">
                    🟢 Cumplimiento ESG Conforme
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

        {aiReal && (
          <div className="mt-4 space-y-3">
            <div className="flex items-center gap-2 text-sm">
              <span className="text-slate-400">Votos:</span>
              {Array.from({ length: vision.total_reads }, (_, i) => (
                <span
                  key={i}
                  className={`h-3.5 w-3.5 rounded-full border-2 ${i < vision.votes ? "border-emerald-400 bg-emerald-400" : "border-slate-500"}`}
                  aria-hidden
                />
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
              <blockquote className="border-l-4 border-emerald-500/60 bg-slate-800/60 px-3 py-2 text-sm italic text-slate-200">
                {vision.rationale}
              </blockquote>
            )}
            {vision.reads.length > 0 && (
              <details className="rounded-lg bg-slate-800/50 p-3 text-sm">
                <summary className="cursor-pointer font-medium text-slate-200">Ver las 3 lecturas</summary>
                <ol className="mt-2 space-y-2">
                  {vision.reads.map((r, i) => {
                    const dissent = r.error != null || r.value !== majority;
                    return (
                      <li key={i} className={`rounded-md border p-2 ${dissent ? "border-amber-500/50 bg-amber-950/30" : "border-slate-700"}`}>
                        <p className="font-semibold">
                          Lectura {i + 1}:{" "}
                          {r.error ? <span className="text-red-300">error</span> : `${r.value ?? "-"} ${r.unit ?? ""}`}
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
        )}
      </section>

      <section className={card} aria-label="Prueba en Solana">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold">Prueba en Solana</h2>
          {proof.is_simulated ? (
            <span className="rounded-full border border-amber-500/60 bg-amber-950/60 px-3 py-1 text-xs font-bold text-amber-200">
              SIMULADO - no anclado en Solana
            </span>
          ) : (
            <span className="rounded-full border border-emerald-500/60 bg-emerald-950/60 px-3 py-1 text-xs font-bold text-emerald-200">
              Anclado en {proof.network}
            </span>
          )}
        </div>
        <dl className="mt-3 space-y-1.5">
          <Row label="SHA-256">
            <span className="inline-flex flex-wrap items-center gap-2">
              <code title={proof.data_hash}>{short(proof.data_hash, 10)}</code>
              <CopyButton text={proof.data_hash} />
            </span>
          </Row>
          <Row label="Memo">
            <code>{proof.memo_payload}</code>
          </Row>
          <Row label="Transacción">
            <code title={proof.tx_signature}>{short(proof.tx_signature, 8)}</code>
          </Row>
          <Row label="Slot">{proof.slot ?? "-"}</Row>
          <Row label="Firmante">
            <code title={proof.signer ?? undefined}>{short(proof.signer)}</code>
          </Row>
          <Row label="Tiempo total">{(result.execution_time_ms / 1000).toFixed(1)} s</Row>
          <Row label="Telegram">
            <span className={n.sent ? "" : "text-red-300"}>{telegram}</span>
          </Row>
        </dl>
        {proof.canonical_json && (
          <details className="mt-3 rounded-lg bg-slate-800/50 p-3 text-sm">
            <summary className="cursor-pointer font-medium text-slate-200">Ver JSON exacto hasheado</summary>
            <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-all text-xs text-slate-300">{proof.canonical_json}</pre>
          </details>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          {!proof.is_simulated && proof.solscan_url && (
            <a
              href={proof.solscan_url}
              target="_blank"
              rel="noreferrer"
              className="rounded-md bg-emerald-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-emerald-400"
            >
              Ver en Solscan Devnet
            </a>
          )}
          <button
            type="button"
            onClick={onVerify}
            className="rounded-md border border-emerald-500 px-4 py-2 text-sm font-semibold text-emerald-300 hover:bg-emerald-500/10"
          >
            Verificar esta prueba
          </button>
        </div>
      </section>
    </div>
  );
}
