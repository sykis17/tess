# TESS Engine — Local Development

This guide covers running the full stack locally on Windows with Docker Compose and Ollama on the host.

## Prerequisites

- Docker Desktop (with `host.docker.internal` support)
- Ollama installed and running on the host
- Node.js 18+ (for the React frontend)

## 1. Set up Ollama

Pull the default model (or the model named in `OLLAMA_MODEL`):

```bash
ollama pull llama3.2
```

Verify Ollama is running:

```bash
curl http://localhost:11434/api/tags
```

## 2. Configure environment

Copy the example env file and adjust if needed:

```bash
cp .env.example .env
```

Key variables for local Ollama:

| Variable | Value |
|----------|-------|
| `DEFAULT_LLM_PROVIDER` | `ollama` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` (host) — Docker Compose overrides this to `http://host.docker.internal:11434` inside containers |
| `OLLAMA_MODEL` | `llama3.2` (or your pulled model) |

## 3. Start the backend stack

```bash
docker compose up --build
```

This starts:
- **web** — FastAPI on `http://localhost:8000`
- **worker** — Celery + LangGraph (calls Ollama via `host.docker.internal`)
- **redis** — broker and Pub/Sub on port `6379`

Health check: `http://localhost:8000/health`

## 4. Start the frontend

In a separate terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` in your browser.

## 5. Verify LLM integration

1. Hard-refresh the browser (`Ctrl+Shift+R`) to clear any stale panels from before a rebuild
2. Use the current Vite URL from the terminal (e.g. `http://localhost:5175`) — not the production server at `5.78.186.223`
3. Send a message such as *"What is 2+2?"*
4. Wait for the response — the **first** Ollama call can take 30–60 seconds while the model loads; a "TESS is thinking…" indicator appears during this time
5. A new Panel should appear with a real LLM answer (not `Task analyzed: ...`)
6. Status should be `completed`, folder path `Assistant/Chat`

If you still see `System/Processing` / `Task analyzed: ...`, that is an **old stub panel** from a previous session — scroll down for newer panels or refresh the page.

## 6. Verify conversation history

1. Ask a question, e.g. *"My favorite color is blue."*
2. Click **"Continue with this"** or ask a follow-up like *"What is my favorite color?"*
3. The response should reference prior context (history is stored in Redis per session)

## Switching to Gemini locally

Set in `.env`:

```
DEFAULT_LLM_PROVIDER=gemini
GEMINI_API_KEY=your-key-here
```

Restart Docker Compose. The `DEFAULT_LLM_PROVIDER=ollama` in `docker-compose.yml` overrides `.env` for containers — remove or change that line in `docker-compose.yml` when testing Gemini locally.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Connection refused` to Ollama | Ensure Ollama is running on the host (`ollama serve` or the desktop app) |
| Model not found | Run `ollama pull <model>` matching `OLLAMA_MODEL` |
| Empty or error Panel | Check worker logs: `docker compose logs worker` |
| Frontend can't connect | Confirm web is up and WS URL is `ws://127.0.0.1:8000` (default in `frontend/.env`) |
