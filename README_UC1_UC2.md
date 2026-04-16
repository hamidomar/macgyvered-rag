# TurboRefi UC1 / UC2 Quick Start

This is the minimal local flow for the current JSON-first build.

## 1. Create the Python environment

From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Then add your OpenAI key in `.env`:

```bash
OPENAI_API_KEY=sk-...
```

## 2. Start the backend

From the repo root:

```bash
source .venv/bin/activate
python3 playground.py
```

Backend API:

```text
http://localhost:7777
```

## 3. Start the frontend

In a second terminal:

```bash
source .venv/bin/activate
cd frontend
npm install
npm run dev
```

Frontend:

```text
http://localhost:3000
```

## 4. Create a UC1 session from JSON

### macOS / Linux / WSL / Git Bash

### UC1 unclean

```bash
jq -n \
  --argfile payload "example_json_inputs/inputs/uc1_parma.json" \
  '{payload: $payload, new_rate: 6.0, session_name: "UC1 unclean"}' \
| curl -s http://localhost:7777/session/from-json \
  -H 'Content-Type: application/json' \
  --data-binary @-
```

### UC1 clean

```bash
jq -n \
  --argfile payload "example_json_inputs/inputs/uc1_north_olmsted.json" \
  '{payload: $payload, new_rate: 6.0, session_name: "UC1 clean"}' \
| curl -s http://localhost:7777/session/from-json \
  -H 'Content-Type: application/json' \
  --data-binary @-
```

### Windows PowerShell

The `jq` commands above are shell-style commands for macOS/Linux. On Windows,
use PowerShell like this instead.

#### UC1 unclean

```powershell
$payload = Get-Content "example_json_inputs/inputs/uc1_parma.json" -Raw | ConvertFrom-Json
$body = @{
  payload = $payload
  new_rate = 6.0
  session_name = "UC1 unclean"
} | ConvertTo-Json -Depth 20

Invoke-RestMethod `
  -Uri "http://localhost:7777/session/from-json" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

#### UC1 clean

```powershell
$payload = Get-Content "example_json_inputs/inputs/uc1_north_olmsted.json" -Raw | ConvertFrom-Json
$body = @{
  payload = $payload
  new_rate = 6.0
  session_name = "UC1 clean"
} | ConvertTo-Json -Depth 20

Invoke-RestMethod `
  -Uri "http://localhost:7777/session/from-json" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

## 5. Refresh the frontend

After creating the session with `jq`, refresh the frontend.

You should then see the session in the sidebar and can continue the flow from the UI.

## Notes

- This build is focused on `UC1` and `UC2`.
- The app now starts from received JSON, not mortgage-statement upload.
- `new_rate` is a screening assumption used for savings/payment estimates.
- If you change backend code, restart `python3 playground.py`.
