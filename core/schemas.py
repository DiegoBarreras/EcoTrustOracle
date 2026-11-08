"""
EcoTrust Oracle - Data Contracts & Schemas
Defines strict Pydantic models for data interchange between modules:
Vision Agent -> Web3 Oracle -> Notifier -> Orchestrator (FastAPI).
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Union
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
        description="reading.value - previous_value, when the client sent the previous counter reading",
    )


class HealthResponse(BaseModel):
    """System health and integration readiness check."""
    status: str = "ok"
    version: str
    gemini_ready: bool
    solana_ready: bool
    telegram_ready: bool
    network: str
