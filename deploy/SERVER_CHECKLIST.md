# Server deploy checklist (Hetzner)

Copy-paste guide for getting code updates and Ollama working on production.

## The flow (every time you change code)

```
Your PC                    GitHub                    Server
  git push    ──────►   sykis17/tess    ◄──────   git pull
                                                      │
                                              ./deploy/deploy.sh
```

**Important:** Editing files on your PC does nothing on the server until you **push** and then **pull** on the server.

---

## One-time server setup

SSH in from your Windows PC:

```bash
ssh root@5.78.186.223
```

### 1. Go to the project

```bash
cd /opt/tess-engine
```

### 2. Create `.env.prod` (only once)

```bash
cp .env.prod.example .env.prod
nano .env.prod
```

Use these values for Ollama testing:

```env
DOMAIN=5.78.186.223
REDIS_URL=redis://redis:6379/0
VITE_WS_BASE_URL=ws://5.78.186.223

DEFAULT_LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=llama3.2

GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.0-flash

# Ops admin (required before any real client data / multi-operator use)
# Prefer: OPS_ADMIN_TOKENS={"jesse":"<strong-secret>"}
OPS_ADMIN_TOKENS=
OPS_ADMIN_TOKEN=
```

Save: `Ctrl+O`, Enter, `Ctrl+X`

**Do not** use `localhost` or `host.docker.internal` for `OLLAMA_BASE_URL` on the server — use `http://ollama:11434` (the Docker service name).

Set at least one of `OPS_ADMIN_TOKENS` / `OPS_ADMIN_TOKEN` before relying on
`/ops` mutations or sensitive reads (fail-closed `503` if both empty). See
[MULTI_CLOUD.md](MULTI_CLOUD.md) admin auth section. Secrets Manager is deferred;
keep tokens in `.env.prod` only (never commit).

### 3. Install Node.js (only once, for frontend build)

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
```

---

## Deploy (every update)

On the server:

```bash
cd /opt/tess-engine
git pull origin main
chmod +x deploy/deploy.sh
./deploy/deploy.sh
```

The script will:
1. Build the frontend
2. Start all Docker containers (including **Ollama inside Docker**)
3. Pull the Ollama model automatically
4. Check `http://5.78.186.223/health`

---

## Verify Ollama works

After deploy, run these on the server:

```bash
cd /opt/tess-engine

# 1. All containers running?
docker compose --env-file .env.prod -f docker-compose.prod.yml ps

# 2. Ollama has the model?
docker compose --env-file .env.prod -f docker-compose.prod.yml exec ollama ollama list

# 3. Worker can reach Ollama?
docker compose --env-file .env.prod -f docker-compose.prod.yml exec worker curl -s http://ollama:11434/api/tags
```

Then open **http://5.78.186.223** in your browser, hard-refresh (`Ctrl+Shift+R`), and send a test message.

First response may take 30–60 seconds while the model loads.

**Multi-POV requests** (e.g. art + ui_design) run 6+ sequential LLM calls. The pipeline allows up to **15 minutes** before timing out. On CPX11 with `llama3.2:1b`, expect several minutes for combiner stages. Phase 21 ships the final answer immediately after defense; follow-up chips may still take extra time unless skipped.

**Phase 21 — skip presenter follow-up LLM (CPX11 fast path):** add to `.env.prod`:

```env
SKIP_LLM_FOLLOW_UPS=true
```

Presenter finishes in seconds after defense with static/topic-fallback chips. Also auto-enabled when `OLLAMA_MODEL` contains `:1b` unless you set `SKIP_LLM_FOLLOW_UPS=false` explicitly.

---

## Common problems

| Symptom | Cause | Fix |
|---------|-------|-----|
| Old UI / stub responses | Browser cache or code not pulled | `git pull` + `./deploy/deploy.sh` + hard refresh |
| `Name or service not known` | Wrong `OLLAMA_BASE_URL` | Set `http://ollama:11434` in `.env.prod`, redeploy |
| `git pull` says "Already up to date" but code is old | Push not done from PC | On PC: `git push origin main`, then pull again |
| Gemini 429 error | Free quota exhausted | Use Ollama (`DEFAULT_LLM_PROVIDER=ollama`) or enable billing |
| Deploy script fails on npm | Node not installed | Install Node.js (one-time setup above) |
| Out of memory / `signal: killed` | CPX11 has 4 GB RAM; llama3.2 is too large | Use `OLLAMA_MODEL=llama3.2:1b`, add swap (see below), redeploy |
| Multi-POV timeout after ~15 minutes | 8+ sequential LLM calls on small hardware | Use `llama3.2:1b`, `SKIP_LLM_FOLLOW_UPS=true`, or simplify prompt |
| Stuck on defense after "Quality checks passed" | Presenter follow-up LLM (Phase 21 ships answer first) | Hard refresh after Phase 21 deploy; or set `SKIP_LLM_FOLLOW_UPS=true` |
| Steer while processing | User sends new message during pipeline | Expected — previous task revoked; wait for new Panel; combiner stages may still take minutes |

---

## View logs when something breaks

```bash
cd /opt/tess-engine
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f worker
```

Press `Ctrl+C` to stop following logs.

---

## Fix OOM: add swap (recommended on 4 GB servers)

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h
```

Then switch to the smaller model and redeploy (see above).

---

## Switch back to Gemini later

Edit `.env.prod`:

```env
DEFAULT_LLM_PROVIDER=gemini
GEMINI_API_KEY=your-key-here
```

Then `./deploy/deploy.sh`.
