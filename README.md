# TESS Engine

Event-driven AI orchestration engine with multi-agent LangGraph pipelines, WebSocket Panel streaming, and Celery background processing.

**Production:** http://5.78.186.223  
**Repo:** https://github.com/sykis17/tess.git

## Documentation

| Doc | Contents |
|-----|----------|
| [AI_MAP.md](AI_MAP.md) | Full target AI chain, POV agent vision, current implementation |
| [ROADMAP.md](ROADMAP.md) | Completed phases 1–16 and planned phases 17–20 |
| [SCHEMA.md](SCHEMA.md) | Panel, AgentTrace, MayorData, product modes, and planned pipeline types |
| [PHASE_15B_OPENER.md](PHASE_15B_OPENER.md) | Session brief for Phase 15B POV agent matrix |
| [PHASE_16_OPENER.md](PHASE_16_OPENER.md) | Session brief for Phase 16 product modes |
| [LOCAL_DEV.md](LOCAL_DEV.md) | Windows + Docker Compose + Ollama local setup |
| [deploy/DEPLOY.md](deploy/DEPLOY.md) | Hetzner production deployment |

## Current graph (Phase 16 — product modes + POV agents + curator/editor combiners)

Mode selector in the frontend header (`auto`, `research`, `planner`, `coding`, `builder`). Non-auto modes send a JSON WebSocket envelope; plain text remains backward compatible.

```
START → wide_receiver → [parallel: POV agents | coder | researcher | media] + [optional: search]
      → post_fan_in → [combiners or bypass] → defense → presenter → END
```

## Quick start (local)

```bash
cp .env.example .env
docker compose up --build
cd frontend && npm install && npm run dev
```

See [LOCAL_DEV.md](LOCAL_DEV.md) for details.

## Tests

```bash
pip install pytest
pytest tests/test_pov_routing.py tests/test_combiner_utils.py tests/test_product_modes.py
```

Quick smoke script: `python scripts/test_pov_routing.py`

## Deploy

```bash
ssh root@<server> "cd /opt/tess-engine && git pull && ./deploy/deploy.sh"
```
