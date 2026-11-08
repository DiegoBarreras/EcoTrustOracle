const DEFAULT_API =
  typeof window !== "undefined" && window.location.hostname === "localhost"
    ? "http://localhost:8000"
    : "https://ecotrustoracle.onrender.com";

export const API = (process.env.NEXT_PUBLIC_API_URL || DEFAULT_API).replace(/\/+$/, "");

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

export type ESGCompliance = {
  threshold: number;
  consumption: number;
  is_breach: boolean;
  excess_percentage: number | null;
  status: "COMPLIANT" | "EXCEEDED";
  detail: string;
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

export async function apiPost<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, { method: "POST", ...init });
  } catch (netErr) {
    throw new ApiError(`No se pudo conectar con el backend (${API}): ${netErr instanceof Error ? netErr.message : String(netErr)}`);
  }
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* empty */
  }
  if (!res.ok) {
    const detail = body && typeof body === "object" && "detail" in body ? (body as { detail: unknown }).detail : null;
    const conflict =
      res.status === 409 && detail && typeof detail === "object" && "code" in detail && (detail as { code: unknown }).code === "reading_below_previous"
        ? (detail as unknown as Conflict)
        : undefined;
    throw new ApiError(detailToText(detail) || `El servidor respondió con HTTP ${res.status}`, conflict);
  }
  return body as T;
}

export const short = (s: string | null | undefined, head = 6, tail = 4) =>
  !s ? "—" : s.length <= head + tail + 3 ? s : `${s.slice(0, head)}…${s.slice(-tail)}`;
