# EcoTrust Oracle — Team Delegation & Developer Action Guide

> **Solana Hackathon (AI Track) — Team of 3 Developers**  
> This document assigns tasks, module boundaries, and implementation roadmaps for the 3 human developers taking over the codebase.

---

## 👥 Team Roles & Module Ownership

| Developer | Primary Responsibility | Primary Files | Upstream / Downstream Dependencies |
|---|---|---|---|
| **Developer 1 (AI Vision)** | Optical character & meter reading extraction | `core/vision_agent.py`, `tests/` | **Upstream:** Raw Image Bytes (`main.py`)<br>**Downstream:** `MeterReading` schema |
| **Developer 2 (Web3 & Blockchain)** | Solana Devnet Memo anchoring & Solscan proofs | `core/web3_oracle.py`, wallet setup | **Upstream:** `MeterReading` schema<br>**Downstream:** `OracleProof` schema |
| **Developer 3 (Orchestration & Comms)** | FastAPI pipeline, Telegram bot, persistence | `main.py`, `core/notifier.py`, `core/config.py` | **Coordinates:** Integrates Dev 1 & Dev 2 modules |

---

## 🛠 Developer 1: AI Vision Engineer (`core/vision_agent.py`)

### Mission
You own the interface between the analog physical world and digital JSON. You must ensure the Vision AI (DeepSeek, Gemini or Claude, auto-detected from `VISION_API_KEY`) reliably interprets diverse industrial meter form-factors.

### Key Deliverables & Immediate Tasks
1. **Multi-Meter Prompt Engineering**:
   - Enhance `SYSTEM_INSTRUCTION` in `core/vision_agent.py` to handle:
     - **Circular Multi-Dial Meters** (e.g., standard water/gas meters with clockwise/counter-clockwise alternating dials).
     - **Odometer/Cyclometer Drum Registers** (black digits for integer units, red digits for decimals).
     - **Digital 7-Segment Displays** (LED/LCD power factor meters).
     - **Pointer needle dial gauges** (pressure gauges in bar/PSI).
2. **Confidence Heuristics**:
   - Calibrate the `confidence` score ($0.0 - 1.0$). If image glare, angle distortion, or dust obscures more than 30% of a dial, flag confidence $< 0.70$.
3. **Image Preprocessing (Optional Performance Boost)**:
   - Use `Pillow` or `OpenCV` to auto-orient EXIF orientation, crop bounding boxes around dial clusters, and normalize contrast before dispatching to the vision model.
4. **Independent Testing**:
   ```bash
   # Run vision unit tests
   uv run pytest tests/test_contracts.py -k "vision"
   ```

### Strict Output Contract (DO NOT BREAK)
Your function `read_meter_from_image(...)` must return a valid `MeterReading` object:
```json
{
  "value": 142.85,
  "unit": "kWh",
  "confidence": 0.98,
  "timestamp": "2026-11-08T01:15:31Z"
}
```

---

## ⛓ Developer 2: Web3 & Solana Engineer (`core/web3_oracle.py`)

### Mission
You own the cryptographic proof-of-auditability on the Solana blockchain. You turn the meter reading into an immutable, publicly verifiable transaction on Solana Devnet.

### Key Deliverables & Immediate Tasks
1. **Solana Devnet Wallet Setup**:
   - Generate a dedicated Solana Devnet keypair for the oracle:
     ```bash
     solana-keygen new --outfile oracle-devnet.json
     solana airdrop 2 $(solana-keygen pubkey oracle-devnet.json) --url devnet
     ```
   - Export the secret key to `.env` as `SOLANA_PRIVATE_KEY` (base58 format or JSON array).
2. **Native Memo Program Integration**:
   - Ensure the transaction embeds the standardized format:
     `EcoTrust:v1:<SHA256_HASH>`
   - Program ID: `MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr`.
   - Verify transaction appearance on [Solscan Devnet](https://solscan.io/?cluster=devnet).
3. **RPC Reliability & Fallbacks**:
   - The public RPC `https://api.devnet.solana.com` can be rate-limited during hackathons.
   - Set up an alternative free RPC endpoint (e.g., QuickNode, Helius, Triton) in `SOLANA_RPC_URL`.
4. **Independent Testing**:
   ```bash
   uv run pytest tests/test_contracts.py -k "web3 or hash"
   ```

### Strict Output Contract (DO NOT BREAK)
Your function `anchor_reading_to_solana(...)` must return an `OracleProof` object:
```json
{
  "data_hash": "e3b0c442...",
  "tx_signature": "5KTpA...",
  "solscan_url": "https://solscan.io/tx/5KTpA...?cluster=devnet",
  "memo_payload": "EcoTrust:v1:e3b0c442...",
  "network": "solana-devnet",
  "is_simulated": false
}
```

---

## 🚀 Developer 3: Orchestrator & Integrations (`main.py` & `core/notifier.py`)

### Mission
You own the end-to-end user experience, the FastAPI pipeline, the Telegram Bot dispatch, and preparation for the hackathon demo.

### Key Deliverables & Immediate Tasks
1. **Telegram Bot Setup**:
   - Speak to [@BotFather](https://t.me/BotFather) on Telegram: create `/newbot` -> Copy `TELEGRAM_BOT_TOKEN`.
   - Get your user or channel chat ID via [@userinfobot](https://t.me/userinfobot) -> Set `TELEGRAM_CHAT_ID` in `.env`.
   - Test message delivery:
     ```bash
     uv run pytest tests/test_contracts.py -k "notifier"
     ```
2. **Orchestrator Endpoints (`main.py`)**:
   - Support multipart/form-data image uploads (`POST /api/v1/audit-meter`).
   - Add database persistence (e.g., SQLite via SQLAlchemy or Tortoise ORM) to store a historical log of ESG audits (`meter_id`, `reading_value`, `hash`, `tx_signature`, `timestamp`).
3. **Frontend / Demo Integration**:
   - Ensure CORS is enabled for frontend connections.
   - The `/docs` Swagger UI is pre-configured for live judge demonstrations.
   - Support mobile camera capture directly into the API.

---

## ⚡ Quickstart Guide for the Team

### 1. Prerequisites
Ensure `uv` is installed:
```bash
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Environment Setup
```bash
# 1. Create and sync the virtual environment
uv venv
uv pip install -e .

# 2. Configure credentials
cp .env.example .env
# Edit .env with your keys (or leave default for instant Mock Fallback!)
```

### 3. Run the Backend Server
```bash
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
* **Interactive OpenAPI Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
* **Health Check**: [http://localhost:8000/health](http://localhost:8000/health)

### 4. Execute Full Test Suite
```bash
uv run pytest -v
```

---

## 🏆 Hackathon Demo Pitch Script (3 Minutes)

1. **The Problem (30s)**: "Enterprise ESG metrics are recorded manually on clipboards. Greenwashing is rampant because auditors cannot verify analog physical meters."
2. **The Solution (45s)**: "EcoTrust Oracle connects physical infrastructure directly to Solana. An operator takes a single picture of an analog dial."
3. **Live Demo (60s)**:
   - Upload a photo of a boiler flowmeter via `/api/v1/audit-meter`.
   - Show the Vision AI (e.g. DeepSeek) parsing the dial with confidence score in the response.
   - Click the live Solscan URL in the response or Telegram message.
   - Show the Solana Devnet transaction containing the SHA-256 Memo proof.
4. **The Impact (45s)**: "Zero smart contract deployment fees, instant auditability, tamper-proof corporate ESG compliance on Solana."
