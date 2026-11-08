"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useWallet } from "@solana/wallet-adapter-react";
import { API, apiGet, apiPost, apiPostJson, errorText, short, type AuditResponse, type DeviceSummary } from "./api";
import { BillCheckPanel } from "./BillCheckPanel";
import { HistoryPanel } from "./HistoryPanel";
import { Pipeline, type Stage } from "./Pipeline";
import { ResultCard } from "./ResultCard";
import { Banner, Field, field, UploadZone } from "./ui";
import { VerifyPanel, type VerifyMode } from "./VerifyPanel";

// Wallet button renders differently server vs. client; load it client-only to avoid hydration errors.
const WalletMultiButton = dynamic(async () => (await import("@solana/wallet-adapter-react-ui")).WalletMultiButton, { ssr: false });

type Tab = "meter" | "sensor" | "history" | "bills" | "verify";
const TABS: [Tab, string][] = [
  ["meter", "Foto de medidor"],
  ["sensor", "Sensor IoT"],
  ["history", "Historial"],
  ["bills", "Comparar recibos"],
  ["verify", "Verificar"],
];
const STAGE_INDEX: Partial<Record<Stage, number>> = { vision: 1, anchor: 2, notify: 3 };
const estimate = (s: number, flow: "meter" | "sensor"): Stage =>
  flow === "meter" ? (s < 8 ? "vision" : s < 12 ? "anchor" : "notify") : s < 3 ? "anchor" : "notify";

function DeviceIdField({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) {
  return (
    <div className="rounded-lg border border-emerald-500/40 bg-emerald-950/20 p-3">
      <label htmlFor="device_id" className="mb-1 block text-base font-semibold text-emerald-200">
        ID del medidor
      </label>
      <input
        id="device_id"
        name="device_id"
        list="device-options"
        maxLength={128}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete="off"
        className={`${field} text-base`}
        aria-describedby="device_id-hint"
      />
      <p id="device_id-hint" className="mt-1 text-xs text-slate-300">
        Activa el historial: la lectura se compara automáticamente con la última de este medidor y se aplica su límite de consumo.
      </p>
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
  const [result, setResult] = useState<AuditResponse | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [deviceId, setDeviceId] = useState("");

  const [verifyMode, setVerifyMode] = useState<VerifyMode>("reading");
  const [verifyJson, setVerifyJson] = useState("");
  const [verifyPayload, setVerifyPayload] = useState("");
  const [verifyTx, setVerifyTx] = useState("");

  const [devices, setDevices] = useState<DeviceSummary[]>([]);
  const [devicesLoading, setDevicesLoading] = useState(false);
  const [devicesError, setDevicesError] = useState<string | null>(null);
  const [historyDevice, setHistoryDevice] = useState<string | null>(null);
  const [historyKey, setHistoryKey] = useState(0);

  const busy = stage === "vision" || stage === "anchor" || stage === "notify";

  useEffect(() => setMounted(true), []);

  const loadDevices = useCallback(async () => {
    setDevicesLoading(true);
    try {
      const list = await apiGet<DeviceSummary[]>("/api/v1/devices");
      const arr = Array.isArray(list) ? list : [];
      setDevices(arr);
      setDevicesError(null);
      // Default to the most recently audited device.
      setHistoryDevice((cur) => {
        if (cur && arr.some((d) => d.device_id === cur)) return cur;
        const latest = [...arr].sort((a, b) => (b.last_timestamp > a.last_timestamp ? 1 : -1))[0];
        return latest?.device_id ?? null;
      });
    } catch (err) {
      setDevicesError(errorText(err));
    } finally {
      setDevicesLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDevices();
  }, [loadDevices]);

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

  function selectTab(t: Tab) {
    setTab(t);
    if ((t === "meter" || t === "sensor") && !busy) setFlow(t);
    if (t === "history") loadDevices();
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
    const dev = deviceId.trim() || (mode === "sensor" ? auditor ?? "" : "");
    setFlow(mode);
    setError(null);
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
        const hint = String(form.get("meter_hint") ?? "").trim();
        if (hint) body.set("meter_hint", hint);
        if (dev) body.set("device_id", dev);
        if (prev) body.set("previous_value", prev);
        res = await apiPost<AuditResponse>("/api/v1/audit-meter", { body });
      } else {
        const qs = prev ? `?previous_value=${encodeURIComponent(prev)}` : "";
        res = await apiPostJson<AuditResponse>(`/api/v1/audit-sensor${qs}`, {
          value: Number(form.get("value")),
          unit: String(form.get("unit") ?? "").trim(),
          confidence: Number(form.get("confidence")),
          timestamp: new Date().toISOString(),
          source: "iot_sensor",
          device_id: dev || null,
        });
      }
      setResult(res);
      setStage("done");
      const audited = res.reading?.device_id;
      if (audited) setHistoryDevice(audited);
      setHistoryKey((k) => k + 1);
      loadDevices();
    } catch (err) {
      const at = estimate((Date.now() - startRef.current) / 1000, mode);
      setFailedAt(STAGE_INDEX[at] ?? 1);
      setStage("error");
      setError(errorText(err));
    }
  }

  function verifyLast() {
    if (!result) return;
    setVerifyMode("reading");
    setVerifyJson(JSON.stringify(result.reading, null, 2));
    setVerifyTx(result.oracle_proof.tx_signature);
    setTab("verify");
  }

  function verifyPayloadProof(canonical: string, tx: string) {
    setVerifyMode("payload");
    setVerifyPayload(canonical);
    setVerifyTx(tx);
    setTab("verify");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  const submitBtn =
    "w-full rounded-md bg-emerald-500 px-4 py-3 text-base font-semibold text-slate-950 hover:bg-emerald-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-300";
  const auditTab = tab === "meter" || tab === "sensor";

  return (
    <main className="mx-auto max-w-6xl space-y-5 p-4 md:p-6">
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

      <nav className="-mx-4 overflow-x-auto px-4 md:mx-0 md:px-0" aria-label="Secciones">
        <div className="flex min-w-max gap-1 rounded-lg bg-slate-900 p-1 md:min-w-0" role="group" aria-label="Modo">
          {TABS.map(([t, label]) => (
            <button
              key={t}
              type="button"
              aria-pressed={tab === t}
              onClick={() => selectTab(t)}
              className={`flex-1 whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300 ${
                tab === t ? "bg-emerald-500 text-slate-950" : "text-slate-300 hover:bg-slate-800"
              }`}
            >
              {label}
              {t === "history" && devices.some((d) => d.anomalies > 0) && (
                <>
                  <span className="ml-1.5 inline-block h-2 w-2 rounded-full bg-red-500 align-middle" aria-hidden />
                  <span className="sr-only"> (hay anomalías)</span>
                </>
              )}
            </button>
          ))}
        </div>
      </nav>

      <datalist id="device-options">
        {devices.map((d) => (
          <option key={d.device_id} value={d.device_id}>{`${d.last_value} ${d.unit}`}</option>
        ))}
      </datalist>

      {auditTab && (
        <>
          <Pipeline stage={stage} failedAt={failedAt} sensor={flow === "sensor"} elapsed={elapsed} />
          <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
            <form key={tab} onSubmit={submit} className="h-fit space-y-4 rounded-xl border border-slate-800 bg-slate-900 p-5">
              {tab === "meter" ? (
                <>
                  <UploadZone
                    id="file"
                    title={file ? "Cambiar foto" : "Tomar o subir foto"}
                    file={file}
                    onFile={(f) => {
                      setError(null);
                      setFile(f);
                    }}
                    onError={setError}
                    required
                    capture
                  />
                  <DeviceIdField value={deviceId} onChange={setDeviceId} placeholder="Ej: MED-001" />
                  <Field id="meter_hint" label="Nota (opcional)" placeholder="Ej: Caldera principal" />
                </>
              ) : (
                <>
                  <DeviceIdField value={deviceId} onChange={setDeviceId} placeholder={auditor ? `Por defecto: ${short(auditor, 4)}` : "Ej: SENSOR-07"} />
                  <div className="grid grid-cols-2 gap-3">
                    <Field id="value" label="Valor" type="number" step="any" required inputMode="decimal" />
                    <Field id="unit" label="Unidad" required placeholder="kWh, m3..." />
                  </div>
                  <Field id="confidence" label="Confianza (0 a 1)" type="number" step="0.01" min="0" max="1" defaultValue="1" required />
                </>
              )}
              <Field
                id="previous_value"
                label="Lectura anterior (opcional)"
                type="number"
                step="any"
                inputMode="decimal"
                placeholder="Se usa la última del historial"
                hint="Solo si quieres ignorar el historial y comparar con otro valor."
              />
              <button type="submit" disabled={busy || (tab === "meter" && !file)} className={submitBtn}>
                {busy ? `Procesando... ${elapsed} s` : tab === "meter" && !file ? "Sube una foto para auditar" : "Auditar y anclar en Solana"}
              </button>
            </form>

            <div className="min-w-0 space-y-4" aria-live="polite">
              {error && <Banner tone="red">{error}</Banner>}
              {result ? (
                <ResultCard result={result} onVerify={verifyLast} />
              ) : (
                !error && (
                  <div className="rounded-xl border border-dashed border-slate-700 bg-slate-900/40 p-6 text-sm text-slate-300">
                    <p className="text-base font-semibold text-slate-100">Aún no hay auditorías</p>
                    <p className="mt-2">
                      {busy
                        ? "Procesando la auditoría..."
                        : "Sube la foto de un medidor o envía la lectura de un sensor. Aquí verás el valor leído, la comparación con la lectura anterior, el límite de consumo y la prueba anclada en Solana."}
                    </p>
                    <p className="mt-3 text-xs text-slate-400">Backend: {API}</p>
                  </div>
                )
              )}
            </div>
          </div>
        </>
      )}

      <div hidden={tab !== "history"}>
        <HistoryPanel
          devices={devices}
          devicesLoading={devicesLoading}
          devicesError={devicesError}
          onReloadDevices={loadDevices}
          selected={historyDevice}
          onSelect={setHistoryDevice}
          refreshKey={historyKey}
        />
      </div>

      <div hidden={tab !== "bills"}>
        <BillCheckPanel
          onVerify={verifyPayloadProof}
          onDone={() => {
            setHistoryKey((k) => k + 1);
            loadDevices();
          }}
        />
      </div>

      {tab === "verify" && (
        <div className="mx-auto max-w-3xl">
          <VerifyPanel
            mode={verifyMode}
            onMode={setVerifyMode}
            readingJson={verifyJson}
            payloadJson={verifyPayload}
            txSig={verifyTx}
            onReadingJson={setVerifyJson}
            onPayloadJson={setVerifyPayload}
            onTxSig={setVerifyTx}
          />
        </div>
      )}
    </main>
  );
}
