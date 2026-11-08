"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState, type FormEvent, type InputHTMLAttributes } from "react";
import { useWallet } from "@solana/wallet-adapter-react";
import { API, apiPost, ApiError, short, type AuditResponse, type Conflict } from "./api";
import { Pipeline, type Stage } from "./Pipeline";
import { Banner, ResultCard } from "./ResultCard";
import { VerifyPanel } from "./VerifyPanel";
import { LandingPage } from "./LandingPage";
import { translations, type Locale } from "./i18n";

// Wallet button renders differently server vs. client; load it client-only to avoid hydration errors.
const WalletMultiButton = dynamic(async () => (await import("@solana/wallet-adapter-react-ui")).WalletMultiButton, { ssr: false });

type Tab = "meter" | "sensor" | "verify";
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
  const [view, setView] = useState<"landing" | "app">("landing");
  const [lang, setLang] = useState<Locale>("es");

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

  const t = translations[lang];
  const busy = stage === "vision" || stage === "anchor" || stage === "notify";

  useEffect(() => {
    setMounted(true);
    const saved = localStorage.getItem("ecotrust_lang") as Locale | null;
    if (saved === "en" || saved === "es") setLang(saved);
  }, []);

  function toggleLanguage() {
    const next: Locale = lang === "es" ? "en" : "es";
    setLang(next);
    localStorage.setItem("ecotrust_lang", next);
  }

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  // Timed estimate of the stage while the single request runs.
  useEffect(() => {
    if (!busy) return;
    const interval = setInterval(() => {
      const s = (Date.now() - startRef.current) / 1000;
      setElapsed(Math.floor(s));
      const next = estimate(s, flow);
      setStage((cur) => (cur === "vision" || cur === "anchor" || cur === "notify" ? next : cur));
    }, 250);
    return () => clearInterval(interval);
  }, [busy, flow]);

  function pickFile(f: File | null) {
    setError(null);
    if (f && f.size > MAX_BYTES) {
      setError(lang === "es" ? `La foto pesa ${(f.size / 1024 / 1024).toFixed(1)} MB; el máximo es 10 MB.` : `Photo is ${(f.size / 1024 / 1024).toFixed(1)} MB; maximum allowed is 10 MB.`);
      f = null;
    }
    setFile(f);
    setPreview(f ? URL.createObjectURL(f) : null);
  }

  function selectTab(nextTab: Tab) {
    setTab(nextTab);
    if (nextTab !== "verify" && !busy) setFlow(nextTab);
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
        if (thresh) body.set("monthly_threshold", thresh);
        res = await apiPost<AuditResponse>("/api/v1/audit-meter", { body });
      } else {
        const params = new URLSearchParams();
        if (prev) params.set("previous_value", prev);
        if (thresh) params.set("monthly_threshold", thresh);
        const qs = params.toString() ? `?${params.toString()}` : "";
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
      else setError(err instanceof Error && err.message ? err.message : "Error");
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
    <main className="mx-auto max-w-5xl space-y-6 p-4 md:p-6">
      {/* Universal Top Navigation Header */}
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-4">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setView("landing")}
            className="flex items-center gap-2 text-left text-xl font-extrabold tracking-tight md:text-2xl hover:opacity-90"
          >
            <span>🌿</span>
            <span>
              EcoTrust <span className="text-emerald-400">Oracle</span>
            </span>
          </button>

          <nav className="hidden sm:flex items-center gap-1 rounded-lg border border-slate-800 bg-slate-900/80 p-1 text-xs">
            <button
              type="button"
              onClick={() => setView("landing")}
              className={`rounded-md px-3 py-1.5 font-medium transition-colors ${
                view === "landing" ? "bg-emerald-500 text-slate-950 font-bold" : "text-slate-300 hover:text-slate-100"
              }`}
            >
              {t.nav.home}
            </button>
            <button
              type="button"
              onClick={() => setView("app")}
              className={`rounded-md px-3 py-1.5 font-medium transition-colors ${
                view === "app" ? "bg-emerald-500 text-slate-950 font-bold" : "text-slate-300 hover:text-slate-100"
              }`}
            >
              {t.nav.demo}
            </button>
          </nav>
        </div>

        <div className="flex items-center gap-2">
          {/* Telegram Bot Link Button */}
          <a
            href="https://t.me/Es0TrustBot"
            target="_blank"
            rel="noreferrer"
            className="hidden md:inline-flex items-center gap-1.5 rounded-lg border border-sky-500/30 bg-sky-950/30 px-3 py-1.5 text-xs font-semibold text-sky-300 hover:bg-sky-900/50 hover:text-sky-200"
          >
            <span>@Es0TrustBot</span>
            <span className="text-xs">&rarr;</span>
          </a>

          {/* Language Switcher */}
          <button
            type="button"
            onClick={toggleLanguage}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs font-bold text-slate-200 transition-colors hover:border-slate-500 hover:bg-slate-800"
            title="Cambiar idioma / Switch language"
          >
            <span>{lang === "es" ? "🇲🇽 ES" : "🇺🇸 EN"}</span>
            <span className="text-[10px] text-slate-400">({lang === "es" ? "EN" : "ES"})</span>
          </button>

          {/* Wallet MultiButton */}
          {mounted ? <WalletMultiButton /> : <div className="h-10 w-36 animate-pulse rounded-md bg-slate-800" />}
        </div>
      </header>

      {/* Main Content Area: Landing Page vs. Interactive Audit App */}
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
        <div className="space-y-6">
          {/* App Top Toolbar */}
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <div>
              <h2 className="text-xl font-bold md:text-2xl">
                {t.app.title} <span className="text-emerald-400">{t.app.titleAccent}</span> — {t.nav.demo}
              </h2>
              <p className="mt-0.5 text-xs text-slate-400">{t.app.subtitle}</p>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setView("landing")}
                className="rounded-md border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-semibold text-slate-200 hover:bg-slate-700"
              >
                {t.nav.backHome}
              </button>
              <a
                href="https://t.me/Es0TrustBot"
                target="_blank"
                rel="noreferrer"
                className="rounded-md border border-sky-500/40 bg-sky-950/40 px-3 py-1.5 text-xs font-semibold text-sky-200 hover:bg-sky-900/60"
              >
                Telegram @Es0TrustBot ↗
              </a>
            </div>
          </div>

          <Pipeline stage={stage} failedAt={failedAt} sensor={flow === "sensor"} elapsed={elapsed} />

          <div className="grid gap-5 md:grid-cols-2">
            <div className="space-y-4">
              <div className="flex gap-1 rounded-lg bg-slate-900 p-1" role="group" aria-label="Modo">
                <button
                  type="button"
                  aria-pressed={tab === "meter"}
                  onClick={() => selectTab("meter")}
                  className={`flex-1 rounded-md px-3 py-2 text-sm font-medium ${
                    tab === "meter" ? "bg-emerald-500 text-slate-950" : "text-slate-300 hover:bg-slate-800"
                  }`}
                >
                  {t.app.tabMeter}
                </button>
                <button
                  type="button"
                  aria-pressed={tab === "sensor"}
                  onClick={() => selectTab("sensor")}
                  className={`flex-1 rounded-md px-3 py-2 text-sm font-medium ${
                    tab === "sensor" ? "bg-emerald-500 text-slate-950" : "text-slate-300 hover:bg-slate-800"
                  }`}
                >
                  {t.app.tabSensor}
                </button>
                <button
                  type="button"
                  aria-pressed={tab === "verify"}
                  onClick={() => selectTab("verify")}
                  className={`flex-1 rounded-md px-3 py-2 text-sm font-medium ${
                    tab === "verify" ? "bg-emerald-500 text-slate-950" : "text-slate-300 hover:bg-slate-800"
                  }`}
                >
                  {t.app.tabVerify}
                </button>
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
                        <span className="text-base font-semibold text-emerald-300">
                          {preview ? t.app.dropChange : t.app.dropPrompt}
                        </span>
                        <span className="text-xs text-slate-400">{t.app.dropLimits}</span>
                      </label>
                      <input
                        id="file"
                        type="file"
                        accept="image/jpeg,image/png,image/webp,image/heic,image/heif"
                        capture="environment"
                        className="sr-only"
                        onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
                      />
                      <Field id="meter_hint" label={t.app.noteLabel} placeholder={t.app.notePlaceholder} />
                      <Field id="device_id" label={t.app.deviceIdLabel} maxLength={128} placeholder={t.app.deviceIdPlaceholder} />
                      <div className="grid grid-cols-2 gap-3">
                        <Field id="previous_value" label={t.app.prevLabel} type="number" step="any" placeholder={t.app.prevPlaceholder} />
                        <Field id="monthly_threshold" label={t.app.thresholdLabel} type="number" step="any" min="0" placeholder={t.app.thresholdPlaceholder} />
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="grid grid-cols-2 gap-3">
                        <Field id="value" label={t.app.valueLabel} type="number" step="any" required />
                        <Field id="unit" label={t.app.unitLabel} required placeholder={t.app.unitPlaceholder} />
                      </div>
                      <Field id="confidence" label={t.app.confLabel} type="number" step="0.01" min="0" max="1" defaultValue="1" required />
                      <Field id="device_id" label={t.app.deviceIdLabel} maxLength={128} placeholder={auditor ? `Auditor: ${short(auditor, 4)}` : "SENSOR-01"} />
                      <div className="grid grid-cols-2 gap-3">
                        <Field id="previous_value" label={t.app.prevLabel} type="number" step="any" placeholder={t.app.prevPlaceholder} />
                        <Field id="monthly_threshold" label={t.app.thresholdLabel} type="number" step="any" min="0" placeholder={t.app.thresholdPlaceholder} />
                      </div>
                    </>
                  )}
                  <button type="submit" disabled={busy || (tab === "meter" && !file)} className={submitBtn}>
                    {busy ? `${t.app.processingBtn} ${elapsed} s` : tab === "meter" && !file ? t.app.uploadFirstBtn : t.app.auditBtn}
                  </button>
                </form>
              )}
            </div>

            <div className="space-y-4" aria-live="polite">
              {conflict && (
                <div className="rounded-xl border-2 border-red-500 bg-red-950/70 p-5 text-red-100">
                  <p className="text-lg font-bold">{t.app.conflictTitle}</p>
                  <p className="mt-2 text-sm">{t.app.conflictDesc}</p>
                  {conflict.message && <p className="mt-2 text-xs text-red-200">{conflict.message}</p>}
                </div>
              )}
              {error && <Banner tone="red">{error}</Banner>}
              {result ? (
                <ResultCard result={result} onVerify={verifyLast} lang={lang} />
              ) : (
                !conflict &&
                !error && (
                  <div className="rounded-xl border border-dashed border-slate-700 bg-slate-900/40 p-6 text-sm text-slate-300">
                    <p className="text-base font-semibold text-slate-100">{t.app.emptyStateTitle}</p>
                    <p className="mt-2">{t.app.emptyStateDesc}</p>
                    <p className="mt-3 text-xs text-slate-400">Backend API: {API}</p>
                  </div>
                )
              )}
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
