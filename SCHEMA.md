# TESS Engine — Data Schemas

Strictly typed data via Pydantic models in Python. This document covers **live** schemas through Phase 20 (`is_streaming` token deltas, mid-chain steer).

---

## 1. Panel (live — WebSocket payload)

Streamed to the frontend when a processing segment completes or updates.

```json
{
  "panel_id": "uuid4",
  "folder_path": "Coding/Projects",
  "status": "processing | review_passed | completed",
  "content_type": "markdown | code | image | audio | video",
  "content": "The actual payload",
  "follow_up_options": ["Who is the target audience?", "Compare to gaming app UI", "Sketch wireframes next"],
  "follow_up_kinds": ["related", "deviating", "choice"],
  "content_format": "ranked_list",
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
| `content_type` | enum | Live | `markdown`, `code`, `image`, `audio`, `video` |
| `content` | `str` | Live | Payload body — see content conventions below |
| `follow_up_options` | `list[str]` | Live | Quick-reply chip labels; LLM-generated on completed Panels (Phase 19); falls back to defaults on error |
| `agents_involved` | `list[str]` | Live (Phase 9) | Human-readable agent pipeline |
| `agent_traces` | `list[AgentTrace]` | Live (Phase 9) | Per-agent visibility records |

Clients should treat missing optional fields as empty lists.

### Content conventions (Phase 14)

| `content_type` | `content` format |
|----------------|------------------|
| `markdown` | Markdown prose (default for text, scripts, plans) |
| `code` | Source code string |
| `image` | HTTP(S) URL or `data:` URI |
| `video` | HTTP(S) URL to video file, or markdown script fallback |
| `audio` | HTTP(S) URL to audio file, or markdown script fallback |

Media specialist agents use `folder_path` values: `Media/Photo`, `Media/Video`, `Media/Audio`.

### Live Panel fields (Phase 12)

| Field | Type | Status | Description |
|-------|------|--------|-------------|
| `data_tier` | `str` | Live (Phase 12) | `mayor`, `micro`, `usable`, `final` — for intermediate stream Panels |

### Live Panel fields (Phase 15B–16)

| Field | Type | Status | Description |
|-------|------|--------|-------------|
| `pov_sources` | `list[str]` | Live (Phase 15B) | Disciplinary lenses on processing, combiner, defense, and completed Panels (e.g. `["Chemistry", "Art"]`) |
| `product_mode` | `str \| null` | Live (Phase 16) | Active intent profile: `research`, `planner`, `coding`, `builder`; omitted or `null` for `auto` |
| `output_level` | `str \| null` | Live (Phase 17) | Chain profile used (`L0`–`L4`) for compare UI |
| `pipeline_stage` | `str \| null` | Live (Phase 18) | Current chain stage for status wall (`routing`, `agents`, `combining`, `defense`, `presenting`, `done`) |
| `pov_segments` | `list[PanelSegment]` | Live (Phase 18) | Structured per-lens sections on completed Panels |

### Live Panel fields (Phase 19)

| Field | Type | Status | Description |
|-------|------|--------|-------------|
| `content_format` | `str \| null` | Live (Phase 19) | `markdown` or `ranked_list` when list intent detected; omitted for default markdown |
| `follow_up_kinds` | `list[str]` | Live (Phase 19) | Parallel to `follow_up_options`: `related`, `deviating`, `choice`, `drill_down` for chip styling |

### Live Panel fields (Phase 20)

| Field | Type | Status | Description |
|-------|------|--------|-------------|
| `is_streaming` | `bool` | Live (Phase 20) | When `true`, `content` is a **delta** appended to the in-flight Panel with the same `panel_id`; omitted or `false` for full replacement |

### PanelSegment (live — Phase 18)

| Field | Type | Description |
|-------|------|-------------|
| `title` | `str` | Segment heading |
| `content` | `str` | Segment body (markdown) |
| `source_agents` | `list[str]` | Registry keys that contributed |
| `pov` | `str \| null` | Display lens (e.g. `Art`, `UI Design`) |

Segment titles are clickable in the frontend; clicking sends `"Tell me more about {title}"` as the next user message.

### Planned Panel fields

_None — Phase 20 fields are live._

### WebSocket cancellation envelope (Phase 20)

```json
{ "type": "cancelled", "message": "Previous request cancelled — processing your new message." }
```

Not a Panel — clients should decrement in-flight state and show an informational notice (not an error).

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

### Live extensions (Phase 16)

WebSocket inbound envelope (backward compatible — plain text still maps to `auto`):

```json
{
  "text": "Explain photosynthesis with citations",
  "product_mode": "research",
  "chain_profile": "L3"
}
```

| Field | Phase | Description |
|-------|-------|-------------|
| `product_mode` | 16 (live) | Research / planner / coding / builder; `auto` when omitted or plain text |
| `chain_profile` | 17 (live) | Output level L0–L4; omitted in JSON resolves from product mode; plain text → L4 |

POV agents use keys such as `chemistry`, `art`, `ui_design` (one disciplinary lens per agent).

---

## 4. Data pipeline types

Internal graph state types for the full chain. `MayorData` is live in Phase 10–11; `MicroData` and `UsableAnswer` are live in Phase 12.

### MayorData (live — Phase 10–15B)

Raw output from a POV agent, specialist, or search reader. Stored in graph state via reducer; merged by Presenter. POV agents set `pov` and `topic`; `resource_reader` populates `citations`.

```json
{
  "source_agent": "chemistry",
  "topic": "Chemistry",
  "pov": "Chemistry",
  "content": "### Ionic bonding (chemistry lens)\n\nIonic bonds form when...",
  "citations": []
}
```

### MicroData (live — Phase 12, curator role Phase 15C)

Combiner Mayor output — sorted inventory (not final user prose).

```json
{
  "combiner": "mayor",
  "segments": [
    {
      "title": "Visual composition (Art POV)",
      "content": "- Blue palette\n- Open Sans for headings",
      "source_agents": ["art"],
      "overlap_notes": null
    },
    {
      "title": "Shared typography",
      "content": "- Open Sans body text",
      "source_agents": ["art", "ui_design"],
      "overlap_notes": "Art and ui_design both recommend Open Sans."
    }
  ],
  "source_agents": ["art", "ui_design"]
}
```

### UsableAnswer (live — Phase 12, editor role Phase 15C)

Combiner Micro output — deduplicated segment ready for collection.

```json
{
  "segment_id": "uuid4",
  "order_hint": 1,
  "title": "Overview",
  "content": "Multiple sources confirm a clean grid and Open Sans typography.",
  "review_status": "pending",
  "source_agents": ["art", "ui_design"]
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
| `expected_fan_in_branches` | `list[str]` | Branch IDs that must finish before post_fan_in routes (Phase 13.1) |
| `fan_in_branches_done` | `list[str]` | Completed branch IDs (reducer append) |

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

## 6. Chain profiles (live — Phase 17)

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
