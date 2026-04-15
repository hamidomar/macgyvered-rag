# TurboRefi

TurboRefi is a localhost-first refinance screening app. The current target build
is focused on:

- UC1: W-2 employee rate-term refinance
- UC2: W-2 employee PMI removal refinance
- JSON-first startup from pre-normalized mortgage/property data
- deterministic Python calculations, LARS scoring, handoff packaging, and
  deterministic FNMA/FHLMC guide retrieval
- a Next.js chat/upload frontend for the loan-officer workflow

The legacy mortgage-statement upload path still exists, but the new UC1/UC2
flow should start from received JSON.

## Project Layout

- `src/turborefi/api.py`: FastAPI product API.
- `src/turborefi/services/session_service.py`: session orchestration.
- `src/turborefi/services/received_input.py`: received JSON adapter.
- `src/turborefi/services/calculations/`: deterministic UC1/UC2 formulas.
- `src/turborefi/services/lars_engine.py`: UC1/UC2 LARS scoring and handoff.
- `src/turborefi/services/information_firewall.py`: LOA-safe state redaction.
- `src/turborefi/services/retrieval_service.py`: deterministic `guide_tool`
  wrapper for FNMA/FHLMC retrieval.
- `frontend/`: Next.js client.
- `example_json_inputs/`: sample received JSON files.
- `new_docs/`: product/specification documents.
- `plan_minimal.md`: current implementation plan for UC1/UC2.

## Setup

From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
```

Edit `.env`:

```bash
OPENAI_API_KEY=sk-...
PLAYGROUND_PORT=7777
SCREENING_NEW_RATE=6.0
FNMA_INDEX_DIR=/absolute/path/to/macgyvered-rag/retrival/output/selling_guide_preprocessed
FHLMC_INDEX_DIR=/absolute/path/to/macgyvered-rag/retrival/output/sf_guide_index
```

`OPENAI_API_KEY` is needed for the legacy OCR/agent paths. The UC1/UC2
JSON-first calculations are deterministic, but the backend still initializes the
AgentOS app. `SCREENING_NEW_RATE` is the default refinance rate assumption used
for demo/screening savings calculations when a request does not send `new_rate`.

## Run The Backend

```bash
source .venv/bin/activate
python3 playground.py
```

The backend runs at:

```text
http://localhost:7777
```

Useful endpoints:

- `POST /session/from-json`: start the new UC1/UC2 received-JSON flow.
- `POST /session/{session_id}/document-json`: add structured document data.
- `POST /session/{session_id}/message`: send borrower answers.
- `GET /session/{session_id}/status`: inspect state, LARS, missing docs, and
  calculated outputs.
- `GET /session/{session_id}/result`: get the recommendation packet.
- `GET /refi/sessions`: list persisted sessions.
- `GET /refi/sessions/{session_id}`: get full session detail.
- `POST /ingest`: legacy PDF/image upload path.

Verifier endpoints remain available for the legacy path, but the UC1/UC2 target
flow does not use the Verifier Agent.

## Run The Frontend

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open:

```text
http://localhost:3000
```

The frontend defaults to the backend at `http://localhost:7777`.

Current UI behavior:

- The chat UI supports legacy file upload and chat.
- There is backend/hook support for JSON-first sessions.
- There is not yet a visible "paste JSON here" screen in the UI.

So for received JSON today, use the API examples below. A small JSON import
panel can be added later on top of the existing frontend hook.

## How Received JSON Input Works

The upstream system provides the mortgage/property data as JSON. You do not need
to upload or OCR a mortgage statement for the UC1/UC2 flow.

The API accepts either:

```json
{
  "payload": {
    "core": {},
    "profile": {},
    "statement": {},
    "raw": {},
    "formDecisions": {},
    "propertyLookup": {}
  },
  "new_rate": 6.0,
  "session_name": "High Rate FHA"
}
```

or the raw received JSON object directly. The wrapper form is recommended
because it lets you pass `new_rate`.

`new_rate` is the screening refinance rate assumption used for new payment,
savings, PITIA, and break-even calculations. If omitted, the backend uses
`SCREENING_NEW_RATE`, which defaults to `6.0`. The frontend also exposes this as
`Screening rate` before a JSON session is started. It is not part of the received
mortgage statement data and does not affect UC1/UC2 classification.

Important behavior:

- `statement.borrowerName` is stored only outside LOA-visible state.
- The LOA-facing session uses a tokenized borrower id.
- The app maps `core.balance`, `core.rate`, `core.paymentBreakdown`,
  `core.propertyAddress`, and `propertyLookup.estimatedValue` into internal
  received fields.
- One property address and one property value are used.
- B11 API divergence is audit-only because there is no multi-source valuation.
- UC2 U2.1 uses the single-LTV borderline band: `0.73 <= ltv <= 0.77`.

## Start A JSON Session

Using `jq` with one of the sample inputs:

```bash
jq -n \
  --argfile payload "example_json_inputs/High Rate FHA.json" \
  '{payload: $payload, new_rate: 6.0, session_name: "High Rate FHA"}' \
| curl -s http://localhost:7777/session/from-json \
  -H 'Content-Type: application/json' \
  --data-binary @-
```

The response includes a `session_id`:

```json
{
  "session_id": "...",
  "response": "...",
  "current_phase": "awaiting_docs",
  "use_case": "uc2_pmi_removal",
  "state_machine_state": "S2_DOCS",
  "lars_result": {},
  "handoff_package": null,
  "tool_trace": []
}
```

Save the `session_id` for later calls.

Without `jq`, use Postman/Insomnia/curl and paste this shape into the body:

```json
{
  "payload": {
    "...": "paste the full JSON from example_json_inputs here"
  },
  "new_rate": 6.0,
  "session_name": "Manual test"
}
```

## Send Borrower Answers

```bash
curl -s http://localhost:7777/session/<SESSION_ID>/message \
  -H 'Content-Type: application/json' \
  -d '{
    "message": "I am around 740, I have been with my employer for 7 years, it is my only income, single-family home."
  }'
```

For UC2, borrower answers can include PMI and second-lien details:

```bash
curl -s http://localhost:7777/session/<SESSION_ID>/message \
  -H 'Content-Type: application/json' \
  -d '{
    "message": "The PMI is not clear, I think it may be built into the rate. I bought the home for $350,000 and put $35,000 down. No HELOC."
  }'
```

## Add Structured Documents

Use `document-json` when document extraction is already done or when testing.

Paystub:

```bash
curl -s http://localhost:7777/session/<SESSION_ID>/document-json \
  -H 'Content-Type: application/json' \
  -d '{
    "doc_type": "paystub",
    "data": {
      "employer_name": "Acme Manufacturing",
      "gross_this_period": 3846.15,
      "pay_frequency": "biweekly",
      "ytd_gross": 25000,
      "pay_period_end_date": "2026-03-31",
      "base_pay": 3846.15,
      "overtime_pay": 0,
      "bonus_pay": 0,
      "commission_pay": 0
    }
  }'
```

W-2:

```bash
curl -s http://localhost:7777/session/<SESSION_ID>/document-json \
  -H 'Content-Type: application/json' \
  -d '{
    "doc_type": "w2",
    "data": {
      "employer_name": "Acme Manufacturing",
      "wages_box1": 98000,
      "tax_year": 2024,
      "employer_ein": "12-3456789"
    }
  }'
```

Tax bill:

```bash
curl -s http://localhost:7777/session/<SESSION_ID>/document-json \
  -H 'Content-Type: application/json' \
  -d '{"doc_type": "tax_bill", "data": {"tax_bill_annual": 5400}}'
```

Insurance declaration:

```bash
curl -s http://localhost:7777/session/<SESSION_ID>/document-json \
  -H 'Content-Type: application/json' \
  -d '{"doc_type": "insurance", "data": {"insurance_annual": 1800}}'
```

Government ID marker:

```bash
curl -s http://localhost:7777/session/<SESSION_ID>/document-json \
  -H 'Content-Type: application/json' \
  -d '{"doc_type": "identity", "data": {"document_present": true}}'
```

UC1/UC2 requires two paystubs, two W-2s, a tax bill, insurance, and ID. UC2 may
also use a PMI statement or closing disclosure when PMI type or purchase price
is unclear.

## Check Status And Result

Status:

```bash
curl -s http://localhost:7777/session/<SESSION_ID>/status | jq
```

Result:

```bash
curl -s http://localhost:7777/session/<SESSION_ID>/result | jq
```

The status/result payloads include:

- `use_case`
- `state_machine_state`
- `documents_received`
- `documents_pending`
- `received_mortgage`
- `screening_assumptions`
- `calculated_outputs`
- `lars_result`
- `handoff_package`
- `source_data_warnings`

## Legacy Upload Flow

The older flow still starts with a mortgage statement file:

```bash
curl -s http://localhost:7777/ingest \
  -F "file=@/path/to/mortgage_statement.pdf"
```

Then upload supporting PDFs/images through `/ingest` with `session_id`, or use
the frontend upload button.

This path still supports the legacy verifier endpoints:

- `POST /session/{session_id}/verify`
- `GET /session/{session_id}/verification`

## Tests

Run backend tests:

```bash
source .venv/bin/activate
pytest -q
```

Run frontend formatting checks on touched files:

```bash
cd frontend
npx prettier --check src/api/turborefi.ts src/types/turborefi.ts src/hooks/useTurboRefiSession.ts src/store.ts
```

Frontend typecheck currently has existing Markdown renderer type errors outside
the TurboRefi files:

```bash
cd frontend
npm run typecheck
```

## Current Implementation Notes

- UC1/UC2 are the active target.
- UC3/UC4/UC5/UC6 are deferred.
- Compliance Agent/TCS is deferred.
- Verifier Agent is not part of the UC1/UC2 JSON-first target path.
- Property valuation is single-address, single-value for now.
- The LOA-visible session excludes borrower name, profession, occupation, job
  title, protected-class fields, and compliance-only fields.
