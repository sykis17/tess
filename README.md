# TESS Engine

Event-driven AI orchestration engine with multi-agent LangGraph pipelines, WebSocket Panel streaming, and Celery background processing.

**Production:** http://5.78.186.223  
**Repo:** https://github.com/sykis17/tess.git

## Documentation

| Doc | Contents |
|-----|----------|
| [AI_MAP.md](AI_MAP.md) | Full target AI chain, current Phase 10 graph, output-level research concept |
| [ROADMAP.md](ROADMAP.md) | Completed phases 1–10 and planned phases 11–18 |
| [SCHEMA.md](SCHEMA.md) | Panel, AgentTrace, and planned pipeline types |
| [LOCAL_DEV.md](LOCAL_DEV.md) | Windows + Docker Compose + Ollama local setup |
| [deploy/DEPLOY.md](deploy/DEPLOY.md) | Hetzner production deployment |

## Current graph (Phase 10)

```
START → wide_receiver → [parallel: coder | researcher | general_assistant] → presenter → END
```

## Quick start (local)

```bash
cp .env.example .env
docker compose up --build
cd frontend && npm install && npm run dev
```

See [LOCAL_DEV.md](LOCAL_DEV.md) for details.

## Deploy

```bash
ssh root@<server> "cd /opt/tess-engine && git pull && ./deploy/deploy.sh"
```
