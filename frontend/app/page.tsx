"use client";

import dynamic from "next/dynamic";
import { useEffect, useState, type FormEvent } from "react";
import { useWallet } from "@solana/wallet-adapter-react";

// Wallet button renders differently server vs. client; load it client-only to avoid hydration errors.
const WalletMultiButton = dynamic(
  async () => (await import("@solana/wallet-adapter-react-ui")).WalletMultiButton,
  { ssr: false },
);

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type AuditResponse = {
  status: string;
  reading: { value: number; unit: string; confidence: number; timestamp: string; source: string };
  oracle_proof: { data_hash: string; solscan_url: string; tx_signature: string; is_simulated: boolean };
  notification: { sent: boolean; is_mock: boolean; error: string | null };
  execution_time_ms: number;
};

const input = "w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm";
const button = "rounded-md bg-emerald-500 px-4 py-2 font-semibold text-slate-950 disabled:opacity-40";

export default function Home() {
  const [mounted, setMounted] = useState(false);
  const { publicKey } = useWallet();
  const auditor = publicKey?.toBase58();
  const [mode, setMode] = useState<"meter" | "sensor">("meter");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AuditResponse | null>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  const isAuditorReady = mounted && Boolean(auditor);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      let res: Response;
      if (mode === "meter") {
        form.set("meter_hint", `${form.get("meter_hint") ?? ""} | auditor: ${auditor}`.trim());
        res = await fetch(`${API}/api/v1/audit-meter`, { method: "POST", body: form });
      } else {
        res = await fetch(`${API}/api/v1/audit-sensor`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            value: Number(form.get("value")),
            unit: form.get("unit"),
            confidence: Number(form.get("confidence")),
            timestamp: new Date().toISOString(),
            source: "iot_sensor",
            device_id: form.get("device_id") || auditor,
          }),
        });
      }
      const body = await res.json();
      if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail));
      setResult(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-2xl space-y-6 p-6">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">🌿 EcoTrust Oracle</h1>
        {mounted ? (
          <WalletMultiButton />
        ) : (
          <div className="h-10 w-36 rounded-md bg-slate-800 animate-pulse" />
        )}
      </header>

      <div className="flex gap-2">
        {(["meter", "sensor"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`rounded-md px-3 py-1 text-sm ${mode === m ? "bg-emerald-500 text-slate-950" : "bg-slate-800"}`}
          >
            {m === "meter" ? "📸 Foto de medidor" : "🔌 Sensor IoT"}
          </button>
        ))}
      </div>

      <form key={mode} onSubmit={submit} className="space-y-3 rounded-lg bg-slate-900 p-4">
        {mode === "meter" ? (
          <>
            <input name="file" type="file" accept="image/*" capture="environment" required className={input} />
            <input name="meter_hint" placeholder="Nota (ej: Caldera principal)" className={input} />
          </>
        ) : (
          <>
            <input name="value" type="number" step="any" placeholder="Valor" required className={input} />
            <input name="unit" placeholder="Unidad (kWh, m3...)" required className={input} />
            <input name="confidence" type="number" step="0.01" min="0" max="1" defaultValue="1" required className={input} />
            <input name="device_id" placeholder="ID del dispositivo (opcional)" className={input} />
          </>
        )}
        <button disabled={!isAuditorReady || busy} className={button}>
          {busy ? "Anclando en Solana…" : isAuditorReady ? "Auditar" : "Conecta tu billetera para auditar"}
        </button>
      </form>

      {error && <p className="rounded-md bg-red-950 p-3 text-sm text-red-300">{error}</p>}

      {result && (
        <section className="space-y-2 rounded-lg bg-slate-900 p-4 text-sm">
          <p className="text-3xl font-bold text-emerald-400">
            {result.reading.value} {result.reading.unit}
          </p>
          <p>Confianza: {(result.reading.confidence * 100).toFixed(1)}%</p>
          <p className="break-all">
            SHA-256: <code>{result.oracle_proof.data_hash}</code>
          </p>
          <p>
            Telegram: {result.notification.sent ? (result.notification.is_mock ? "simulado" : "enviado") : "falló"}
            {result.oracle_proof.is_simulated && " · ancla simulada (sin SOL/RPC)"}
          </p>
          <a href={result.oracle_proof.solscan_url} target="_blank" rel="noreferrer" className={`${button} inline-block`}>
            Ver en Solscan Devnet ↗
          </a>
        </section>
      )}
    </main>
  );
}
