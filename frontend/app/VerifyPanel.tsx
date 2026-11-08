"use client";

import { useState, type FormEvent } from "react";
import { apiPost, ApiError, short, type VerifyResult } from "./api";
import { Banner } from "./ResultCard";

const CHECKS: [keyof VerifyResult["checks"], string][] = [
  ["tx_found", "Transacción encontrada"],
  ["tx_succeeded", "Transacción exitosa"],
  ["memo_found", "Memo EcoTrust presente"],
  ["hash_matches", "Hash recalculado coincide con el Memo"],
  ["signer_matches", "Firmante es el oráculo esperado"],
];

const field = "w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-emerald-400 focus:outline-none";

export function VerifyPanel({ readingJson, txSig, onReadingJson, onTxSig }: {
  readingJson: string;
  txSig: string;
  onReadingJson: (v: string) => void;
  onTxSig: (v: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<VerifyResult | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setRes(null);
    let reading: unknown;
    try {
      reading = JSON.parse(readingJson);
    } catch {
      setError("El JSON de la lectura no es válido.");
      return;
    }
    setBusy(true);
    try {
      setRes(
        await apiPost<VerifyResult>("/api/v1/verify", {
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reading, tx_signature: txSig.trim() }),
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError || err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={submit} className="space-y-3 rounded-xl border border-slate-800 bg-slate-900 p-5">
        <p className="text-sm text-slate-300">
          Cualquiera puede comprobar una prueba: recalculamos el SHA-256 de la lectura y lo comparamos con el Memo de la transacción en Solana.
        </p>
        <div>
          <label htmlFor="v-reading" className="mb-1 block text-sm font-medium text-slate-200">JSON de la lectura</label>
          <textarea id="v-reading" required rows={7} value={readingJson} onChange={(e) => onReadingJson(e.target.value)} className={`${field} font-mono`} />
        </div>
        <div>
          <label htmlFor="v-tx" className="mb-1 block text-sm font-medium text-slate-200">Firma de la transacción</label>
          <input id="v-tx" required value={txSig} onChange={(e) => onTxSig(e.target.value)} className={`${field} font-mono`} />
        </div>
        <button type="submit" disabled={busy} className="w-full rounded-md bg-emerald-500 px-4 py-2.5 font-semibold text-slate-950 hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-300">
          {busy ? "Verificando..." : "Verificar en Solana"}
        </button>
      </form>

      {error && <Banner tone="red">{error}</Banner>}

      {res && (
        <section className="space-y-3 rounded-xl border border-slate-800 bg-slate-900 p-5" aria-live="polite">
          <p className={`text-center text-4xl font-black tracking-wide ${res.valid ? "text-emerald-400" : "text-red-400"}`}>
            {res.valid ? "VÁLIDO" : "NO VÁLIDO"}
          </p>
          {res.detail && <p className="text-center text-sm text-slate-300">{res.detail}</p>}
          <ul className="divide-y divide-slate-800">
            {CHECKS.map(([k, label]) => (
              <li key={k} className="flex items-center justify-between py-2 text-sm">
                <span>{label}</span>
                <span className={`rounded px-2 py-0.5 text-xs font-bold ${res.checks[k] ? "bg-emerald-950 text-emerald-300" : "bg-red-950 text-red-300"}`}>
                  {res.checks[k] ? "OK" : "FALLA"}
                </span>
              </li>
            ))}
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
