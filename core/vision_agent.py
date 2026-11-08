"""
EcoTrust Oracle - Vision Agent Module (Developer 1)
Integrates with Google Generative AI (Gemini 1.5 Flash Vision) to extract analog/digital
industrial meter readings into strict validated JSON data contracts.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from core.config import get_settings
from core.schemas import MeterReading

logger = logging.getLogger("ecotrust.vision")

SYSTEM_INSTRUCTION = """
You are EcoTrust Oracle, a high-precision B2B industrial meter oracle.
Analyze the provided meter photo (analog dials, pointer needle gauges, cyclometer drums, or digital LCD/LED).
Your objective is to extract the current consumption/generation reading.

Return ONLY a valid JSON object with the following fields:
- "value" (float): The numeric meter reading. Read pointers/dials carefully. If multi-dial, read left-to-right.
- "unit" (string): The engineering unit indicated on the faceplate (e.g., "kWh", "m3", "kgCO2", "L", "PSI", "MWh", "kW"). Default to "kWh" if water/electric context suggests, but prefer printed unit.
- "confidence" (float): Estimated confidence between 0.0 and 1.0 based on glare, occlusion, lens blur, and dial legibility.
- "timestamp" (string): ISO 8601 UTC timestamp of reading analysis (e.g. "2026-11-08T01:15:31Z").

Output MUST be raw JSON adhering strictly to:
{
  "value": float,
  "unit": string,
  "confidence": float,
  "timestamp": string
}
No Markdown formatting, no code fences, no explanations.
"""


class VisionExtractionError(Exception):
    """Raised when the vision agent fails to parse or extract meter reading."""
    pass


def _get_mock_meter_reading(reason: str = "Mock fallback enabled") -> MeterReading:
    """
    High-fidelity mock data contract to ensure development and downstream
    modules (Web3 Oracle, Notifier) are never blocked when Gemini API key is missing.
    """
    logger.warning(f"⚠️ [VisionAgent] Utilizing MOCK MeterReading: {reason}")
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return MeterReading(
        value=142.85,
        unit="kWh",
        confidence=0.98,
        timestamp=now_utc,
    )


def _sync_gemini_vision_call(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    custom_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Synchronous worker executed in a thread pool to avoid blocking the asyncio loop.
    Calls google.generativeai Gemini 1.5 Flash Vision.
    """
    import google.generativeai as genai

    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not configured in environment")

    genai.configure(api_key=settings.GEMINI_API_KEY)

    # Configure Gemini 1.5 Flash with JSON schema enforcement
    model = genai.GenerativeModel(
        model_name=settings.GEMINI_MODEL,
        generation_config={
            "temperature": 0.1,  # Low temperature for deterministic meter readout
            "response_mime_type": "application/json",
        },
        system_instruction=SYSTEM_INSTRUCTION,
    )

    prompt = "Inspect this industrial meter and extract the exact reading, unit, confidence, and timestamp."
    if custom_hint:
        prompt += f" Meter operator note / context: {custom_hint}"

    image_part = {
        "mime_type": mime_type,
        "data": image_bytes,
    }

    response = model.generate_content([prompt, image_part])

    if not response or not response.text:
        raise VisionExtractionError("Gemini Vision returned an empty response")

    text_content = response.text.strip()
    # Strip potential markdown formatting if returned
    if text_content.startswith("```json"):
        text_content = text_content[7:]
    if text_content.startswith("```"):
        text_content = text_content[3:]
    if text_content.endswith("```"):
        text_content = text_content[:-3]
    text_content = text_content.strip()

    parsed = json.loads(text_content)
    return parsed


async def read_meter_from_image(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    meter_hint: Optional[str] = None,
) -> MeterReading:
    """
    Main asynchronous entrypoint for the Vision Agent.

    Args:
        image_bytes: Raw bytes of the uploaded meter image.
        mime_type: MIME type of the image (e.g. 'image/jpeg', 'image/png').
        meter_hint: Optional operator hint (e.g. 'Water flowmeter model A-12').

    Returns:
        Validated MeterReading Pydantic instance matching the contract:
        {"value": float, "unit": str, "confidence": float, "timestamp": str}
    """
    settings = get_settings()

    if not settings.GEMINI_API_KEY:
        if settings.VISION_MOCK_FALLBACK:
            return _get_mock_meter_reading(reason="GEMINI_API_KEY not configured")
        raise VisionExtractionError("GEMINI_API_KEY is not configured and VISION_MOCK_FALLBACK=False")

    try:
        # Offload synchronous SDK call to worker thread
        raw_result = await asyncio.to_thread(
            _sync_gemini_vision_call,
            image_bytes=image_bytes,
            mime_type=mime_type,
            custom_hint=meter_hint,
        )

        # Validate with strict Pydantic contract
        reading = MeterReading(
            value=float(raw_result.get("value", 0.0)),
            unit=str(raw_result.get("unit", "kWh")),
            confidence=float(raw_result.get("confidence", 0.85)),
            timestamp=str(raw_result.get("timestamp") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        )
        logger.info(f"✅ [VisionAgent] Successfully extracted reading: {reading.value} {reading.unit} (conf: {reading.confidence})")
        return reading

    except Exception as exc:
        logger.error(f"❌ [VisionAgent] Failed to read meter with Gemini: {exc}", exc_info=True)
        if settings.VISION_MOCK_FALLBACK:
            return _get_mock_meter_reading(reason=f"Gemini API invocation failed: {exc}")
        raise VisionExtractionError(f"Error extracting meter reading from image: {exc}") from exc
