# Agno App

This directory contains the Agno-based version of the TurboRefi app:

- `backend/` runs the AgentOS backend and document/session APIs
- `frontend/` runs the Next.js chat UI

To use the app locally, start the backend first and then start the frontend.

## Prerequisites

- Python 3.10+
- Node.js and npm
- An OpenAI API key

## Backend Setup

Open a terminal and run:

```bash
cd agno/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Update `agno/backend/.env` and set:

```bash
OPENAI_API_KEY=your_actual_key_here
```

Then start the backend:

```bash
cd agno/backend
source .venv/bin/activate
python playground.py
```

The backend will start on:

```text
http://localhost:7777
```

Notes:

- The app uses `7777` by default.
- You can change the backend port with `PLAYGROUND_PORT` in your environment if needed.
- If you change the backend port, update the frontend endpoint to match.

## Frontend Setup

Open a second terminal and run:

```bash
cd agno/frontend
npm install
npm run dev
```

The frontend will start on:

```text
http://localhost:3000
```

## Run Order

1. Start the backend with `python playground.py`
2. Start the frontend with `npm run dev`
3. Open `http://localhost:3000/` in your browser

## Connecting The UI

The frontend is configured to use:

```text
http://localhost:7777
```

If the UI does not connect automatically:

- make sure the backend is still running
- confirm the endpoint in the left sidebar is `http://localhost:7777`
- if you changed the backend port, update the UI endpoint to the new URL

## Useful Paths

- Backend entry point: `agno/backend/playground.py`
- Backend env file: `agno/backend/.env`
- Frontend app: `agno/frontend`

## Troubleshooting

- If the backend fails at startup, check that `OPENAI_API_KEY` is set correctly.
- If `npm run dev` fails, run `npm install` again inside `agno/frontend`.
- If the frontend loads but cannot talk to the backend, verify that the backend is reachable at `http://localhost:7777`.
