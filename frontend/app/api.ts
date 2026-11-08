export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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

export type AuditResponse = {
  status: "success" | "partial_success";
  reading: Reading;
  oracle_proof: {
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
  notification: {
    sent: boolean;
    channel: string;
    recipient: string | null;
    message_id: number | string | null;
    is_mock: boolean;
    error: string | null;
  };
  execution_time_ms: number;
  vision: Vision | null;
  consumption: number | null;
};

export type VerifyResult = {
  valid: boolean;
  tx_signature: string;
  computed_hash: string;
  canonical_json: string;
  memo_hash: string | null;
  signer: string | null;
  expected_signer: string | null;
  checks: Record<"tx_found" | "tx_succeeded" | "memo_found" | "hash_matches" | "signer_matches", boolean>;
  detail: string;
};

export type Conflict = { message: string; previous_value: number; value: number };

/** Error with a guaranteed non-empty message; `conflict` is set for 409 reading_below_previous. */
export class ApiError extends Error {
  constructor(message: string, public conflict?: Conflict) {
    super(message || "Error desconocido");
  }
}

function detailToText(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : JSON.stringify(d)))
      .join("; ");
  if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message);
  return detail == null ? "" : JSON.stringify(detail);
}

export async function apiPost<T>(path: string, init: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, { method: "POST", ...init });
  } catch {
    throw new ApiError(`No se pudo conectar con el backend en ${API}`);
  }
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (res.ok) {
    if (body === null) throw new ApiError(`Respuesta no válida del backend (HTTP ${res.status})`);
    return body as T;
  }
  const detail = body && typeof body === "object" && "detail" in body ? (body as { detail: unknown }).detail : undefined;
  if (res.status === 409 && detail && typeof detail === "object" && (detail as { code?: unknown }).code === "reading_below_previous") {
    const d = detail as Conflict;
    throw new ApiError(d.message || "La lectura es menor que la anterior", d);
  }
  const msg = detail !== undefined ? detailToText(detail) : text.trim().slice(0, 300);
  throw new ApiError(`HTTP ${res.status}${res.statusText ? ` ${res.statusText}` : ""}${msg ? `: ${msg}` : ""}`);
}

export const short = (s: string | null | undefined, n = 6) => (!s ? "-" : s.length <= n * 2 + 3 ? s : `${s.slice(0, n)}...${s.slice(-n)}`);
