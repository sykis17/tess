# TESS Engine — Production Deployment (Hetzner)

This guide covers provisioning a Hetzner VPS, configuring environment variables, and deploying the full stack with Docker Compose and Caddy.

## Architecture

- **Caddy** — TLS termination (Let's Encrypt), static frontend, WebSocket proxy to FastAPI
- **web** — FastAPI + WebSocket (`/ws/{session_id}`)
- **worker** — Celery + LangGraph
- **redis** — internal broker, result backend, and Pub/Sub (not exposed publicly)

```
Browser (HTTPS/WSS)
    → Caddy :443
        → /*           → frontend/dist (React SPA)
        → /ws/*        → web:8000 (WebSocket upgrade)
        → /health      → web:8000
    → worker → Redis → Panels streamed back via WebSocket
```

## Prerequisites

- A domain name with DNS managed by you
- A Hetzner Cloud account
- SSH key pair for server access
- Gemini API key (`GEMINI_API_KEY`)

## 1. Create a Hetzner VPS

1. In [Hetzner Cloud Console](https://console.hetzner.cloud/), create a server:
   - **Type:** CX22 or CPX11 (2 vCPU, 4 GB RAM recommended)
   - **Image:** Ubuntu 24.04
   - **Authentication:** SSH key (no root password login)
2. Note the server's public IPv4 address.

## 2. Initial server setup

SSH into the server as root:

```bash
ssh root@YOUR_SERVER_IP
```

### Create a deploy user

```bash
adduser deploy
usermod -aG sudo deploy
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy
```

Log in as the deploy user:

```bash
ssh deploy@YOUR_SERVER_IP
```

### Configure firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

Only ports **22**, **80**, and **443** should be open to the internet.

## 3. Install Docker

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "${VERSION_CODENAME}") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

sudo usermod -aG docker deploy
```

Log out and back in so the `docker` group applies.

Verify:

```bash
docker --version
docker compose version
```

## 4. Configure DNS

Create an **A record** pointing your domain to the server IP:

| Type | Name | Value |
|------|------|-------|
| A | `tess` (or `@`) | `YOUR_SERVER_IP` |

Wait for DNS propagation before deploying. Let's Encrypt requires the domain to resolve to this server.

## 5. Clone the repository

```bash
sudo mkdir -p /opt/tess-engine
sudo chown deploy:deploy /opt/tess-engine
git clone https://github.com/YOUR_ORG/tess-engine.git /opt/tess-engine
cd /opt/tess-engine
```

Replace the clone URL with your actual repository remote.

## 6. Configure environment

Copy the production env template and edit it:

```bash
cp .env.prod.example .env.prod
nano .env.prod
```

### Required variables

| Variable | Description |
|----------|-------------|
| `DOMAIN` | Public hostname (e.g. `tess.example.com`) — used by Caddy for TLS |
| `GEMINI_API_KEY` | Google Gemini API key |
| `REDIS_URL` | Keep default `redis://redis:6379/0` for Docker Compose |
| `DEFAULT_LLM_PROVIDER` | Set to `gemini` for production |
| `GEMINI_MODEL` | Gemini model name (default `gemini-2.0-flash`) |
| `VITE_WS_BASE_URL` | Must be `wss://YOUR_DOMAIN` (same host as the SPA) |

Example:

```env
DOMAIN=tess.example.com
GEMINI_API_KEY=your-key-here
REDIS_URL=redis://redis:6379/0
DEFAULT_LLM_PROVIDER=gemini
GEMINI_MODEL=gemini-2.0-flash
VITE_WS_BASE_URL=wss://tess.example.com
```

**Important:** `VITE_WS_BASE_URL` is baked into the frontend at build time. It must use `wss://` and match your `DOMAIN` so the browser connects to `wss://tess.example.com/ws/{sessionId}`.

Never commit `.env.prod` — it is listed in `.gitignore`.

### Optional variables (Ollama)

Ollama is optional in production. To use it on the same host, install Ollama on the server and set:

```env
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=llama3.2
DEFAULT_LLM_PROVIDER=ollama
```

Add `extra_hosts: ["host.docker.internal:host-gateway"]` to `web` and `worker` in `docker-compose.prod.yml` if needed.

## 7. Install Node.js (for frontend build)

The deploy script builds the frontend on the server before starting containers:

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
node --version
npm --version
```

## 8. Deploy

From the repository root:

```bash
chmod +x deploy/deploy.sh
./deploy/deploy.sh
```

The script will:

1. Load `.env.prod`
2. Build the frontend with `VITE_WS_BASE_URL`
3. Run `docker compose -f docker-compose.prod.yml up -d --build`
4. Verify `https://$DOMAIN/health`

### Re-deploy after code changes

```bash
git pull
./deploy/deploy.sh
```

## 9. Verification checklist

After deploy, confirm:

- [ ] `https://YOUR_DOMAIN` serves the React app
- [ ] `https://YOUR_DOMAIN/health` returns `{"status":"ok","redis":"ok"}`
- [ ] WebSocket connects at `wss://YOUR_DOMAIN/ws/{sessionId}`
- [ ] Sending a message produces a Panel (folder_path, status, markdown, follow_up_options)
- [ ] Redis port 6379 is **not** reachable from the public internet

Test WebSocket with browser DevTools → Network → WS, or:

```bash
curl -fsS https://YOUR_DOMAIN/health
```

## Operations

### View logs

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f caddy web worker
```

### Restart a service

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml restart web
```

### Stop the stack

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml down
```

### Service status

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
```

## Local development vs production

| | Development | Production |
|---|-------------|------------|
| Compose file | `docker-compose.yml` | `docker-compose.prod.yml` |
| Command | `docker compose up` | `./deploy/deploy.sh` |
| Hot reload | Yes (`--reload`, bind mounts) | No |
| TLS | No | Caddy + Let's Encrypt |
| Frontend | `npm run dev` in `frontend/` | Built static assets in `frontend/dist/` |
| Redis exposure | Port 6379 on host | Internal only |

## Troubleshooting

### Caddy fails to obtain TLS certificate

- Confirm DNS A record points to the server IP
- Ensure ports 80 and 443 are open (`sudo ufw status`)
- Check Caddy logs: `docker compose ... logs caddy`

### WebSocket connection fails

- Confirm `VITE_WS_BASE_URL` was `wss://YOUR_DOMAIN` at build time
- Re-run `./deploy/deploy.sh` after changing the domain or WS URL
- Verify Caddy proxies `/ws/*` (see `deploy/Caddyfile`)

### Health check returns 503

- Redis may not be ready: `docker compose ... logs redis`
- Check web logs: `docker compose ... logs web`

### Worker not processing tasks

- Check worker logs: `docker compose ... logs worker`
- Verify `GEMINI_API_KEY` is set in `.env.prod`
- Confirm worker health: `docker compose ... ps`

## Windows developers

Run the deploy script from WSL or Git Bash on the server. For local frontend development, use `frontend/.env` with `VITE_WS_BASE_URL=ws://127.0.0.1:8000`.
