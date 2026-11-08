"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState, type FormEvent, type InputHTMLAttributes } from "react";
import { useWallet } from "@solana/wallet-adapter-react";
import { API, apiPost, ApiError, short, type AuditResponse, type Conflict } from "./api";
import { Pipeline, type Stage } from "./Pipeline";
import { Banner, ResultCard } from "./ResultCard";
import { VerifyPanel } from "./VerifyPanel";

// Wallet button renders differently server vs. client; load it client-only to avoid hydration errors.
const WalletMultiButton = dynamic(async () => (await import("@solana/wallet-adapter-react-ui")).WalletMultiButton, { ssr: false });

type Tab = "meter" | "sensor" | "verify";
const TABS: [Tab, string][] = [
  ["meter", "Foto de medidor"],
  ["sensor", "Sensor IoT"],
  ["verify", "Verificar"],
];
const MAX_BYTES = 10 * 1024 * 1024;
const STAGE_INDEX: Partial<Record<Stage, number>> = { vision: 1, anchor: 2, notify: 3 };
const estimate = (s: number, flow: "meter" | "sensor"): Stage =>
  flow === "meter" ? (s < 8 ? "vision" : s < 12 ? "anchor" : "notify") : s < 3 ? "anchor" : "notify";

const field = "w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-emerald-400 focus:outline-none";
const labelCls = "mb-1 block text-sm font-medium text-slate-200";

function Field({ id, label, ...props }: { id: string; label: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div>
      <label htmlFor={id} className={labelCls}>{label}</label>
      <input id={id} name={id} className={field} {...props} />
    </div>
  );
}

export default function Home() {
  const [mounted, setMounted] = useState(false);
  const { publicKey } = useWallet();
  const auditor = mounted ? publicKey?.toBase58() : undefined;

  const [tab, setTab] = useState<Tab>("meter");
  const [flow, setFlow] = useState<"meter" | "sensor">("meter");
  const [stage, setStage] = useState<Stage>("idle");
  const [failedAt, setFailedAt] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(0);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<Conflict | null>(null);
  const [result, setResult] = useState<AuditResponse | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [verifyJson, setVerifyJson] = useState("");
  const [verifyTx, setVerifyTx] = useState("");

  const busy = stage === "vision" || stage === "anchor" || stage === "notify";

  useEffect(() => setMounted(true), []);

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  // Timed estimate of the stage while the single request runs.
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(() => {
      const s = (Date.now() - startRef.current) / 1000;
      setElapsed(Math.floor(s));
      const next = estimate(s, flow);
      setStage((cur) => (cur === "vision" || cur === "anchor" || cur === "notify" ? next : cur));
    }, 250);
    return () => clearInterval(t);
  }, [busy, flow]);

  function pickFile(f: File | null) {
    setError(null);
    if (f && f.size > MAX_BYTES) {
      setError(`La foto pesa ${(f.size / 1024 / 1024).toFixed(1)} MB; el máximo es 10 MB.`);
      f = null;
    }
    setFile(f);
    setPreview(f ? URL.createObjectURL(f) : null);
  }

  function selectTab(t: Tab) {
    setTab(t);
    if (t !== "verify" && !busy) setFlow(t);
  }

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (busy) return;
    const form = new FormData(e.currentTarget);
    const prev = String(form.get("previous_value") ?? "").trim();
    const mode = tab === "sensor" ? "sensor" : "meter";
    if (mode === "meter" && !file) {
      setError("Primero toma o sube una foto del medidor.");
      return;
    }
    setFlow(mode);
    setError(null);
    setConflict(null);
    setResult(null);
    setFailedAt(null);
    setElapsed(0);
    startRef.current = Date.now();
    setStage(mode === "meter" ? "vision" : "anchor");
    try {
      let res: AuditResponse;
      if (mode === "meter") {
        const body = new FormData();
        body.set("file", file as File);
        for (const k of ["meter_hint", "device_id"]) {
          const v = String(form.get(k) ?? "").trim();
          if (v) body.set(k, v);
        }
        if (prev) body.set("previous_value", prev);
        res = await apiPost<AuditResponse>("/api/v1/audit-meter", { body });
      } else {
        const qs = prev ? `?previous_value=${encodeURIComponent(prev)}` : "";
        res = await apiPost<AuditResponse>(`/api/v1/audit-sensor${qs}`, {
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            value: Number(form.get("value")),
            unit: String(form.get("unit") ?? "").trim(),
            confidence: Number(form.get("confidence")),
            timestamp: new Date().toISOString(),
            source: "iot_sensor",
            device_id: String(form.get("device_id") ?? "").trim() || auditor || null,
          }),
        });
      }
      setResult(res);
      setStage("done");
    } catch (err) {
      const at = estimate((Date.now() - startRef.current) / 1000, mode);
      setFailedAt(err instanceof ApiError && err.conflict ? 2 : (STAGE_INDEX[at] ?? 1));
      setStage("error");
      if (err instanceof ApiError && err.conflict) setConflict(err.conflict);
      else setError(err instanceof Error && err.message ? err.message : "Error desconocido");
    }
  }

  function verifyLast() {
    if (!result) return;
    setVerifyJson(JSON.stringify(result.reading, null, 2));
    setVerifyTx(result.oracle_proof.tx_signature);
    setTab("verify");
  }

  const submitBtn =
    "w-full rounded-md bg-emerald-500 px-4 py-3 text-base font-semibold text-slate-950 hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-300";

  return (
    <main className="mx-auto max-w-5xl space-y-5 p-4 md:p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold md:text-3xl">
            EcoTrust <span className="text-emerald-400">Oracle</span>
          </h1>
          <p className="mt-1 text-slate-300">Foto de un medidor &rarr; la IA lo lee 3 veces &rarr; la huella queda en Solana</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          {mounted ? <WalletMultiButton /> : <div className="h-12 w-40 animate-pulse rounded-md bg-slate-800" />}
          <p className="text-xs text-slate-400">{auditor ? `Auditor: ${short(auditor, 4)}` : "Billetera opcional"}</p>
        </div>
      </header>

      <Pipeline stage={stage} failedAt={failedAt} sensor={flow === "sensor"} elapsed={elapsed} />

      <div className="grid gap-5 md:grid-cols-2">
        <div className="space-y-4">
          <div className="flex gap-1 rounded-lg bg-slate-900 p-1" role="group" aria-label="Modo">
            {TABS.map(([t, label]) => (
              <button
                key={t}
                type="button"
                aria-pressed={tab === t}
                onClick={() => selectTab(t)}
                className={`flex-1 rounded-md px-3 py-2 text-sm font-medium ${tab === t ? "bg-emerald-500 text-slate-950" : "text-slate-300 hover:bg-slate-800"}`}
              >
                {label}
              </button>
            ))}
          </div>

          {tab === "verify" ? (
            <VerifyPanel readingJson={verifyJson} txSig={verifyTx} onReadingJson={setVerifyJson} onTxSig={setVerifyTx} />
          ) : (
            <form key={tab} onSubmit={submit} className="space-y-4 rounded-xl border border-slate-800 bg-slate-900 p-5">
              {tab === "meter" ? (
                <>
                  <label
                    htmlFor="file"
                    className="flex min-h-40 cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-emerald-500/60 bg-slate-950 p-4 text-center hover:border-emerald-400"
                  >
                    {preview ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={preview} alt="Vista previa del medidor" className="max-h-64 rounded-md object-contain" />
                    ) : (
                      <svg viewBox="0 0 24 24" className="h-10 w-10 text-emerald-400" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
                        <path d="M4 8h3l2-3h6l2 3h3v11H4z" />
                        <circle cx="12" cy="13" r="3.5" />
                      </svg>
                    )}
                    <span className="text-base font-semibold text-emerald-300">{preview ? "Cambiar foto" : "Tomar o subir foto"}</span>
                    <span className="text-xs text-slate-400">JPEG, PNG, WebP o HEIC, máximo 10 MB</span>
                  </label>
                  <input
                    id="file"
                    type="file"
                    accept="image/jpeg,image/png,image/webp,image/heic,image/heif"
                    capture="environment"
                    className="sr-only"
                    onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
                  />
                  <Field id="meter_hint" label="Nota (opcional)" placeholder="Ej: Caldera principal" />
                  <Field id="device_id" label="ID del medidor (opcional)" maxLength={128} placeholder="Ej: MED-001" />
                  <Field id="previous_value" label="Lectura anterior (opcional)" type="number" step="any" placeholder="Para calcular consumo" />
                </>
              ) : (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <Field id="value" label="Valor" type="number" step="any" required />
                    <Field id="unit" label="Unidad" required placeholder="kWh, m3..." />
                  </div>
                  <Field id="confidence" label="Confianza (0 a 1)" type="number" step="0.01" min="0" max="1" defaultValue="1" required />
                  <Field id="device_id" label="ID del dispositivo" maxLength={128} placeholder={auditor ? `Por defecto: ${short(auditor, 4)}` : "Ej: SENSOR-07"} />
                  <Field id="previous_value" label="Lectura anterior (opcional)" type="number" step="any" />
                </>
              )}
              <button type="submit" disabled={busy || (tab === "meter" && !file)} className={submitBtn}>
                {busy ? `Procesando... ${elapsed} s` : tab === "meter" && !file ? "Sube una foto para auditar" : "Auditar y anclar en Solana"}
              </button>
            </form>
          )}
        </div>

        <div className="space-y-4" aria-live="polite">
          {conflict && (
            <div className="rounded-xl border-2 border-red-500 bg-red-950/70 p-5 text-red-100">
              <p className="text-lg font-bold">Alerta: posible fraude o lectura errónea</p>
              <p className="mt-2 text-sm">
                La nueva lectura (<strong>{conflict.value}</strong>) es menor que la anterior (<strong>{conflict.previous_value}</strong>). Un contador no
                puede retroceder, así que <strong>no se ancló en Solana</strong>.
              </p>
              {conflict.message && <p className="mt-2 text-xs text-red-200">{conflict.message}</p>}
            </div>
          )}
          {error && <Banner tone="red">{error}</Banner>}
          {result ? (
            <ResultCard result={result} onVerify={verifyLast} />
          ) : (
            !conflict &&
            !error && (
              <div className="rounded-xl border border-dashed border-slate-700 bg-slate-900/40 p-6 text-sm text-slate-300">
                <p className="text-base font-semibold text-slate-100">Aún no hay auditorías</p>
                <p className="mt-2">
                  {busy
                    ? "Procesando la auditoría..."
                    : "Sube la foto de un medidor o envía la lectura de un sensor. Aquí verás el valor leído, la confianza de la IA y la prueba anclada en Solana."}
                </p>
                <p className="mt-3 text-xs text-slate-400">Backend: {API}</p>
              </div>
            )
          )}
        </div>
      </div>
    </main>
  );
}
