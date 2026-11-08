export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ---------------------------------------------------------------------------
// Types: mirror core/schemas.py exactly
// ---------------------------------------------------------------------------

export type Reading = {
  value: number;
  unit: string;
  confidence: number;
  timestamp: string;
  source: string;
  device_id: string | null;
};

export type VisionRead = { value: number | null; unit: string | null; rationale: string | null; error: string | null };

export type Vision = {
  model: string;
  meter_type: string | null;
  obstruction_ratio: number | null;
  votes: number;
  total_reads: number;
  is_mock: boolean;
  rationale: string | null;
  reads: VisionRead[];
};

export type OracleProof = {
  data_hash: string;
  tx_signature: string;
  solscan_url: string;
  memo_payload: string;
  network: string;
  is_simulated: boolean;
  slot: number | null;
  canonical_json: string | null;
  signer: string | null;
};

export type NotificationResult = {
  sent: boolean;
  channel: string;
  recipient: string | null;
  message_id: number | string | null;
  is_mock: boolean;
  error: string | null;
};

export type AnomalyCode = "reading_below_previous" | "unit_mismatch" | "abnormal_jump";
export type LimitPeriod = "day" | "week" | "month";

export type PreviousReading = {
  value: number;
  unit: string;
  timestamp: string;
  tx_signature: string | null;
  is_simulated: boolean;
  origin: "history" | "client";
};

export type ReadingComparison = {
  previous: PreviousReading;
  consumption: number;
  elapsed_hours: number | null;
  daily_rate: number | null;
  typical_daily_rate: number | null;
  anomaly: AnomalyCode | null;
  anomaly_message: string | null;
};

export type ConsumptionLimit = { period: LimitPeriod; limit: number; unit: string };

export type LimitStatus = {
  period: LimitPeriod;
  period_start: string;
  limit: number;
  unit: string;
  used: number;
  percent: number;
  status: "ok" | "warning" | "exceeded";
  projected: number | null;
};

export type HistoryEntry = {
  id: number;
  value: number;
  unit: string;
  timestamp: string;
  source: string;
  confidence: number;
  data_hash: string;
  tx_signature: string;
  is_simulated: boolean;
  consumption: number | null;
  anomaly: AnomalyCode | null;
};

export type DeviceSummary = {
  device_id: string;
  last_value: number;
  unit: string;
  last_timestamp: string;
  count: number;
  anomalies: number;
};

export type DeviceHistory = {
  device_id: string;
  entries: HistoryEntry[];
  limit: ConsumptionLimit | null;
  limit_status: LimitStatus | null;
};

export type ESGCompliance = {
  threshold: number;
  consumption: number;
  is_breach: boolean;
  excess_percentage: number | null;
  status: "COMPLIANT" | "EXCEEDED";
  detail: string;
};

export type AuditResponse = {
  status: "success" | "partial_success" | string;
  reading: Reading;
  oracle_proof: OracleProof;
  notification: NotificationResult;
  execution_time_ms: number;
  vision: Vision | null;
  consumption: number | null;
  comparison: ReadingComparison | null;
  limit_status: LimitStatus | null;
  compliance?: ESGCompliance | null;
};

export type VerifyResult = {
  valid: boolean;
  tx_signature: string;
  computed_hash: string;
  canonical_json: string;
  memo_hash: string | null;
  signer: string | null;
  expected_signer: string | null;
  checks: Partial<Record<"tx_found" | "tx_succeeded" | "memo_found" | "hash_matches" | "signer_matches", boolean>>;
  detail: string;
};

export type BillFields = {
  provider: string | null;
  account_number: string | null;
  meter_serial: string | null;
  period_start: string | null;
  period_end: string | null;
  previous_reading: number | null;
  current_reading: number | null;
  billed_consumption: number | null;
  unit: string | null;
  total_amount: number | null;
  currency: string | null;
  reading_type: "actual" | "estimated" | null;
};

export type BillExtraction = {
  fields: BillFields;
  disputed: string[];
  votes: number;
  total_reads: number;
  model: string;
  image_sha256: string;
  notes: string | null;
  is_mock: boolean;
};

export type BillCheckItem = {
  name: string;
  label: string;
  status: "match" | "mismatch" | "not_checkable";
  expected: string | null;
  actual: string | null;
  detail: string;
};

export type BillCheckResult = {
  bill: BillExtraction;
  previous_bill: BillExtraction | null;
  meter_reading: Reading | null;
  meter_vision: Vision | null;
  checks: BillCheckItem[];
  verdict: "consistent" | "discrepancies" | "inconclusive";
  overcharge_estimate: number | null;
  currency: string | null;
  explanation: string;
  canonical_json: string | null;
  oracle_proof: OracleProof | null;
  notification: NotificationResult | null;
};

// ---------------------------------------------------------------------------
// HTTP
// ---------------------------------------------------------------------------

/** Error with a guaranteed non-empty, human-readable message. */
export class ApiError extends Error {
  constructor(message: string, public status?: number) {
    super(message || "Error desconocido");
  }
}

function detailToText(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail
      .map((d) => {
        if (d && typeof d === "object" && "msg" in d) {
          const loc = "loc" in d && Array.isArray((d as { loc: unknown }).loc) ? (d as { loc: unknown[] }).loc.filter((x) => x !== "body").join(".") : "";
          return `${loc ? `${loc}: ` : ""}${String((d as { msg: unknown }).msg)}`;
        }
        return typeof d === "string" ? d : JSON.stringify(d);
      })
      .join("; ");
  if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message);
  return detail == null ? "" : JSON.stringify(detail);
}

async function request<T>(method: string, path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, { ...init, method });
  } catch {
    throw new ApiError(`No se pudo conectar con el backend en ${API}`);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text().catch(() => "");
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* empty */
  }
  if (res.ok) {
    if (body === null) throw new ApiError(`Respuesta no válida del backend (HTTP ${res.status})`, res.status);
    return body as T;
  }
  const detail = body && typeof body === "object" && "detail" in body ? (body as { detail: unknown }).detail : undefined;
  const msg = detail !== undefined ? detailToText(detail) : text.trim().slice(0, 300);
  throw new ApiError(`HTTP ${res.status}${res.statusText ? ` ${res.statusText}` : ""}${msg ? `: ${msg}` : ""}`, res.status);
}

const json = (data: unknown): RequestInit => ({ headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

export const apiPost = <T>(path: string, init: RequestInit) => request<T>("POST", path, init);
export const apiGet = <T>(path: string) => request<T>("GET", path, { cache: "no-store" });
export const apiPostJson = <T>(path: string, data: unknown) => request<T>("POST", path, json(data));
export const apiPutJson = <T>(path: string, data: unknown) => request<T>("PUT", path, json(data));
export const apiDelete = (path: string) => request<void>("DELETE", path);

export const devicePath = (id: string) => `/api/v1/devices/${encodeURIComponent(id)}`;

export const errorText = (err: unknown) => (err instanceof Error && err.message ? err.message : "Error desconocido");

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

export const short = (s: string | null | undefined, n = 6) => (!s ? "-" : s.length <= n * 2 + 3 ? s : `${s.slice(0, n)}...${s.slice(-n)}`);

export const fmtNum = (v: number | null | undefined, digits = 3) =>
  // es-MX: dot decimals, comma thousands (es-ES rendered 12121 as "12.121", which reads as twelve point one).
  v == null || !Number.isFinite(v) ? "-" : v.toLocaleString("es-MX", { maximumFractionDigits: digits, useGrouping: true });

export const fmtSigned = (v: number, digits = 3) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${fmtNum(Math.abs(v), digits)}`;

export function fmtDate(iso: string | null | undefined, withTime = true): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("es-ES", withTime ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium" });
}

export function fmtElapsed(hours: number | null | undefined): string {
  if (hours == null || !Number.isFinite(hours)) return "desconocido";
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min`;
  if (hours < 48) return `${fmtNum(hours, 1)} h`;
  return `${fmtNum(hours / 24, 1)} días`;
}

export const PERIOD_LABEL: Record<LimitPeriod, string> = { day: "Diario", week: "Semanal", month: "Mensual" };
export const PERIOD_CURRENT: Record<LimitPeriod, string> = { day: "hoy", week: "esta semana", month: "este mes" };

export const ANOMALY_LABEL: Record<AnomalyCode, string> = {
  reading_below_previous: "Lectura menor que la anterior",
  unit_mismatch: "Unidad distinta a la anterior",
  abnormal_jump: "Salto de consumo anormal",
};

export const solscanTx = (sig: string) => `https://solscan.io/tx/${sig}?cluster=devnet`;
