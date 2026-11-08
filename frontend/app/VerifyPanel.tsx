"use client";

import { useState, type FormEvent } from "react";
import { apiPostJson, errorText, short, type VerifyResult } from "./api";
import { Banner, field, labelCls, primaryBtn } from "./ui";

export type VerifyMode = "reading" | "payload";

const CHECKS: [keyof VerifyResult["checks"], string][] = [
  ["tx_found", "Transacción encontrada"],
  ["tx_succeeded", "Transacción exitosa"],
  ["memo_found", "Memo EcoTrust presente"],
  ["hash_matches", "Hash recalculado coincide con el Memo"],
  ["signer_matches", "Firmante es el oráculo esperado"],
];

const MODES: [VerifyMode, string][] = [
  ["reading", "Lectura"],
  ["payload", "JSON anclado"],
];

export function VerifyPanel({
  mode,
  onMode,
  readingJson,
  payloadJson,
  txSig,
  onReadingJson,
  onPayloadJson,
  onTxSig,
}: {
  mode: VerifyMode;
  onMode: (m: VerifyMode) => void;
  readingJson: string;
  payloadJson: string;
  txSig: string;
  onReadingJson: (v: string) => void;
  onPayloadJson: (v: string) => void;
  onTxSig: (v: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<VerifyResult | null>(null);

  function switchMode(m: VerifyMode) {
    onMode(m);
    setError(null);
    setRes(null);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setRes(null);
    const tx = txSig.trim();
    if (tx.length < 32) {
      setError("La firma de la transacción parece incompleta (mínimo 32 caracteres).");
      return;
    }
    let path: string;
    let body: unknown;
    if (mode === "reading") {
      let reading: unknown;
      try {
        reading = JSON.parse(readingJson);
      } catch {
        setError("El JSON de la lectura no es válido.");
        return;
      }
      path = "/api/v1/verify";
      body = { reading, tx_signature: tx };
    } else {
      // Sent verbatim: the hash covers the exact string, so it must not be reformatted.
      if (payloadJson.trim().length < 2) {
        setError("Pega el JSON exacto que se ancló.");
        return;
      }
      path = "/api/v1/verify-payload";
      body = { canonical_json: payloadJson, tx_signature: tx };
    }
    setBusy(true);
    try {
      setRes(await apiPostJson<VerifyResult>(path, body));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={submit} className="space-y-3 rounded-xl border border-slate-800 bg-slate-900 p-5">
        <div className="flex gap-1 rounded-lg bg-slate-950 p-1" role="group" aria-label="Tipo de prueba">
          {MODES.map(([m, label]) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              onClick={() => switchMode(m)}
              className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 ${
                mode === m ? "bg-slate-700 text-emerald-300" : "text-slate-300 hover:bg-slate-800"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <p className="text-sm text-slate-300">
          {mode === "reading"
            ? "Cualquiera puede comprobar una prueba: recalculamos el SHA-256 de la lectura y lo comparamos con el Memo de la transacción en Solana."
            : "Para comprobantes de recibos u otros datos anclados: se hashea el JSON tal cual (sin reformatear) y se compara con el Memo en Solana."}
        </p>
        {mode === "reading" ? (
          <div>
            <label htmlFor="v-reading" className={labelCls}>JSON de la lectura</label>
            <textarea id="v-reading" required rows={7} value={readingJson} onChange={(e) => onReadingJson(e.target.value)} className={`${field} font-mono`} spellCheck={false} />
          </div>
        ) : (
          <div>
            <label htmlFor="v-payload" className={labelCls}>JSON canónico anclado</label>
            <textarea
              id="v-payload"
              required
              rows={9}
              value={payloadJson}
              onChange={(e) => onPayloadJson(e.target.value)}
              className={`${field} font-mono text-xs`}
              spellCheck={false}
              aria-describedby="v-payload-hint"
            />
            <p id="v-payload-hint" className="mt-1 text-xs text-slate-400">
              Cualquier cambio (incluso un espacio) produce otro hash y la verificación fallará.
            </p>
          </div>
        )}
        <div>
          <label htmlFor="v-tx" className={labelCls}>Firma de la transacción</label>
          <input id="v-tx" required value={txSig} onChange={(e) => onTxSig(e.target.value)} className={`${field} font-mono`} spellCheck={false} autoComplete="off" />
        </div>
        <button type="submit" disabled={busy} className={`w-full py-2.5 text-base ${primaryBtn}`}>
          {busy ? "Verificando..." : "Verificar en Solana"}
        </button>
      </form>

      {error && <Banner tone="red">{error}</Banner>}

      {res && (
        <section className="space-y-3 rounded-xl border border-slate-800 bg-slate-900 p-5" aria-live="polite">
          <p className={`text-center text-4xl font-black tracking-wide ${res.valid ? "text-emerald-400" : "text-red-400"}`}>{res.valid ? "VÁLIDO" : "NO VÁLIDO"}</p>
          {res.detail && <p className="text-center text-sm text-slate-300">{res.detail}</p>}
          <ul className="divide-y divide-slate-800">
            {CHECKS.map(([k, label]) => {
              const v = res.checks?.[k];
              return (
                <li key={k} className="flex items-center justify-between py-2 text-sm">
                  <span>{label}</span>
                  <span
                    className={`rounded px-2 py-0.5 text-xs font-bold ${v === undefined ? "bg-slate-800 text-slate-400" : v ? "bg-emerald-950 text-emerald-300" : "bg-red-950 text-red-300"}`}
                  >
                    {v === undefined ? "N/A" : v ? "OK" : "FALLA"}
                  </span>
                </li>
              );
            })}
          </ul>
          <dl className="space-y-1 text-sm">
            <div><dt className="inline text-slate-400">Hash calculado: </dt><dd className="inline break-all font-mono">{res.computed_hash}</dd></div>
            <div><dt className="inline text-slate-400">Hash en Memo: </dt><dd className="inline break-all font-mono">{res.memo_hash ?? "-"}</dd></div>
            <div><dt className="inline text-slate-400">Firmante: </dt><dd className="inline font-mono" title={res.signer ?? undefined}>{short(res.signer, 8)}</dd></div>
            <div><dt className="inline text-slate-400">Esperado: </dt><dd className="inline font-mono" title={res.expected_signer ?? undefined}>{short(res.expected_signer, 8)}</dd></div>
          </dl>
        </section>
      )}
    </div>
  );
}
