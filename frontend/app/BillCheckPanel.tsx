"use client";

import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { apiPost, errorText, fmtDate, fmtNum, short, type BillCheckItem, type BillCheckResult, type BillExtraction, type BillFields } from "./api";
import { ConfidenceBar, VisionDetails } from "./ResultCard";
import { Banner, card, CopyButton, field, labelCls, primaryBtn, ProofSection, Row, Spinner, telegramText, UploadZone, WarnIcon } from "./ui";

// ---------------------------------------------------------------------------
// Labels
// ---------------------------------------------------------------------------

const FIELD_LABELS: [keyof BillFields, string][] = [
  ["provider", "Proveedor"],
  ["account_number", "Número de cuenta"],
  ["meter_serial", "Serie del medidor"],
  ["period_start", "Inicio del período"],
  ["period_end", "Fin del período"],
  ["previous_reading", "Lectura anterior"],
  ["current_reading", "Lectura actual"],
  ["billed_consumption", "Consumo facturado"],
  ["unit", "Unidad"],
  ["total_amount", "Importe total"],
  ["currency", "Moneda"],
  ["reading_type", "Tipo de lectura"],
];

const VERDICT = {
  consistent: { label: "Consistente", cls: "border-emerald-500 bg-emerald-950/60 text-emerald-200", sub: "Las cifras del recibo cuadran con lo que se pudo comprobar." },
  discrepancies: { label: "Discrepancias", cls: "border-red-500 bg-red-950/60 text-red-200", sub: "Hay cifras que no cuadran. Revisa las comprobaciones." },
  inconclusive: { label: "No concluyente", cls: "border-amber-500 bg-amber-950/60 text-amber-200", sub: "No hubo datos suficientes para comprobar el recibo." },
} as const;

const CHECK_STYLE = {
  match: { box: "border-emerald-500/40 bg-emerald-950/20", icon: "bg-emerald-400 text-slate-950", tag: "text-emerald-300", label: "Coincide" },
  mismatch: { box: "border-red-500/50 bg-red-950/30", icon: "bg-red-500 text-white", tag: "text-red-300", label: "No coincide" },
  not_checkable: { box: "border-slate-700 bg-slate-950/40", icon: "bg-slate-700 text-slate-300", tag: "text-slate-400", label: "No comprobable" },
} as const;

function CheckIcon({ status }: { status: BillCheckItem["status"] }) {
  const s = CHECK_STYLE[status] ?? CHECK_STYLE.not_checkable;
  return (
    <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${s.icon}`} aria-hidden>
      <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round">
        {status === "match" ? <path d="M4 10l4 4 8-8" /> : status === "mismatch" ? <path d="M5 5l10 10M15 5L5 15" /> : <path d="M5 10h10" />}
      </svg>
    </span>
  );
}

function fmtIsoDate(v: string) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(v);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : v;
}

function fmtField(key: keyof BillFields, f: BillFields): ReactNode {
  const v = f[key];
  if (v == null || v === "") return <span className="text-slate-500">-</span>;
  if (key === "period_start" || key === "period_end") return fmtIsoDate(String(v));
  if (key === "reading_type")
    return v === "estimated" ? <span className="font-semibold text-amber-300">Estimada por la compañía</span> : <span className="text-emerald-300">Real</span>;
  if (key === "total_amount") return `${fmtNum(v as number, 2)}${f.currency ? ` ${f.currency}` : ""}`;
  if (key === "previous_reading" || key === "current_reading" || key === "billed_consumption") return `${fmtNum(v as number, 4)}${f.unit ? ` ${f.unit}` : ""}`;
  return String(v);
}

function Cell({ bill, k }: { bill: BillExtraction; k: keyof BillFields }) {
  if (bill.disputed.includes(k))
    return (
      <span className="inline-flex items-center gap-1 rounded bg-amber-500/15 px-1.5 py-0.5 text-xs font-semibold text-amber-300" title="Las lecturas independientes de la IA no coincidieron; el campo se descarta">
        <WarnIcon className="h-3.5 w-3.5" /> lecturas en desacuerdo
      </span>
    );
  return <>{fmtField(k, bill.fields)}</>;
}

// ---------------------------------------------------------------------------
// Progress while waiting
// ---------------------------------------------------------------------------

function BillProgress({ elapsed, hasPrev, hasMeter, onCancel }: { elapsed: number; hasPrev: boolean; hasMeter: boolean; onCancel: () => void }) {
  const steps: [string, number][] = [
    ["Subiendo imágenes", 1],
    ["IA lee el recibo actual (3 lecturas)", 9],
    ...(hasPrev ? ([["IA lee el recibo anterior (3 lecturas)", 9]] as [string, number][]) : []),
    ...(hasMeter ? ([["IA lee la foto del medidor (3 lecturas)", 9]] as [string, number][]) : []),
    ["Comprobaciones aritméticas y explicación", 5],
    ["Anclaje en Solana y aviso por Telegram", 4],
  ];
  let acc = 0;
  let active = steps.length - 1;
  for (let i = 0; i < steps.length; i++) {
    acc += steps[i][1];
    if (elapsed < acc) {
      active = i;
      break;
    }
  }
  return (
    <section className={card} aria-label="Progreso de la comparación" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold text-slate-100">Analizando recibos... {elapsed} s</p>
        <button type="button" onClick={onCancel} className="rounded-md border border-slate-600 px-3 py-1 text-xs text-slate-200 hover:border-red-400 hover:text-red-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400">
          Cancelar
        </button>
      </div>
      <ol className="mt-3 space-y-2">
        {steps.map(([label], i) => {
          const done = i < active;
          const now = i === active;
          return (
            <li key={label} className="flex items-center gap-3 text-sm">
              {done ? (
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-400 text-slate-950" aria-hidden>
                  <svg viewBox="0 0 20 20" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="3"><path d="M4 10l4 4 8-8" /></svg>
                </span>
              ) : now ? (
                <span className="flex h-6 w-6 items-center justify-center" aria-hidden><Spinner className="h-5 w-5" /></span>
              ) : (
                <span className="h-6 w-6 rounded-full border-2 border-slate-600" aria-hidden />
              )}
              <span className={done ? "text-slate-200" : now ? "font-semibold text-emerald-300" : "text-slate-500"}>{label}</span>
            </li>
          );
        })}
      </ol>
      <p className="mt-3 text-xs text-slate-400">Progreso estimado (~). Con varias imágenes puede tardar entre 10 y 40 segundos.</p>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Result
// ---------------------------------------------------------------------------

function MetaRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
      <dt className="text-xs uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="min-w-0 text-slate-100">{children}</dd>
    </div>
  );
}

function BillMeta({ title, bill }: { title: string; bill: BillExtraction }) {
  return (
    <div className="rounded-lg border border-slate-800 p-3 text-sm">
      <p className="font-semibold text-slate-100">{title}</p>
      <dl className="mt-2 space-y-1.5">
        <MetaRow label="Lecturas válidas">
          <span className="inline-flex items-center gap-1.5">
            {Array.from({ length: bill.total_reads }, (_, i) => (
              <span key={i} className={`h-3 w-3 rounded-full border-2 ${i < bill.votes ? "border-emerald-400 bg-emerald-400" : "border-slate-500"}`} aria-hidden />
            ))}
            <span className="whitespace-nowrap">{bill.votes}/{bill.total_reads}</span>
          </span>
        </MetaRow>
        <MetaRow label="Modelo"><code className="break-all">{bill.model}</code></MetaRow>
        <MetaRow label="SHA-256 imagen">
          <span className="inline-flex items-center gap-2">
            <code title={bill.image_sha256}>{short(bill.image_sha256, 5)}</code>
            <CopyButton text={bill.image_sha256} />
          </span>
        </MetaRow>
        {bill.disputed.length > 0 && (
          <MetaRow label="En desacuerdo">
            <span className="text-amber-300">{bill.disputed.length} {bill.disputed.length === 1 ? "campo" : "campos"}</span>
          </MetaRow>
        )}
      </dl>
      {bill.notes && (
        <p className="mt-2 border-l-4 border-slate-600 bg-slate-800/50 px-3 py-2 text-xs italic text-slate-300">
          <span className="not-italic font-semibold text-slate-200">Notas de la IA: </span>
          {bill.notes}
        </p>
      )}
    </div>
  );
}

function BillResult({ result: r, onVerify }: { result: BillCheckResult; onVerify: (canonical: string, tx: string) => void }) {
  const v = VERDICT[r.verdict] ?? VERDICT.inconclusive;
  const prev = r.previous_bill;
  const mock = r.bill.is_mock || prev?.is_mock || r.meter_vision?.is_mock;
  const currency = r.currency ?? r.bill.fields.currency ?? "";
  const counts = r.checks.reduce((a, c) => ({ ...a, [c.status]: (a[c.status] ?? 0) + 1 }), {} as Record<string, number>);
  const canonical = r.canonical_json ?? r.oracle_proof?.canonical_json ?? null;
  const tg = telegramText(r.notification);

  return (
    <div className="space-y-4">
      {mock && <Banner tone="amber">Resultado simulado: el servidor no tiene clave de IA, los datos del recibo son de ejemplo.</Banner>}

      <section className={`rounded-xl border-2 p-5 ${v.cls}`} aria-label="Veredicto">
        <p className="text-xs uppercase tracking-wide opacity-80">Veredicto</p>
        <p className="mt-1 text-3xl font-black">{v.label}</p>
        <p className="mt-1 text-sm">{v.sub}</p>
        <p className="mt-2 text-xs opacity-80">
          {counts.match ?? 0} coinciden &middot; {counts.mismatch ?? 0} no coinciden &middot; {counts.not_checkable ?? 0} no comprobables
        </p>
      </section>

      {r.overcharge_estimate != null && r.overcharge_estimate > 0 && (
        <section className="rounded-xl border-2 border-red-500 bg-red-950/70 p-5 text-red-100" aria-label="Posible cobro de más">
          <p className="text-xs uppercase tracking-wide text-red-300">Posible cobro de más (estimado)</p>
          <p className="mt-1 text-4xl font-black tabular-nums">
            {fmtNum(r.overcharge_estimate, 2)} <span className="text-xl">{currency}</span>
          </p>
          <p className="mt-1 text-xs text-red-200">Calculado por el código a partir de las comprobaciones, no por la IA.</p>
        </section>
      )}

      <section className={`${card} bg-slate-900`} aria-label="Explicación de la IA">
        <p className="text-xs uppercase tracking-wide text-slate-400">Explicación generada por la IA a partir de las comprobaciones</p>
        <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-slate-100">{r.explanation || "Sin explicación."}</p>
      </section>

      <section className={card} aria-label="Datos de los recibos">
        <h2 className="mb-3 text-lg font-semibold">Datos leídos</h2>
        <div className="-mx-5 overflow-x-auto px-5">
          <table className="w-full min-w-[420px] text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-slate-400">
              <tr className="border-b border-slate-800">
                <th scope="col" className="py-2 pr-3 font-medium">Campo</th>
                <th scope="col" className="py-2 pr-3 font-medium">Recibo actual</th>
                {prev && <th scope="col" className="py-2 font-medium">Recibo anterior</th>}
              </tr>
            </thead>
            <tbody>
              {FIELD_LABELS.map(([k, label]) => {
                const disputed = r.bill.disputed.includes(k) || prev?.disputed.includes(k);
                return (
                  <tr key={k} className={`border-b border-slate-800/70 ${disputed ? "bg-amber-950/20" : ""}`}>
                    <th scope="row" className="py-2 pr-3 font-normal text-slate-400">{label}</th>
                    <td className="break-all py-2 pr-3 text-slate-100"><Cell bill={r.bill} k={k} /></td>
                    {prev && <td className="break-all py-2 text-slate-100"><Cell bill={prev} k={k} /></td>}
                  </tr>
                );
              })}
              {r.meter_reading && (
                <tr className="bg-emerald-950/20">
                  <th scope="row" className="py-2 pr-3 font-semibold text-emerald-300">Lectura del medidor (foto)</th>
                  <td className="py-2 pr-3" colSpan={prev ? 2 : 1}>
                    <span className="font-semibold tabular-nums text-emerald-300">
                      {fmtNum(r.meter_reading.value, 4)} {r.meter_reading.unit}
                    </span>
                    <span className="ml-2 text-xs text-slate-400">{fmtDate(r.meter_reading.timestamp)}</span>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {r.meter_reading && (
          <div className="mt-4 space-y-3">
            <ConfidenceBar value={r.meter_reading.confidence} />
            {r.meter_vision && !r.meter_vision.is_mock && (
              <details className="rounded-lg bg-slate-800/40 p-3 text-sm">
                <summary className="cursor-pointer font-medium text-slate-200">Cómo leyó la IA el medidor</summary>
                <div className="mt-3">
                  <VisionDetails vision={r.meter_vision} majority={r.meter_reading.value} />
                </div>
              </details>
            )}
          </div>
        )}
        <div className={`mt-4 grid gap-3 ${prev ? "sm:grid-cols-2" : ""}`}>
          <BillMeta title="Recibo actual" bill={r.bill} />
          {prev && <BillMeta title="Recibo anterior" bill={prev} />}
        </div>
      </section>

      <section className={card} aria-label="Comprobaciones">
        <h2 className="text-lg font-semibold">Comprobaciones</h2>
        <p className="mb-3 text-xs text-slate-400">Decididas por código (aritmética y continuidad), nunca por la IA.</p>
        {r.checks.length === 0 ? (
          <p className="text-sm text-slate-400">No se realizaron comprobaciones.</p>
        ) : (
          <ul className="space-y-2">
            {r.checks.map((c) => {
              const s = CHECK_STYLE[c.status] ?? CHECK_STYLE.not_checkable;
              return (
                <li key={c.name} className={`flex gap-3 rounded-lg border p-3 ${s.box}`}>
                  <CheckIcon status={c.status} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <p className="font-semibold text-slate-100">{c.label}</p>
                      <span className={`text-xs font-bold uppercase ${s.tag}`}>{s.label}</span>
                    </div>
                    <p className="mt-1 text-sm text-slate-300">{c.detail}</p>
                    {(c.expected != null || c.actual != null) && (
                      <dl className="mt-2 grid gap-1 text-xs sm:grid-cols-2">
                        <div>
                          <dt className="inline text-slate-400">Esperado: </dt>
                          <dd className="inline break-all font-mono text-slate-100">{c.expected ?? "-"}</dd>
                        </div>
                        <div>
                          <dt className="inline text-slate-400">En el recibo: </dt>
                          <dd className={`inline break-all font-mono ${c.status === "mismatch" ? "text-red-300" : "text-slate-100"}`}>{c.actual ?? "-"}</dd>
                        </div>
                      </dl>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {r.oracle_proof ? (
        <ProofSection
          proof={r.oracle_proof}
          canonicalJson={canonical}
          onVerify={canonical ? () => onVerify(canonical, r.oracle_proof!.tx_signature) : undefined}
          extraRows={
            <Row label="Telegram">
              <span className={tg.ok ? "" : "text-red-300"}>{tg.text}</span>
            </Row>
          }
        />
      ) : (
        <section className={card} aria-label="Prueba en Solana">
          <h2 className="text-lg font-semibold">Prueba en Solana</h2>
          <p className="mt-2 text-sm text-amber-300">Esta comparación no se ancló en Solana.</p>
          {canonical && (
            <details className="mt-3 rounded-lg bg-slate-800/50 p-3 text-sm">
              <summary className="cursor-pointer font-medium text-slate-200">Ver JSON canónico</summary>
              <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs text-slate-300">{canonical}</pre>
            </details>
          )}
        </section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------

export function BillCheckPanel({ onVerify, onDone }: { onVerify: (canonical: string, tx: string) => void; onDone: () => void }) {
  const [bill, setBill] = useState<File | null>(null);
  const [prevBill, setPrevBill] = useState<File | null>(null);
  const [meter, setMeter] = useState<File | null>(null);
  const [deviceId, setDeviceId] = useState("");
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BillCheckResult | null>(null);
  const [sent, setSent] = useState({ prev: false, meter: false });
  const abortRef = useRef<AbortController | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!busy) return;
    const start = Date.now();
    const t = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 250);
    return () => clearInterval(t);
  }, [busy]);

  useEffect(() => () => abortRef.current?.abort(), []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    if (!bill) {
      setError("Sube la foto del recibo actual.");
      return;
    }
    const body = new FormData();
    body.set("bill", bill);
    if (prevBill) body.set("previous_bill", prevBill);
    if (meter) body.set("meter", meter);
    if (deviceId.trim()) body.set("device_id", deviceId.trim());
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setSent({ prev: !!prevBill, meter: !!meter });
    setError(null);
    setResult(null);
    setElapsed(0);
    setBusy(true);
    try {
      const res = await apiPost<BillCheckResult>("/api/v1/bill-check", { body, signal: ctrl.signal });
      setResult(res);
      onDone();
      requestAnimationFrame(() => resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
    } catch (err) {
      setError(ctrl.signal.aborted ? "Comparación cancelada." : errorText(err));
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  }

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <form onSubmit={submit} className={`${card} h-fit space-y-4`} aria-label="Comparar recibos">
        <div>
          <h2 className="text-lg font-semibold">Comparar recibos con IA</h2>
          <p className="mt-1 text-sm text-slate-300">
            La IA lee tu recibo (y opcionalmente el anterior y la foto del medidor) y el código comprueba que lecturas, consumo e importe cuadren; el resultado se ancla en Solana.
          </p>
        </div>
        <UploadZone id="bill" title="Recibo actual" file={bill} onFile={(f) => { setError(null); setBill(f); }} onError={setError} required />
        <div className="grid gap-3 sm:grid-cols-2">
          <UploadZone id="previous_bill" title="Recibo anterior" subtitle="Para comprobar continuidad" file={prevBill} onFile={(f) => { setError(null); setPrevBill(f); }} onError={setError} compact />
          <UploadZone id="meter_photo" title="Foto del medidor" subtitle="Para contrastar la lectura" file={meter} onFile={(f) => { setError(null); setMeter(f); }} onError={setError} compact capture />
        </div>
        <div>
          <label htmlFor="bill-device" className={labelCls}>ID del medidor (opcional)</label>
          <input
            id="bill-device"
            list="device-options"
            maxLength={128}
            value={deviceId}
            onChange={(e) => setDeviceId(e.target.value)}
            placeholder="Ej: MED-001"
            className={field}
            aria-describedby="bill-device-hint"
          />
          <p id="bill-device-hint" className="mt-1 text-xs text-slate-400">Si lo indicas, también se usa el historial de ese medidor para contrastar el recibo.</p>
        </div>
        <button type="submit" disabled={busy || !bill} className={`w-full py-3 text-base ${primaryBtn}`}>
          {busy ? `Analizando... ${elapsed} s` : !bill ? "Sube el recibo actual" : "Comparar y anclar en Solana"}
        </button>
      </form>

      <div className="min-w-0 space-y-4" ref={resultRef} aria-live="polite">
        {busy && <BillProgress elapsed={elapsed} hasPrev={sent.prev} hasMeter={sent.meter} onCancel={() => abortRef.current?.abort()} />}
        {error && <Banner tone="red">{error}</Banner>}
        {result && !busy && <BillResult result={result} onVerify={onVerify} />}
        {!result && !busy && !error && (
          <div className="rounded-xl border border-dashed border-slate-700 bg-slate-900/40 p-6 text-sm text-slate-300">
            <p className="text-base font-semibold text-slate-100">Sin comparaciones todavía</p>
            <p className="mt-2">Verás aquí el veredicto, el posible cobro de más, los datos leídos de cada recibo, las comprobaciones y la prueba anclada en Solana.</p>
          </div>
        )}
      </div>
    </div>
  );
}
