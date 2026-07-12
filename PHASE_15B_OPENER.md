# TESS Engine — Phase 15B Session Opening Message

## Context

Phases 1–15 are complete and deployed. Phase 15 shipped subject agent **scaffolding** with an interim `*_major`/`*_minor` **depth-tier** model. Production is live at latest `3782b56`.

**Important:** Phase 15 misinterpreted "major/minor." The intended design is **point-of-view (POV) agents** — disciplinary lenses on the same question, not deep vs brief variants of one subject.

| Wrong (Phase 15) | Right (Phase 15B) |
|------------------|-------------------|
| `chemistry_major` = deep chemistry | `chemistry` = chemistry **POV** |
| `chemistry_minor` = brief chemistry | `art` = art **POV** on a design question |
| One subject, two depths | Multiple disciplines, one synthesized answer |

**Example:** *"Design a user interface for a science app"* → WR alarms `art` (aesthetics, composition) + `ui_design` (patterns, usability) + optional `coder` (implementation) → combiners weave POV segments → defense keeps output reasonable → presenter.

Architecture docs: [AI_MAP.md](AI_MAP.md), [ROADMAP.md](ROADMAP.md), [SCHEMA.md](SCHEMA.md).

---

## Production

| Item | Value |
|------|-------|
| URL | http://5.78.186.223 (HTTP/IP mode) |
| Repo | https://github.com/sykis17/tess.git |
| Server path | `/opt/tess-engine` — deploy with `git pull && ./deploy/deploy.sh` |
| Local | Docker Compose + Ollama on Windows host; frontend `npm run dev` |

---

## Goal for Phase 15B: POV agent matrix

Replace `*_major`/`*_minor` depth pairs with **one POV agent per discipline**. WR routes questions to 1–3 relevant **perspectives**; combiners synthesize cross-POV answers; defense caps length and keeps output safe and aligned.

### Target graph (same shape, corrected agent semantics)

```
WR → [parallel: POV agents (chemistry, biology, economics, art, ui_design, …)]
   + [optional: coder | photo | video | audio | search]
   → post_fan_in → combiners (when multi-POV) → defense → presenter
```

### Starter POV catalog (recommended first deploy)

| POV key | Discipline lens | `folder_path` | Example question facet |
|---------|-----------------|---------------|------------------------|
| `chemistry` | Scientific / chemical | `Science/Chemistry` | Bonding, reactions, materials |
| `biology` | Life science | `Science/Biology` | Cells, ecosystems, physiology |
| `economics` | Markets / systems | `Social Studies/Economics` | Cost, incentives, trade-offs |
| `art` | Visual / aesthetic | `Arts/Visual` | Composition, color, style |
| `ui_design` | UX / interface | `Design/UI` | Layout, usability, patterns |

Tool/media agents stay separate: `coder`, `general_assistant`, `photo`, `video`, `audio`, `researcher` (off-matrix fallback).

---

## What's working (Phase 15 baseline to reuse)

| Concept | Behavior |
|---------|----------|
| Subject registry | `app/agents/subjects/registry.py` — extend for POV, not depth |
| Agent packages | `config.py` + `prompt.py` per agent |
| Graph factory | `builder.py` auto-wires specialists from `AGENT_REGISTRY` |
| Combiner bypass | `len(active_agents) <= 1` (not mayor_data length) |
| Fan-in join | `expected_fan_in_branches` / `fan_in_branches_done` |
| Defense | Single LLM, three checks; `review_passed` before `completed` |
| 3-agent cap | WR capped at 3 parallel agents + optional search |
| Keyword fallback | Media override pattern — extend for POV correction |

---

## Known issues to fix in 15B

| Issue | Notes |
|-------|-------|
| Depth-tier model | `*_major`/`*_minor` encode wrong abstraction — remove or migrate |
| WR misroutes on small model | e.g. "ionic bonding" → `biology_minor` instead of `chemistry` |
| Subject override gap | Override only fires for `researcher`/`general_assistant`, not wrong topic agent |
| `MayorData.depth` | Replace with `pov` as primary lens metadata |
| Combiner prompts | Must explicitly weave POV segments, not just cross-topic prose |

---

## Deliverables

| Area | Work |
|------|------|
| POV packages | One agent per discipline under `app/agents/<pov_key>/` |
| Registry | Replace depth pairs; `agent_kind: "pov"`; `pov` field on `AgentConfig` |
| Remove / migrate | Deprecate `chemistry_major`, `chemistry_minor`, etc. |
| `MayorData` | Add `pov: str`; combiner headers show lens |
| WR prompt | Route perspectives, not depth; auto-generate from POV registry |
| Routing fallback | Correct WR when wrong POV chosen (not only researcher/GA) |
| Combiner prompts | Cross-POV synthesis instructions |
| Defense | Length cap + learning-assumption guidance in review prompt |
| Frontend | POV display names; optional POV badges on segments |
| Docs | Update AI_MAP, SCHEMA, ROADMAP; mark 15B complete |
| Deploy | Commit + production deploy |

---

## Test matrix (Phase 15B)

| Input | Expected pipeline | Notes |
|-------|-------------------|-------|
| "Explain ionic bonding" | WR → `chemistry` → bypass → defense | Must NOT route to biology |
| "Design a science app UI — cover look and usability" | WR → `art` + `ui_design` → combiners → defense | Core POV example |
| "Compare renewable energy economics and chemistry" | WR → `economics` + `chemistry` → combiners | Multi-POV factual |
| "Explain supply and demand and sketch a diagram plan" | WR → `economics` + `photo` → combiners | POV + media |
| "What is Kubernetes?" | WR → `researcher` (fallback) | Off-matrix regression |
| "Hey, how are you?" | WR → `general_assistant` only | Casual regression |
| "Write a Python sort function" | WR → `coder` only | Tool regression |

Verify: processing Panel shows POV badges; `MayorData.pov` populated; combiners label segments by lens; ionic bonding never hits biology.

---

## Out of scope for Phase 15B (future phases)

| Phase | Feature |
|-------|---------|
| 16 | Product modes (research, planner, coding, builder) |
| 17 | Output levels L0–L4 |
| 18 | Pipeline status wall + results wall from folder tree |
| 19 | Click title → drill down; context-related/deviating questions; list formats (top 10); 4 choice themes |
| 20 | Token streaming |

---

## Constraints

- Follow `.cursorrules` (async, Pydantic, Celery for heavy work, modular structure)
- CPX11 / `llama3.2:1b` — keep starter POV count small (5 agents)
- English for user-facing text and comments
- Backward-compatible Panels — new fields optional
- Visibility first: POV nodes write `AgentTrace` and appear in `agents_involved`
- Never return `{}` from nodes
- Fan-in branches report to `fan_in_branches_done`
- Combiner bypass uses `len(active_agents) <= 1`

---

## Key files (Phase 15 baseline)

| Area | Path |
|------|------|
| Graph | `app/graph/builder.py` |
| WR routing | `app/graph/nodes/wide_receiver.py`, `app/graph/routing.py`, `app/graph/prompts.py` |
| Subject/POV registry | `app/agents/subjects/registry.py` |
| Agent registry | `app/agents/registry.py` |
| MayorData | `app/graph/schemas.py` |
| Combiners | `app/graph/combiner_utils.py`, `app/graph/nodes/combiner_mayor.py` |
| Defense | `app/graph/nodes/defense_review.py` |
| Frontend | `frontend/src/types/panel.ts`, `frontend/src/components/PanelCard.tsx` |

---

## Request

Please review [AI_MAP.md](AI_MAP.md), [SCHEMA.md](SCHEMA.md), and [ROADMAP.md](ROADMAP.md) before starting.

**Goal:** Implement Phase 15B POV agent matrix, fix routing override gap, migrate off depth-tier agents, commit + deploy.

---

## Completion (Phase 15B — shipped)

Phase 15B is complete. Summary of what shipped:

| Area | Status |
|------|--------|
| POV agent matrix | Five lenses: `chemistry`, `biology`, `economics`, `art`, `ui_design` |
| Depth-tier removal | `*_major`/`*_minor` fully migrated off |
| `MayorData.pov` | Live on all POV agent output |
| Routing override | Keyword fallback corrects, merges, and **prunes** wrong POV agents |
| Combiner prompts | Cross-POV synthesis with POV headers; fallbacks preserve lens labels |
| Defense | Length cap guidance in review prompt |
| Frontend | POV badges persist through combiner/defense stages |
| Multi-POV reliability | Celery + client timeout raised to **720s**; pre-LLM progress panels; per-node timing logs |
| Tests | `tests/test_pov_routing.py` — full Phase 15B routing matrix |

**Known limits (future phases):**

- No token streaming (Phase 20) — long combiner stages show progress text only
- Multi-POV on CPX11 with `llama3.2:1b` can take several minutes; 12-minute pipeline cap
- `pov_sources` reflects routing intent, not per-segment synthesis attribution

**Verify locally:**

```bash
pytest tests/test_pov_routing.py
```

**Canonical multi-POV test prompt:** *"Design a science app UI covering aesthetics and usability"* → `art` + `ui_design` → combiners → defense → presenter.

---

## Glossary

| Term | Meaning |
|------|---------|
| POV agent | Disciplinary lens (chemistry, art, ui_design) — answers from that field's perspective |
| Tool agent | Non-POV specialist: coder, general_assistant, researcher |
| Media specialist | photo, video, audio |
| Mayor data | Raw per-agent output; POV agents set `pov` + `topic` |
| Combiner | Synthesizes multiple POV segments into one answer |
| Defense | QA gate; keeps output reasonable, safe, aligned — user wants to keep learning but not overwhelmed |
