"""
EcoTrust Oracle - Data Contracts & Schemas
Defines strict Pydantic models for data interchange between modules:
Vision Agent -> Web3 Oracle -> Notifier -> Orchestrator (FastAPI).
"""

from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator


class MeterReading(BaseModel):
    """
    Contract 1: Output of core/vision_agent.py & Input to core/web3_oracle.py.
    Represents the verified ESG meter reading extracted via AI vision.
    """
    value: float = Field(
        ...,
        allow_inf_nan=False,  # NaN/Infinity cannot be hashed reproducibly, so they never reach the chain
        description="Numerical reading value read from analog dial or digital display (e.g. 142.85)",
        examples=[142.85],
    )
    unit: str = Field(
        ...,
        min_length=1,
        max_length=32,
        description="Standardized physical unit: kWh, m3, kgCO2, L, PSI, etc.",
        examples=["kWh"],
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score of the optical character/meter reading (0.0 to 1.0)",
        examples=[0.98],
    )
    timestamp: str = Field(
        ...,
        description="ISO 8601 UTC timestamp of the meter reading capture (e.g. 2026-11-08T01:15:31Z)",
        examples=["2026-11-08T01:15:31Z"],
    )
    source: str = Field(
        default="ai_vision",
        description="Provenance of reading: 'ai_vision' (analog camera), 'iot_sensor' (USB/serial/MQTT), or 'scada'",
        examples=["ai_vision", "iot_sensor"],
    )
    device_id: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Physical asset ID, sensor serial number, or meter tag (e.g. 'SENSOR-MODBUS-042')",
        examples=["SENSOR-MODBUS-042"],
    )

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        """Ensure timestamp is valid ISO format."""
        try:
            # Check parsing
            if v.endswith("Z"):
                datetime.fromisoformat(v.replace("Z", "+00:00"))
            else:
                datetime.fromisoformat(v)
            return v
        except Exception:
            # Fallback to normalized UTC string
            return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def to_canonical_dict(self) -> dict:
        """Returns the dictionary with keys sorted for deterministic hashing."""
        canonical = {
            "confidence": round(float(self.confidence), 4),
            "source": self.source.strip().lower(),
            "timestamp": self.timestamp,
            "unit": self.unit.strip().upper(),
            "value": round(float(self.value), 4),
        }
        if self.device_id:
            canonical["device_id"] = str(self.device_id).strip()
        return canonical


class OracleProof(BaseModel):
    """
    Contract 2: Output of core/web3_oracle.py.
    Contains the cryptographic anchor details on the Solana Devnet blockchain.
    """
    data_hash: str = Field(
        ...,
        description="Deterministic SHA-256 hexadecimal digest of the canonical MeterReading JSON",
        examples=["e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"],
    )
    tx_signature: str = Field(
        ...,
        description="Base58 Solana Devnet transaction signature",
        examples=["5KTpA...vM9X"],
    )
    solscan_url: str = Field(
        ...,
        description="Direct URL to verify the transaction and Memo on Solscan Devnet",
        examples=["https://solscan.io/tx/5KTpA...vM9X?cluster=devnet"],
    )
    memo_payload: str = Field(
        ...,
        description="Plaintext string anchored in the Solana Memo program instruction",
        examples=["EcoTrust:v1:SHA256:e3b0c442..."],
    )
    network: str = Field(
        default="solana-devnet",
        description="Target blockchain network",
    )
    is_simulated: bool = Field(
        default=False,
        description="Indicates whether transaction was simulated due to missing wallet funds/offline RPC",
    )
    slot: Optional[int] = Field(
        default=None,
        description="Solana block slot containing the confirmed transaction",
    )
    canonical_json: Optional[str] = Field(
        default=None,
        description="Exact UTF-8 string that was SHA-256 hashed, so anyone can recompute data_hash",
    )
    signer: Optional[str] = Field(
        default=None,
        description="Base58 public key of the oracle wallet that signed the anchor transaction",
    )


class VerifyRequest(BaseModel):
    """Input of POST /api/v1/verify: the reading a third party claims was anchored, and the transaction."""
    reading: MeterReading
    tx_signature: str = Field(..., min_length=32, max_length=128)


class VerifyResult(BaseModel):
    """Output of core/web3_oracle.verify_anchor: independent re-check of an anchored reading."""
    valid: bool = Field(..., description="True only if every check passed")
    tx_signature: str
    computed_hash: str = Field(..., description="SHA-256 recomputed by the server from the submitted reading")
    canonical_json: str = Field(..., description="Exact string that was hashed")
    memo_hash: Optional[str] = Field(default=None, description="Hash found in the on-chain EcoTrust memo")
    signer: Optional[str] = Field(default=None, description="Fee payer / signer of the transaction")
    expected_signer: Optional[str] = Field(default=None, description="This oracle's public key")
    checks: Dict[str, bool] = Field(
        default_factory=dict,
        description="tx_found, tx_succeeded, memo_found, hash_matches, signer_matches",
    )
    detail: str = Field(default="", description="Human-readable explanation of the result")


class NotificationResult(BaseModel):
    """
    Contract 3: Output of core/notifier.py.
    Status of the Telegram ESG notification delivery.
    """
    sent: bool = Field(
        ...,
        description="True if message was delivered to Telegram or successfully mocked",
    )
    channel: str = Field(
        default="telegram",
        description="Communication medium used",
    )
    recipient: Optional[str] = Field(
        default=None,
        description="Telegram Chat ID or handle where notification was sent",
    )
    message_id: Optional[Union[str, int]] = Field(
        default=None,
        description="Telegram message ID assigned by Telegram Bot API",
    )
    is_mock: bool = Field(
        default=False,
        description="True if mock fallback was triggered (e.g. no token configured)",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error detail if delivery failed",
    )


class VisionRead(BaseModel):
    """One of the independent vision reads behind the consensus."""
    value: Optional[float] = None
    unit: Optional[str] = None
    rationale: Optional[str] = Field(default=None, description="How the model reached this value (dials/drums/digits it saw)")
    error: Optional[str] = Field(default=None, description="Why this read failed, if it did")


class VisionAnalysis(BaseModel):
    """
    How the vision agent reached the reading. Reported next to the reading, never hashed,
    so the anchored MeterReading contract stays unchanged.
    """
    model: str = Field(..., description="Vision model that actually answered (after any fallback), or 'mock'")
    meter_type: Optional[str] = Field(default=None, description="multi_dial | cyclometer | seven_segment | needle_gauge | other")
    obstruction_ratio: Optional[float] = Field(default=None, description="Fraction of the reading area hidden by glare, dust or cropping")
    votes: int = Field(..., description="Independent reads that agreed on the reported value")
    total_reads: int = Field(..., description="Independent reads attempted")
    is_mock: bool = Field(default=False, description="True when no vision API key is configured and a synthetic reading was used")
    rationale: Optional[str] = Field(default=None, description="Model's explanation for the winning reading")
    reads: List[VisionRead] = Field(default_factory=list, description="Every independent read, including dissenting or failed ones")


class VerifyPayloadRequest(BaseModel):
    """Input of POST /api/v1/verify-payload: any anchored canonical JSON (e.g. a bill check) and its transaction."""
    canonical_json: str = Field(..., min_length=2, max_length=100_000)
    tx_signature: str = Field(..., min_length=32, max_length=128)


# ---------------------------------------------------------------------------
# History, comparison with the previous reading, consumption limits
# ---------------------------------------------------------------------------

AnomalyCode = Literal["reading_below_previous", "unit_mismatch", "abnormal_jump"]
LimitPeriod = Literal["day", "week", "month"]


class PreviousReading(BaseModel):
    """The reading this audit is compared against."""
    value: float
    unit: str
    timestamp: str
    tx_signature: Optional[str] = None
    is_simulated: bool = False
    origin: Literal["history", "client"] = Field(
        default="history",
        description="'history' = last stored reading of this device; 'client' = previous_value sent with the request",
    )


class ReadingComparison(BaseModel):
    """Current vs previous reading of a cumulative meter. Suspicious readings are still anchored, but flagged."""
    previous: PreviousReading
    consumption: float = Field(..., description="current value - previous value (negative means the counter went backwards)")
    elapsed_hours: Optional[float] = Field(default=None, description="Hours between both readings (None if unknown)")
    daily_rate: Optional[float] = Field(default=None, description="Consumption per 24 h over the elapsed time")
    typical_daily_rate: Optional[float] = Field(default=None, description="Median daily rate of this device's history")
    anomaly: Optional[AnomalyCode] = Field(default=None, description="Why this reading looks altered or wrong, if it does")
    anomaly_message: Optional[str] = Field(default=None, description="Spanish explanation of the anomaly")


class ConsumptionLimit(BaseModel):
    """Consumption budget for one device and period (body of PUT /api/v1/devices/{device_id}/limit)."""
    period: LimitPeriod
    limit: float = Field(..., gt=0, allow_inf_nan=False)
    unit: str = Field(..., min_length=1, max_length=32)


class LimitStatus(BaseModel):
    """How much of the period budget is used. warning >= 80 %, exceeded >= 100 %."""
    period: LimitPeriod
    period_start: str = Field(..., description="ISO 8601 UTC start of the current period")
    limit: float
    unit: str
    used: float = Field(..., description="Consumption since the period started")
    percent: float = Field(..., description="used / limit * 100")
    status: Literal["ok", "warning", "exceeded"]
    projected: Optional[float] = Field(default=None, description="Projected consumption at the end of the period")


class HistoryEntry(BaseModel):
    """One stored audit of a device."""
    id: int
    value: float
    unit: str
    timestamp: str
    source: str
    confidence: float
    data_hash: str
    tx_signature: str
    is_simulated: bool
    consumption: Optional[float] = None
    anomaly: Optional[AnomalyCode] = None


class DeviceSummary(BaseModel):
    """Row of GET /api/v1/devices."""
    device_id: str
    last_value: float
    unit: str
    last_timestamp: str
    count: int
    anomalies: int = Field(default=0, description="Stored readings flagged as anomalous")


class DeviceHistory(BaseModel):
    """GET /api/v1/devices/{device_id}/history: readings oldest first, plus the limit and its status."""
    device_id: str
    entries: List[HistoryEntry]
    limit: Optional[ConsumptionLimit] = None
    limit_status: Optional[LimitStatus] = None


# ---------------------------------------------------------------------------
# Bill check: utility bill vs previous bill and/or meter photo
# ---------------------------------------------------------------------------

class BillFields(BaseModel):
    """Fields read from a utility bill. A field is None when it is absent or the reads did not agree."""
    provider: Optional[str] = None
    account_number: Optional[str] = None
    meter_serial: Optional[str] = None
    period_start: Optional[str] = Field(default=None, description="ISO date YYYY-MM-DD")
    period_end: Optional[str] = Field(default=None, description="ISO date YYYY-MM-DD")
    previous_reading: Optional[float] = None
    current_reading: Optional[float] = None
    billed_consumption: Optional[float] = None
    unit: Optional[str] = None
    total_amount: Optional[float] = None
    currency: Optional[str] = None
    reading_type: Optional[Literal["actual", "estimated"]] = Field(default=None, description="Real meter reading or utility estimate")


class BillExtraction(BaseModel):
    """AI extraction of one bill, with per-field consensus over independent reads."""
    fields: BillFields
    disputed: List[str] = Field(default_factory=list, description="Fields the independent reads did not agree on (set to None)")
    votes: int = Field(..., description="Reads that returned usable JSON")
    total_reads: int
    model: str
    image_sha256: str = Field(..., description="SHA-256 of the uploaded bill image bytes")
    notes: Optional[str] = Field(default=None, description="Model's observations about the bill (Spanish)")
    is_mock: bool = False


class BillCheckItem(BaseModel):
    """One arithmetic/consistency check. Decided by code, never by the model."""
    name: str = Field(..., description="Stable id, e.g. 'consumption_arithmetic', 'meter_vs_bill', 'continuity'")
    label: str = Field(..., description="Spanish title for the UI")
    status: Literal["match", "mismatch", "not_checkable"]
    expected: Optional[str] = None
    actual: Optional[str] = None
    detail: str = Field(..., description="Spanish explanation")


class BillCheckResult(BaseModel):
    """POST /api/v1/bill-check output."""
    bill: BillExtraction
    previous_bill: Optional[BillExtraction] = None
    meter_reading: Optional[MeterReading] = None
    meter_vision: Optional[VisionAnalysis] = None
    checks: List[BillCheckItem]
    verdict: Literal["consistent", "discrepancies", "inconclusive"]
    overcharge_estimate: Optional[float] = Field(default=None, description="Estimated amount billed in excess, computed by code")
    currency: Optional[str] = None
    explanation: str = Field(..., description="Plain-language Spanish summary (written by the model from the code's checks)")
    canonical_json: Optional[str] = Field(default=None, description="Exact string hashed and anchored on Solana")
    oracle_proof: Optional[OracleProof] = None
    notification: Optional[NotificationResult] = None


class AuditResponse(BaseModel):
    """
    Contract 4: Output of main.py orchestrator endpoint POST /api/v1/audit-meter.
    Complete audit trail combining AI extraction, on-chain proof, and notification.
    """
    status: str = Field(
        default="success",
        description="Workflow status: success | partial_success | error",
    )
    reading: MeterReading = Field(
        ...,
        description="Extracted and validated meter data",
    )
    oracle_proof: OracleProof = Field(
        ...,
        description="On-chain Solana proof details",
    )
    notification: NotificationResult = Field(
        ...,
        description="Telegram dispatch confirmation",
    )
    execution_time_ms: float = Field(
        ...,
        description="Total orchestrator pipeline execution latency in milliseconds",
    )
    vision: Optional[VisionAnalysis] = Field(
        default=None,
        description="AI vision analysis details (photo audits only)",
    )
    consumption: Optional[float] = Field(
        default=None,
        description="Same as comparison.consumption (kept for older clients)",
    )
    comparison: Optional[ReadingComparison] = Field(
        default=None,
        description="Comparison with the previous reading of this device (history or client-provided)",
    )
    limit_status: Optional[LimitStatus] = Field(
        default=None,
        description="Consumption limit status of this device after this reading",
    )


class HealthResponse(BaseModel):
    """System health and integration readiness check."""
    status: str = "ok"
    version: str
    gemini_ready: bool
    solana_ready: bool
    telegram_ready: bool
    network: str
