"use client";

import { useEffect, useState, type InputHTMLAttributes, type ReactNode } from "react";
import { short, type NotificationResult, type OracleProof } from "./api";

export const card = "rounded-xl border border-slate-800 bg-slate-900 p-5";
export const field =
  "w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-emerald-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400/40";
export const labelCls = "mb-1 block text-sm font-medium text-slate-200";
export const primaryBtn =
  "rounded-md bg-emerald-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-emerald-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-300";
export const secondaryBtn =
  "rounded-md border border-emerald-500 px-4 py-2 text-sm font-semibold text-emerald-300 hover:bg-emerald-500/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300 disabled:cursor-not-allowed disabled:border-slate-700 disabled:text-slate-500";

export function Field({ id, label, hint, ...props }: { id: string; label: ReactNode; hint?: ReactNode } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div>
      <label htmlFor={id} className={labelCls}>{label}</label>
      <input id={id} name={id} className={field} aria-describedby={hint ? `${id}-hint` : undefined} {...props} />
      {hint && <p id={`${id}-hint`} className="mt-1 text-xs text-slate-400">{hint}</p>}
    </div>
  );
}

export function CopyButton({ text, label = "Copiar" }: { text: string; label?: string }) {
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
      className="rounded-md border border-slate-600 px-2 py-0.5 text-xs text-slate-200 hover:border-emerald-400 hover:text-emerald-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400"
    >
      {copied ? "Copiado" : label}
    </button>
  );
}

export function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 sm:flex-row sm:items-baseline sm:gap-3">
      <dt className="w-36 shrink-0 text-xs uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="min-w-0 break-all text-sm text-slate-100">{children}</dd>
    </div>
  );
}

export function Banner({ tone, children }: { tone: "amber" | "red" | "slate"; children: ReactNode }) {
  const c =
    tone === "amber"
      ? "border-amber-500/50 bg-amber-950/60 text-amber-200"
      : tone === "red"
        ? "border-red-500/50 bg-red-950/60 text-red-200"
        : "border-slate-700 bg-slate-900/60 text-slate-300";
  return (
    <div role={tone === "red" ? "alert" : undefined} className={`rounded-lg border p-3 text-sm ${c}`}>
      {children}
    </div>
  );
}

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return <span className={`inline-block animate-spin rounded-full border-2 border-emerald-400 border-t-transparent ${className}`} aria-hidden />;
}

export function WarnIcon({ className = "h-6 w-6" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M12 3l10 18H2z" />
      <path d="M12 10v5M12 18v.01" />
    </svg>
  );
}

export function SimBadge({ simulated, network }: { simulated: boolean; network?: string }) {
  return simulated ? (
    <span className="whitespace-nowrap rounded-full border border-amber-500/60 bg-amber-950/60 px-3 py-1 text-xs font-bold text-amber-200">
      SIMULADO - no anclado en Solana
    </span>
  ) : (
    <span className="whitespace-nowrap rounded-full border border-emerald-500/60 bg-emerald-950/60 px-3 py-1 text-xs font-bold text-emerald-200">
      Anclado en {network ?? "solana-devnet"}
    </span>
  );
}

export function telegramText(n: NotificationResult | null | undefined) {
  if (!n) return { text: "no enviado", ok: false };
  if (!n.sent) return { text: `fallo: ${n.error || "sin detalle"}`, ok: false };
  return { text: n.is_mock ? "simulado (sin bot configurado)" : "enviado", ok: true };
}

/** Shared "Prueba en Solana" section (audits and bill checks). */
export function ProofSection({
  proof,
  canonicalJson,
  extraRows,
  onVerify,
}: {
  proof: OracleProof;
  canonicalJson?: string | null;
  extraRows?: ReactNode;
  onVerify?: () => void;
}) {
  const json = canonicalJson ?? proof.canonical_json;
  return (
    <section className={card} aria-label="Prueba en Solana">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">Prueba en Solana</h2>
        <SimBadge simulated={proof.is_simulated} network={proof.network} />
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
          <span className="inline-flex flex-wrap items-center gap-2">
            <code title={proof.tx_signature}>{short(proof.tx_signature, 8)}</code>
            <CopyButton text={proof.tx_signature} />
          </span>
        </Row>
        <Row label="Slot">{proof.slot ?? "-"}</Row>
        <Row label="Firmante">
          <code title={proof.signer ?? undefined}>{short(proof.signer)}</code>
        </Row>
        {extraRows}
      </dl>
      {json && (
        <details className="mt-3 rounded-lg bg-slate-800/50 p-3 text-sm">
          <summary className="cursor-pointer font-medium text-slate-200">Ver JSON exacto hasheado</summary>
          <div className="mt-2 flex justify-end">
            <CopyButton text={json} label="Copiar JSON" />
          </div>
          <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs text-slate-300">{json}</pre>
        </details>
      )}
      <div className="mt-4 flex flex-wrap gap-2">
        {!proof.is_simulated && proof.solscan_url && (
          <a href={proof.solscan_url} target="_blank" rel="noreferrer" className={primaryBtn}>
            Ver en Solscan Devnet
          </a>
        )}
        {onVerify && (
          <button type="button" onClick={onVerify} className={secondaryBtn}>
            Verificar esta prueba
          </button>
        )}
      </div>
    </section>
  );
}

const MAX_BYTES = 10 * 1024 * 1024;
export const IMAGE_ACCEPT = "image/jpeg,image/png,image/webp,image/heic,image/heif";

/** Image picker with preview. Reports size errors through onError. */
export function UploadZone({
  id,
  title,
  subtitle,
  file,
  onFile,
  onError,
  required,
  compact,
  capture,
}: {
  id: string;
  title: string;
  subtitle?: string;
  file: File | null;
  onFile: (f: File | null) => void;
  onError?: (msg: string) => void;
  required?: boolean;
  compact?: boolean;
  capture?: boolean;
}) {
  const [preview, setPreview] = useState<string | null>(null);
  useEffect(() => {
    if (!file) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  function pick(f: File | null) {
    if (f && f.size > MAX_BYTES) {
      onError?.(`"${f.name}" pesa ${(f.size / 1024 / 1024).toFixed(1)} MB; el máximo es 10 MB.`);
      return;
    }
    onFile(f);
  }

  return (
    <div className="flex flex-col">
      <label
        htmlFor={id}
        className={`flex ${compact ? "min-h-36" : "min-h-40"} cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed bg-slate-950 p-3 text-center focus-within:border-emerald-300 focus-within:ring-2 focus-within:ring-emerald-400/40 hover:border-emerald-400 ${
          required ? "border-emerald-500/60" : "border-slate-600"
        }`}
      >
        {preview ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={preview} alt={`Vista previa: ${title}`} className={`${compact ? "max-h-40" : "max-h-64"} rounded-md object-contain`} />
        ) : (
          <svg viewBox="0 0 24 24" className="h-9 w-9 text-emerald-400" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
            <path d="M4 8h3l2-3h6l2 3h3v11H4z" />
            <circle cx="12" cy="13" r="3.5" />
          </svg>
        )}
        <span className="text-sm font-semibold text-emerald-300">
          {title}
          {required ? <span className="ml-1 text-xs font-normal text-slate-400">(obligatorio)</span> : <span className="ml-1 text-xs font-normal text-slate-400">(opcional)</span>}
        </span>
        <span className="text-xs text-slate-400">{preview ? "Pulsa para cambiar" : subtitle ?? "JPEG, PNG, WebP o HEIC, máximo 10 MB"}</span>
        <input
          id={id}
          type="file"
          accept={IMAGE_ACCEPT}
          capture={capture ? "environment" : undefined}
          className="sr-only"
          onChange={(e) => {
            pick(e.target.files?.[0] ?? null);
            e.target.value = "";
          }}
        />
      </label>
      {file && !required && (
        <button type="button" onClick={() => onFile(null)} className="mt-1 self-end text-xs text-slate-400 underline hover:text-red-300">
          Quitar
        </button>
      )}
    </div>
  );
}
