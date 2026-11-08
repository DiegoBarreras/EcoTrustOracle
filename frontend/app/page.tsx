"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useWallet } from "@solana/wallet-adapter-react";
import { API, apiGet, apiPost, apiPostJson, errorText, short, type AuditResponse, type DeviceSummary } from "./api";
import { BillCheckPanel } from "./BillCheckPanel";
import { HistoryPanel } from "./HistoryPanel";
import { LandingPage } from "./LandingPage";
import { Pipeline, type Stage } from "./Pipeline";
import { ResultCard } from "./ResultCard";
import { translations, type Locale } from "./i18n";
import { Banner, Field, field, UploadZone } from "./ui";
import { VerifyPanel, type VerifyMode } from "./VerifyPanel";

// Wallet button renders differently server vs. client; load it client-only to avoid hydration errors.
const WalletMultiButton = dynamic(async () => (await import("@solana/wallet-adapter-react-ui")).WalletMultiButton, { ssr: false });

type Tab = "meter" | "sensor" | "history" | "bills" | "verify";
const TAB_ORDER: Tab[] = ["meter", "sensor", "history", "bills", "verify"];
const STAGE_INDEX: Partial<Record<Stage, number>> = { vision: 1, anchor: 2, notify: 3 };
const estimate = (s: number, flow: "meter" | "sensor"): Stage =>
  flow === "meter" ? (s < 8 ? "vision" : s < 12 ? "anchor" : "notify") : s < 3 ? "anchor" : "notify";

function DeviceIdField({
  value,
  onChange,
  placeholder,
  title,
  hint,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  title: string;
  hint: string;
}) {
  return (
    <div className="rounded-lg border border-emerald-500/40 bg-emerald-950/20 p-3">
      <label htmlFor="device_id" className="mb-1 block text-base font-semibold text-emerald-200">
        {title}
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
        {hint}
      </p>
    </div>
  );
}

export default function Home() {
  const [mounted, setMounted] = useState(false);
  const [view, setView] = useState<"landing" | "app">("landing");
  const [lang, setLang] = useState<Locale>("es");
  const t = translations[lang];

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
  const tabLabel: Record<Tab, string> = {
    meter: t.app.tabMeter,
    sensor: t.app.tabSensor,
    history: t.app.tabHistory,
    bills: t.app.tabBills,
    verify: t.app.tabVerify,
  };

  useEffect(() => {
    setMounted(true);
    try {
      const saved = localStorage.getItem("ecotrust_lang");
      if (saved === "en" || saved === "es") setLang(saved);
    } catch {
      // Storage can be blocked (private mode); the default language still works.
    }
  }, []);

  function toggleLanguage() {
    const next: Locale = lang === "es" ? "en" : "es";
    setLang(next);
    try {
      localStorage.setItem("ecotrust_lang", next);
    } catch {
      // Not persisted when storage is blocked.
    }
  }

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
    const timer = setInterval(() => {
      const s = (Date.now() - startRef.current) / 1000;
      setElapsed(Math.floor(s));
      const next = estimate(s, flow);
      setStage((cur) => (cur === "vision" || cur === "anchor" || cur === "notify" ? next : cur));
    }, 250);
    return () => clearInterval(timer);
  }, [busy, flow]);

  function selectTab(next: Tab) {
    setTab(next);
    if ((next === "meter" || next === "sensor") && !busy) setFlow(next);
    if (next === "history") loadDevices();
  }

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (busy) return;
    const form = new FormData(e.currentTarget);
    const prev = String(form.get("previous_value") ?? "").trim();
    const thresh = String(form.get("monthly_threshold") ?? "").trim();
    const mode = tab === "sensor" ? "sensor" : "meter";
    if (mode === "meter" && !file) {
      setError(lang === "es" ? "Primero toma o sube una foto del medidor." : "Please capture or upload a meter photo first.");
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
        if (thresh) body.set("monthly_threshold", thresh);
        res = await apiPost<AuditResponse>("/api/v1/audit-meter", { body });
      } else {
        const params = new URLSearchParams();
        if (prev) params.set("previous_value", prev);
        if (thresh) params.set("monthly_threshold", thresh);
        const qs = params.toString() ? `?${params.toString()}` : "";
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
  const navBtn = (active: boolean) =>
    `rounded-md px-3 py-1.5 font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300 ${
      active ? "bg-emerald-500 font-bold text-slate-950" : "text-slate-300 hover:text-slate-100"
    }`;
  const auditTab = tab === "meter" || tab === "sensor";

  return (
    <main className="mx-auto max-w-6xl space-y-5 p-4 md:p-6">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-4">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setView("landing")}
            className="text-left text-xl font-extrabold tracking-tight hover:opacity-90 md:text-2xl"
          >
            EcoTrust <span className="text-emerald-400">Oracle</span>
          </button>
          <nav className="hidden items-center gap-1 rounded-lg border border-slate-800 bg-slate-900/80 p-1 text-xs sm:flex" aria-label="Vista">
            <button type="button" aria-pressed={view === "landing"} onClick={() => setView("landing")} className={navBtn(view === "landing")}>
              {t.nav.home}
            </button>
            <button type="button" aria-pressed={view === "app"} onClick={() => setView("app")} className={navBtn(view === "app")}>
              {t.nav.demo}
            </button>
          </nav>
        </div>

        <div className="flex items-center gap-2">
          <a
            href="https://t.me/Es0TrustBot"
            target="_blank"
            rel="noreferrer"
            className="hidden items-center gap-1.5 rounded-lg border border-sky-500/30 bg-sky-950/30 px-3 py-1.5 text-xs font-semibold text-sky-300 hover:bg-sky-900/50 hover:text-sky-200 md:inline-flex"
          >
            @Es0TrustBot <span aria-hidden>&rarr;</span>
          </a>
          <button
            type="button"
            onClick={toggleLanguage}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs font-bold text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800"
            title="Cambiar idioma / Switch language"
          >
            {lang === "es" ? "ES" : "EN"}
            <span className="text-[10px] text-slate-400">({lang === "es" ? "EN" : "ES"})</span>
          </button>
          <div className="flex flex-col items-end gap-1">
            {mounted ? <WalletMultiButton /> : <div className="h-10 w-36 animate-pulse rounded-md bg-slate-800" />}
            <p className="text-xs text-slate-400">{auditor ? `${t.app.auditor}: ${short(auditor, 4)}` : t.app.optionalWallet}</p>
          </div>
        </div>
      </header>

      {view === "landing" ? (
        <LandingPage
          lang={lang}
          onLaunchApp={() => setView("app")}
          onOpenVerify={() => {
            setView("app");
            selectTab("verify");
          }}
        />
      ) : (
        <>
          <div>
            <h2 className="text-xl font-bold md:text-2xl">
              {t.app.title} <span className="text-emerald-400">{t.app.titleAccent}</span>
            </h2>
            <p className="mt-0.5 text-sm text-slate-400">{t.app.subtitle}</p>
          </div>

          <nav className="-mx-4 overflow-x-auto px-4 md:mx-0 md:px-0" aria-label="Secciones">
            <div className="flex min-w-max gap-1 rounded-lg bg-slate-900 p-1 md:min-w-0" role="group" aria-label="Modo">
              {TAB_ORDER.map((id) => (
                <button
                  key={id}
                  type="button"
                  aria-pressed={tab === id}
                  onClick={() => selectTab(id)}
                  className={`flex-1 whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300 ${
                    tab === id ? "bg-emerald-500 text-slate-950" : "text-slate-300 hover:bg-slate-800"
                  }`}
                >
                  {tabLabel[id]}
                  {id === "history" && devices.some((d) => d.anomalies > 0) && (
                    <>
                      <span className="ml-1.5 inline-block h-2 w-2 rounded-full bg-red-500 align-middle" aria-hidden />
                      <span className="sr-only"> {t.app.anomaliesSr}</span>
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
                        title={file ? t.app.dropChange : t.app.dropPrompt}
                        subtitle={t.app.dropLimits}
                        file={file}
                        onFile={(f) => {
                          setError(null);
                          setFile(f);
                        }}
                        onError={setError}
                        required
                        capture
                      />
                      <DeviceIdField
                        value={deviceId}
                        onChange={setDeviceId}
                        placeholder={t.app.deviceIdPlaceholder}
                        title={t.app.deviceIdTitle}
                        hint={t.app.deviceIdHint}
                      />
                      <Field id="meter_hint" label={t.app.noteLabel} placeholder={t.app.notePlaceholder} />
                      <Field id="monthly_threshold" label={t.app.thresholdLabel} type="number" step="any" min="0" placeholder={t.app.thresholdPlaceholder} />
                    </>
                  ) : (
                    <>
                      <DeviceIdField
                        value={deviceId}
                        onChange={setDeviceId}
                        placeholder={auditor ? `${t.app.deviceIdSensorDefault}: ${short(auditor, 4)}` : "SENSOR-07"}
                        title={t.app.deviceIdTitle}
                        hint={t.app.deviceIdHint}
                      />
                      <div className="grid grid-cols-2 gap-3">
                        <Field id="value" label={t.app.valueLabel} type="number" step="any" required inputMode="decimal" />
                        <Field id="unit" label={t.app.unitLabel} required placeholder={t.app.unitPlaceholder} />
                      </div>
                      <Field id="confidence" label={t.app.confLabel} type="number" step="0.01" min="0" max="1" defaultValue="1" required />
                      <Field id="monthly_threshold" label={t.app.thresholdLabel} type="number" step="any" min="0" placeholder={t.app.thresholdPlaceholder} />
                    </>
                  )}
                  <Field
                    id="previous_value"
                    label={t.app.prevLabel}
                    type="number"
                    step="any"
                    inputMode="decimal"
                    placeholder={t.app.prevOverridePlaceholder}
                    hint={t.app.prevOverrideHint}
                  />
                  <button type="submit" disabled={busy || (tab === "meter" && !file)} className={submitBtn}>
                    {busy ? `${t.app.processingBtn} ${elapsed} s` : tab === "meter" && !file ? t.app.uploadFirstBtn : t.app.auditBtn}
                  </button>
                </form>

                <div className="min-w-0 space-y-4" aria-live="polite">
                  {error && <Banner tone="red">{error}</Banner>}
                  {result ? (
                    <ResultCard result={result} onVerify={verifyLast} lang={lang} />
                  ) : (
                    !error && (
                      <div className="rounded-xl border border-dashed border-slate-700 bg-slate-900/40 p-6 text-sm text-slate-300">
                        <p className="text-base font-semibold text-slate-100">{t.app.emptyStateTitle}</p>
                        <p className="mt-2">{busy ? t.app.busyText : t.app.emptyStateDesc}</p>
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
        </>
      )}
    </main>
  );
}
