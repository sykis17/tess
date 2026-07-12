# TESS Engine

Event-driven AI orchestration engine with multi-agent LangGraph pipelines, WebSocket Panel streaming, and Celery background processing.

**Production:** http://5.78.186.223  
**Repo:** https://github.com/sykis17/tess.git

## Documentation

| Doc | Contents |
|-----|----------|
| [AI_MAP.md](AI_MAP.md) | Full target AI chain, POV agent vision, current implementation |
| [ROADMAP.md](ROADMAP.md) | Completed phases 1–19 and planned phases 20+ |
| [SCHEMA.md](SCHEMA.md) | Panel, AgentTrace, MayorData, pipeline types, and follow-up fields |
| [PHASE_15B_OPENER.md](PHASE_15B_OPENER.md) | Session brief for Phase 15B POV agent matrix |
| [PHASE_16_OPENER.md](PHASE_16_OPENER.md) | Session brief for Phase 16 product modes |
| [PHASE_17_OPENER.md](PHASE_17_OPENER.md) | Session brief for Phase 17 chain profiles (L0–L4) |
| [PHASE_18_OPENER.md](PHASE_18_OPENER.md) | Session brief for Phase 18 status wall + results wall |
| [PHASE_19_OPENER.md](PHASE_19_OPENER.md) | Session brief for Phase 19 interactive learning UX |
| [LOCAL_DEV.md](LOCAL_DEV.md) | Windows + Docker Compose + Ollama local setup |
| [deploy/DEPLOY.md](deploy/DEPLOY.md) | Hetzner production deployment |

## Current graph (Phase 19 — interactive follow-ups + L0–L4 chain profiles)

Mode and **depth** selectors in the frontend header. Product modes steer intent; chain profiles gate graph depth. The UI includes a **status wall** (live pipeline stage from `pipeline_stage` on Panels), a **virtual folder tree** sidebar, and a **results wall** filtered by `folder_path`. Multi-POV completed Panels expose structured `pov_segments` with **clickable segment titles** for drill-down. Completed Panels show **LLM-generated follow-up chips** (`follow_up_options` + `follow_up_kinds`). List-intent prompts (e.g. "top 10 beaches") render as **ranked numbered lists** when applicable.

```
START → [L0: direct_responder | L1–L4: wide_receiver]
      → [parallel: POV agents | coder | researcher | media] + [optional: search at L3/L4]
      → post_fan_in → [profile gates: presenter | defense | combiners] → presenter → END
```

Compare mode runs the same prompt at 2–3 selected levels; Panels show `output_level` badges.

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
pytest tests/test_pov_routing.py tests/test_combiner_utils.py tests/test_product_modes.py tests/test_chain_profiles.py tests/test_pipeline_stages.py tests/test_pov_segments.py
```

Quick smoke script: `python scripts/test_pov_routing.py`

## Deploy

```bash
ssh root@<server> "cd /opt/tess-engine && git pull && ./deploy/deploy.sh"
```
