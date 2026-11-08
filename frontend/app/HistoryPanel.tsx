"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  ANOMALY_LABEL,
  apiDelete,
  apiGet,
  apiPutJson,
  devicePath,
  errorText,
  fmtDate,
  fmtNum,
  fmtSigned,
  PERIOD_LABEL,
  short,
  solscanTx,
  type DeviceHistory,
  type DeviceSummary,
  type HistoryEntry,
  type LimitPeriod,
} from "./api";
import { LimitBar } from "./LimitBar";
import { Banner, card, CopyButton, field, labelCls, primaryBtn, Spinner } from "./ui";

// ---------------------------------------------------------------------------
// Chart (inline SVG, no dependencies)
// ---------------------------------------------------------------------------

const W = 640;
const H = 240;
const PAD = { l: 60, r: 16, t: 26, b: 34 };

function niceTicks(min: number, max: number, count = 4): number[] {
  if (min === max) return [min];
  const step = (max - min) / count;
  return Array.from({ length: count + 1 }, (_, i) => min + step * i);
}

function HistoryChart({ entries, unit }: { entries: HistoryEntry[]; unit: string }) {
  const [hover, setHover] = useState<number | null>(null);

  const pts = useMemo(() => {
    const times = entries.map((e) => new Date(e.timestamp).getTime());
    const validTime = times.every((t) => Number.isFinite(t));
    const tMin = validTime ? Math.min(...times) : 0;
    const tMax = validTime ? Math.max(...times) : 0;
    const useTime = validTime && tMax > tMin;
    const vals = entries.map((e) => e.value);
    let vMin = Math.min(...vals);
    let vMax = Math.max(...vals);
    if (vMin === vMax) {
      vMin -= Math.abs(vMin) * 0.05 || 1;
      vMax += Math.abs(vMax) * 0.05 || 1;
    } else {
      const pad = (vMax - vMin) * 0.08;
      vMin -= pad;
      vMax += pad;
    }
    const iw = W - PAD.l - PAD.r;
    const ih = H - PAD.t - PAD.b;
    const xOf = (i: number) =>
      PAD.l + (entries.length === 1 ? iw / 2 : useTime ? ((times[i] - tMin) / (tMax - tMin)) * iw : (i / (entries.length - 1)) * iw);
    const yOf = (v: number) => PAD.t + (1 - (v - vMin) / (vMax - vMin)) * ih;
    return {
      list: entries.map((e, i) => ({ x: xOf(i), y: yOf(e.value), e })),
      yTicks: niceTicks(vMin, vMax).map((v) => ({ v, y: yOf(v) })),
      useTime,
    };
  }, [entries]);

  const path = pts.list.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const xLabels = pts.list.length <= 1 ? pts.list : [pts.list[0], ...(pts.list.length > 2 ? [pts.list[Math.floor(pts.list.length / 2)]] : []), pts.list[pts.list.length - 1]];
  const h = hover != null ? pts.list[hover] : null;

  return (
    <div>
      <div className="mb-2 min-h-10 rounded-md bg-slate-950/60 px-3 py-2 text-xs text-slate-300" aria-live="polite">
        {h ? (
          <span>
            <strong className="text-slate-100">{fmtDate(h.e.timestamp)}</strong>: {fmtNum(h.e.value, 4)} {h.e.unit}
            {h.e.consumption != null && <> &middot; consumo {fmtSigned(h.e.consumption)} {h.e.unit}</>}
            {h.e.anomaly && <span className="ml-1 font-semibold text-red-300">&middot; {ANOMALY_LABEL[h.e.anomaly]}</span>}
          </span>
        ) : (
          <span className="text-slate-500">Pasa el cursor o enfoca un punto para ver el detalle.</span>
        )}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={`Lecturas del medidor a lo largo del tiempo, en ${unit}`}>
        {pts.yTicks.map((t, i) => (
          <g key={i}>
            <line x1={PAD.l} x2={W - PAD.r} y1={t.y} y2={t.y} stroke="#1e293b" strokeWidth="1" />
            <text x={PAD.l - 6} y={t.y + 4} textAnchor="end" fontSize="11" fill="#94a3b8">
              {fmtNum(t.v, 1)}
            </text>
          </g>
        ))}
        <text x={PAD.l - 6} y={12} textAnchor="end" fontSize="10" fill="#64748b">
          {unit}
        </text>
        {xLabels.map((p, i) => (
          <text
            key={i}
            x={p.x}
            y={H - 10}
            textAnchor={xLabels.length > 1 && i === 0 ? "start" : xLabels.length > 1 && i === xLabels.length - 1 ? "end" : "middle"}
            fontSize="11"
            fill="#94a3b8"
          >
            {fmtDate(p.e.timestamp, false)}
          </text>
        ))}
        {pts.list.length > 1 && <path d={path} fill="none" stroke="#34d399" strokeWidth="2" strokeLinejoin="round" />}
        {h && <line x1={h.x} x2={h.x} y1={PAD.t} y2={H - PAD.b} stroke="#475569" strokeDasharray="3 3" />}
        {pts.list.map((p, i) => {
          const bad = p.e.anomaly != null;
          const label = `${fmtDate(p.e.timestamp)}: ${fmtNum(p.e.value, 4)} ${p.e.unit}${bad ? ` - ${ANOMALY_LABEL[p.e.anomaly!]}` : ""}`;
          return (
            <g
              key={p.e.id}
              tabIndex={0}
              role="img"
              aria-label={label}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
              className="cursor-pointer focus:outline-none"
            >
              <title>{label}</title>
              <circle cx={p.x} cy={p.y} r="11" fill="transparent" />
              <circle
                cx={p.x}
                cy={p.y}
                r={hover === i ? 6 : bad ? 5 : 3.5}
                fill={bad ? "#ef4444" : "#34d399"}
                stroke={hover === i ? "#f8fafc" : bad ? "#fecaca" : "#022c22"}
                strokeWidth="1.5"
              />
            </g>
          );
        })}
      </svg>
      <div className="mt-1 flex flex-wrap gap-4 text-xs text-slate-400">
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-emerald-400" aria-hidden /> Lectura</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-red-500" aria-hidden /> Lectura sospechosa (anclada como evidencia)</span>
        {!pts.useTime && pts.list.length > 1 && <span>Eje X por orden de lectura</span>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Limit form
// ---------------------------------------------------------------------------

function LimitForm({ history, defaultUnit, onSaved }: { history: DeviceHistory; defaultUnit: string; onSaved: (h: DeviceHistory | null) => void }) {
  const [period, setPeriod] = useState<LimitPeriod>(history.limit?.period ?? "month");
  const [limit, setLimit] = useState(history.limit ? String(history.limit.limit) : "");
  const [unit, setUnit] = useState(history.limit?.unit ?? defaultUnit);
  const [busy, setBusy] = useState<"save" | "delete" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setOk(null);
    const n = Number(limit.replace(",", "."));
    if (!Number.isFinite(n) || n <= 0) {
      setError("El límite debe ser un número mayor que 0.");
      return;
    }
    if (!unit.trim()) {
      setError("Indica la unidad del límite.");
      return;
    }
    setBusy("save");
    try {
      const res = await apiPutJson<DeviceHistory>(`${devicePath(history.device_id)}/limit`, { period, limit: n, unit: unit.trim() });
      onSaved(res);
      setOk("Límite guardado.");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  }

  async function remove() {
    if (!window.confirm(`¿Quitar el límite de consumo de ${history.device_id}?`)) return;
    setError(null);
    setOk(null);
    setBusy("delete");
    try {
      await apiDelete(`${devicePath(history.device_id)}/limit`);
      onSaved(null);
      setOk("Límite eliminado.");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <form onSubmit={save} className="space-y-3" aria-label="Límite de consumo">
      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <label htmlFor="limit-period" className={labelCls}>Período</label>
          <select id="limit-period" value={period} onChange={(e) => setPeriod(e.target.value as LimitPeriod)} className={field}>
            <option value="day">Día</option>
            <option value="week">Semana</option>
            <option value="month">Mes</option>
          </select>
        </div>
        <div>
          <label htmlFor="limit-value" className={labelCls}>Límite</label>
          <input id="limit-value" type="number" step="any" min="0" inputMode="decimal" required value={limit} onChange={(e) => setLimit(e.target.value)} className={field} placeholder="Ej: 300" />
        </div>
        <div>
          <label htmlFor="limit-unit" className={labelCls}>Unidad</label>
          <input id="limit-unit" required maxLength={32} value={unit} onChange={(e) => setUnit(e.target.value)} className={field} />
        </div>
      </div>
      {error && <Banner tone="red">{error}</Banner>}
      {ok && <p className="text-sm text-emerald-300" role="status">{ok}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={busy != null} className={primaryBtn}>
          {busy === "save" ? "Guardando..." : history.limit ? "Actualizar límite" : "Guardar límite"}
        </button>
        {history.limit && (
          <button
            type="button"
            onClick={remove}
            disabled={busy != null}
            className="rounded-md border border-red-500/70 px-4 py-2 text-sm font-semibold text-red-300 hover:bg-red-500/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400 disabled:opacity-50"
          >
            {busy === "delete" ? "Quitando..." : "Quitar límite"}
          </button>
        )}
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------

export function HistoryPanel({
  devices,
  devicesLoading,
  devicesError,
  onReloadDevices,
  selected,
  onSelect,
  refreshKey,
}: {
  devices: DeviceSummary[];
  devicesLoading: boolean;
  devicesError: string | null;
  onReloadDevices: () => void;
  selected: string | null;
  onSelect: (id: string) => void;
  refreshKey: number;
}) {
  const [history, setHistory] = useState<DeviceHistory | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reqId = useRef(0);

  async function load(id: string) {
    const my = ++reqId.current;
    setLoading(true);
    setError(null);
    try {
      const h = await apiGet<DeviceHistory>(`${devicePath(id)}/history?limit=200`);
      if (my === reqId.current) setHistory(h);
    } catch (err) {
      if (my === reqId.current) {
        setHistory(null);
        setError(errorText(err));
      }
    } finally {
      if (my === reqId.current) setLoading(false);
    }
  }

  useEffect(() => {
    if (selected) load(selected);
    else setHistory(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, refreshKey]);

  const device = devices.find((d) => d.device_id === selected) ?? null;
  const entries = history?.device_id === selected ? history.entries : [];
  const unit = device?.unit ?? entries[entries.length - 1]?.unit ?? "";
  const anomalies = entries.filter((e) => e.anomaly).length;
  const sameUnit = entries.length > 1 && entries.every((e) => e.unit === entries[0].unit);
  // Sum of forward steps only: a counter that goes backwards (suspicious reading) must not cancel real consumption.
  const total = sameUnit
    ? entries.slice(1).reduce((acc, e, i) => acc + Math.max(0, e.value - entries[i].value), 0)
    : null;
  const tableRows = [...entries].reverse();

  return (
    <div className="space-y-5">
      <section className={card} aria-label="Medidores">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-lg font-semibold">Medidores</h2>
            <p className="text-sm text-slate-400">Cada auditoría con ID de medidor se guarda aquí y se compara con la anterior.</p>
          </div>
          <button type="button" onClick={onReloadDevices} disabled={devicesLoading} className="rounded-md border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:border-emerald-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 disabled:opacity-50">
            {devicesLoading ? "Cargando..." : "Actualizar"}
          </button>
        </div>
        {devicesError && (
          <div className="mt-3">
            <Banner tone="red">No se pudo cargar la lista de medidores: {devicesError}</Banner>
          </div>
        )}
        {!devicesError && !devicesLoading && devices.length === 0 && (
          <div className="mt-4 rounded-lg border border-dashed border-slate-700 p-6 text-center text-sm text-slate-300">
            <p className="text-base font-semibold text-slate-100">Aún no hay historial</p>
            <p className="mt-1">Audita una foto o una lectura de sensor indicando un <strong>ID del medidor</strong> (por ejemplo MED-001) y aparecerá aquí.</p>
          </div>
        )}
        {devices.length > 0 && (
          <ul className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {devices.map((d) => {
              const active = d.device_id === selected;
              return (
                <li key={d.device_id}>
                  <button
                    type="button"
                    aria-pressed={active}
                    onClick={() => onSelect(d.device_id)}
                    className={`w-full rounded-lg border p-3 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 ${
                      active ? "border-emerald-400 bg-emerald-950/30" : "border-slate-700 bg-slate-950/50 hover:border-slate-500"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="break-all font-mono text-sm font-semibold text-slate-100">{d.device_id}</span>
                      {d.anomalies > 0 ? (
                        <span className="shrink-0 rounded-full bg-red-500/20 px-2 py-0.5 text-xs font-bold text-red-300">
                          {d.anomalies} {d.anomalies === 1 ? "anomalía" : "anomalías"}
                        </span>
                      ) : (
                        <span className="shrink-0 rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-300">sin anomalías</span>
                      )}
                    </div>
                    <p className="mt-2 text-xl font-bold tabular-nums text-emerald-300">
                      {fmtNum(d.last_value, 4)} <span className="text-sm text-slate-300">{d.unit}</span>
                    </p>
                    <p className="mt-1 text-xs text-slate-400">
                      {d.count} {d.count === 1 ? "lectura" : "lecturas"} &middot; última {fmtDate(d.last_timestamp)}
                    </p>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {selected && (
        <>
          {error && <Banner tone="red">No se pudo cargar el historial de {selected}: {error}</Banner>}
          {loading && !history && (
            <div className="flex items-center gap-2 text-sm text-slate-300">
              <Spinner /> Cargando historial de {selected}...
            </div>
          )}
          {history && history.device_id === selected && (
            <>
              <section className={card} aria-label={`Lecturas de ${selected}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h2 className="text-lg font-semibold">
                    Lecturas de <span className="font-mono text-emerald-300">{selected}</span>
                  </h2>
                  {loading && <Spinner />}
                </div>
                <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <div className="rounded-lg border border-slate-800 p-3">
                    <dt className="text-xs uppercase tracking-wide text-slate-400">Lecturas</dt>
                    <dd className="text-lg font-semibold">{entries.length}</dd>
                  </div>
                  <div className="rounded-lg border border-slate-800 p-3">
                    <dt className="text-xs uppercase tracking-wide text-slate-400">Consumo total</dt>
                    <dd className="text-lg font-semibold">{total == null ? "-" : `${fmtSigned(total)} ${entries[0].unit}`}</dd>
                  </div>
                  <div className="rounded-lg border border-slate-800 p-3">
                    <dt className="text-xs uppercase tracking-wide text-slate-400">Anomalías</dt>
                    <dd className={`text-lg font-semibold ${anomalies ? "text-red-300" : ""}`}>{anomalies}</dd>
                  </div>
                  <div className="rounded-lg border border-slate-800 p-3">
                    <dt className="text-xs uppercase tracking-wide text-slate-400">Última</dt>
                    <dd className="text-sm font-semibold">{fmtDate(entries[entries.length - 1]?.timestamp)}</dd>
                  </div>
                </dl>
                <div className="mt-4">
                  {entries.length > 0 ? <HistoryChart entries={entries} unit={unit} /> : <p className="text-sm text-slate-400">Este medidor no tiene lecturas guardadas.</p>}
                </div>
              </section>

              <section className={card} aria-label="Límite de consumo">
                <h2 className="text-lg font-semibold">Límite de consumo</h2>
                <p className="mb-3 text-sm text-slate-400">Al pasar del 80 % se marca como aviso y al 100 % como superado.</p>
                {history.limit_status ? (
                  <div className="mb-4">
                    <LimitBar status={history.limit_status} />
                  </div>
                ) : history.limit ? (
                  <p className="mb-4 text-sm text-slate-300">
                    Límite {PERIOD_LABEL[history.limit.period].toLowerCase()} de {fmtNum(history.limit.limit)} {history.limit.unit}; aún no hay consumo en este período.
                  </p>
                ) : (
                  <p className="mb-4 text-sm text-slate-300">Sin límite configurado.</p>
                )}
                <LimitForm
                  key={selected}
                  history={history}
                  defaultUnit={unit}
                  onSaved={(h) => {
                    if (h) setHistory(h);
                    else load(selected);
                  }}
                />
              </section>

              {entries.length > 0 && (
                <section className={card} aria-label="Tabla de lecturas">
                  <h2 className="mb-3 text-lg font-semibold">Detalle (más reciente primero)</h2>
                  <div className="-mx-5 overflow-x-auto px-5">
                    <table className="w-full min-w-[640px] text-left text-sm">
                      <thead className="text-xs uppercase tracking-wide text-slate-400">
                        <tr className="border-b border-slate-800">
                          <th scope="col" className="py-2 pr-3 font-medium">Fecha</th>
                          <th scope="col" className="py-2 pr-3 text-right font-medium">Valor</th>
                          <th scope="col" className="py-2 pr-3 text-right font-medium">Consumo</th>
                          <th scope="col" className="py-2 pr-3 font-medium">Anomalía</th>
                          <th scope="col" className="py-2 pr-3 font-medium">Prueba</th>
                          <th scope="col" className="py-2 font-medium">Hash</th>
                        </tr>
                      </thead>
                      <tbody>
                        {tableRows.map((e) => (
                          <tr key={e.id} className={`border-b border-slate-800/70 ${e.anomaly ? "bg-red-950/30" : ""}`}>
                            <td className="whitespace-nowrap py-2 pr-3 text-slate-200">{fmtDate(e.timestamp)}</td>
                            <td className="whitespace-nowrap py-2 pr-3 text-right tabular-nums">
                              {fmtNum(e.value, 4)} <span className="text-slate-400">{e.unit}</span>
                            </td>
                            <td className={`whitespace-nowrap py-2 pr-3 text-right tabular-nums ${e.consumption != null && e.consumption < 0 ? "text-red-300" : ""}`}>
                              {e.consumption == null ? "-" : fmtSigned(e.consumption)}
                            </td>
                            <td className="py-2 pr-3">
                              {e.anomaly ? <span className="rounded bg-red-500/20 px-1.5 py-0.5 text-xs font-semibold text-red-300">{ANOMALY_LABEL[e.anomaly] ?? e.anomaly}</span> : <span className="text-slate-500">-</span>}
                            </td>
                            <td className="whitespace-nowrap py-2 pr-3">
                              {e.is_simulated ? (
                                <span className="rounded border border-amber-500/60 px-1.5 py-0.5 text-xs font-bold text-amber-200">SIMULADO</span>
                              ) : (
                                <a href={solscanTx(e.tx_signature)} target="_blank" rel="noreferrer" className="text-emerald-300 underline hover:text-emerald-200" title={e.tx_signature}>
                                  Solscan
                                </a>
                              )}
                            </td>
                            <td className="whitespace-nowrap py-2">
                              <span className="inline-flex items-center gap-2">
                                <code className="text-xs text-slate-300" title={e.data_hash}>{short(e.data_hash, 5)}</code>
                                <CopyButton text={e.data_hash} />
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}
            </>
          )}
        </>
      )}
      {!selected && devices.length > 0 && <Banner tone="slate">Selecciona un medidor para ver su gráfica, sus lecturas y su límite de consumo.</Banner>}
    </div>
  );
}
