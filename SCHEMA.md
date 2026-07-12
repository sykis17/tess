# TESS Engine — Data Schemas

Strictly typed data via Pydantic models in Python. This document covers **live** schemas (Phase 11) and **planned** types for the full AI chain.

---

## 1. Panel (live — WebSocket payload)

Streamed to the frontend when a processing segment completes or updates.

```json
{
  "panel_id": "uuid4",
  "folder_path": "Coding/Projects",
  "status": "processing | review_passed | completed",
  "content_type": "markdown | code | image",
  "content": "The actual payload",
  "follow_up_options": ["Continue with this", "Change style", "Discard"],
  "agents_involved": ["Wide Receiver", "Coder", "Presenter"],
  "agent_traces": [
    {
      "agent_name": "wide_receiver",
      "inputs_seen": ["user_input", "conversation_history (2 turns)"],
      "task_summary": "Write a Python sort function",
      "output_preview": "Routed to: coder — Write a Python sort function"
    }
  ]
}
```

### Panel fields

| Field | Type | Status | Description |
|-------|------|--------|-------------|
| `panel_id` | `str` | Live | Stable ID; processing → completed updates reuse it |
| `folder_path` | `str` | Live | Virtual folder (e.g. `Science/Chemistry`) |
| `status` | enum | Live | `processing`, `review_passed`, `completed` |
| `content_type` | enum | Live | `markdown`, `code`, `image` |
| `content` | `str` | Live | Payload body |
| `follow_up_options` | `list[str]` | Live | Quick-reply buttons |
| `agents_involved` | `list[str]` | Live (Phase 9) | Human-readable agent pipeline |
| `agent_traces` | `list[AgentTrace]` | Live (Phase 9) | Per-agent visibility records |

Clients should treat missing optional fields as empty lists.

### Live Panel fields (Phase 12)

| Field | Type | Status | Description |
|-------|------|--------|-------------|
| `data_tier` | `str` | Live (Phase 12) | `mayor`, `micro`, `usable`, `final` — for intermediate stream Panels |

### Planned Panel fields

| Field | Type | Phase | Description |
|-------|------|-------|-------------|
| `output_level` | `str` | 17 | Chain profile used (`L0`–`L4`) for research comparison |
| `product_mode` | `str` | 16 | `research`, `planner`, `coding`, `builder` |

---

## 2. AgentTrace (live)

Per-agent visibility record accumulated during graph execution.

| Field | Type | Description |
|-------|------|-------------|
| `agent_name` | `str` | Registry key (e.g. `wide_receiver`, `coder`) |
| `inputs_seen` | `list[str]` | Summary of context received |
| `task_summary` | `str \| null` | Task from WR routing |
| `output_preview` | `str \| null` | First ~200 chars of output |

---

## 3. RoutingDecision (live)

Wide Receiver routing JSON. Supports 1–3 agents per message (capped at 3) and 0–1 search queries.

```json
{
  "active_agents": ["coder", "researcher"],
  "current_task": "Compare Python async patterns and explain photosynthesis",
  "search_queries": ["photosynthesis mechanism 2024"]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `active_agents` | `list[str]` | 1–3 registered specialist agent names |
| `current_task` | `str` | Concise task summary for specialists |
| `search_queries` | `list[str]` | 0–1 web search queries for resource finder |

### Planned extensions (Phase 16+)

```json
{
  "active_agents": ["chemistry_major", "economics_minor", "photo"],
  "current_task": "Compare renewable energy economics and chemistry",
  "search_queries": ["renewable energy cost trends 2025"],
  "product_mode": "research",
  "chain_profile": "L4"
}
```

| Field | Phase | Description |
|-------|-------|-------------|
| `product_mode` | 16 | Research / planner / coding / builder |
| `chain_profile` | 17 | Output level L0–L4 |

---

## 4. Data pipeline types

Internal graph state types for the full chain. `MayorData` is live in Phase 10–11; `MicroData` and `UsableAnswer` are live in Phase 12.

### MayorData (live — Phase 10–11)

Raw output from a topic agent, specialist, or search reader. Stored in graph state via reducer; merged by Presenter. `resource_reader` populates `citations`.

```json
{
  "source_agent": "resource_reader",
  "topic": "Web sources",
  "depth": null,
  "content": "### Article title\n\nExtracted excerpt...",
  "citations": ["[Article title](https://example.com/article)"]
}
```

### MicroData (live — Phase 12)

Combiner Mayor output — cross-topic synthesis.

```json
{
  "combiner": "mayor",
  "segments": [
    { "title": "Cross-topic comparison", "content": "..." }
  ],
  "source_agents": ["chemistry_major", "economics_minor"]
}
```

### UsableAnswer (live — Phase 12)

Combiner Micro output — refined segment ready for collection.

```json
{
  "segment_id": "uuid4",
  "order_hint": 1,
  "title": "Introduction",
  "content": "...",
  "review_status": "pending"
}
```

### DefenseReview (live — Phase 13)

QA verdict per answer segment from Defense Review.

```json
{
  "segment_id": "uuid4",
  "checks": {
    "big_picture": "pass",
    "detail": "pass",
    "implication": "revise"
  },
  "notes": "Clarify long-term environmental implication.",
  "verdict": "revise"
}
```

Graph state fields (Phase 13):

| Field | Type | Description |
|-------|------|-------------|
| `defense_reviews` | `list[DefenseReview]` | Latest review results per segment |
| `defense_retry_count` | `int` | Bounded retry counter (max 2) |
| `defense_notes` | `str` | Aggregated revise notes injected into retry prompts |

---

## 5. Search types (live — Phase 11)

### SearchResult

```json
{
  "query": "photosynthesis mechanism",
  "url": "https://example.com/article",
  "title": "Article title",
  "excerpt": "Relevant extracted text",
  "reader_agent": "resource_reader"
}
```

### Search configuration (env)

| Variable | Default | Description |
|----------|---------|-------------|
| `TAVILY_API_KEY` | (empty) | When set, Tavily is preferred over DuckDuckGo |
| `SEARCH_MAX_URLS` | `3` | Max URLs per query |
| `SEARCH_FETCH_TIMEOUT_SECONDS` | `15` | Per-page fetch timeout |

---

## 6. Chain profiles (planned — Phase 17)

User-selectable output levels for research and benchmarking.

| Profile | Graph | LLM calls (typical) |
|---------|-------|---------------------|
| `L0` | Direct LLM → Presenter | 1 |
| `L1` | WR → specialist → Presenter | 2 |
| `L1+` | WR → parallel specialists → Presenter | 2–4 |
| `L2` | L1 + Defense | 3+ |
| `L3` | L2 + Search | 4+ |
| `L4` | Full parallel chain | 6+ |

Request carries `chain_profile`; response Panels include `output_level` for side-by-side comparison UI.

---

## 7. Worker error envelope (live)

```json
{
  "type": "error",
  "message": "Human-readable error description"
}
```
