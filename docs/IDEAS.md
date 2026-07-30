# Ideas parking lot

A zero-ceremony inbox for ideas that are not scope. The two rules that keep it
healthy:

1. **Anything can enter, anytime, at zero ceremony** — two or three lines: the
   idea, where and when it came from, and what would gate it if ever built.
2. **Nothing leaves this list into scope without its gate and a recorded
   decision.** An idea here is parked, not planned; filing one creates no
   obligation and implies no endorsement.

This exists so ideas stop doing the three bad things: becoming scope on the
spot, getting filed into whatever doc is nearest, or living in someone's head
until they rot.

---

## Parked

- **Dialogic refinement protocol.** Origin: Jesse, 2026-07-30 (P2 Step-0 night
  sitting). Gate: the W2 graph-eval harness — measured answer-quality gain must
  justify the added token cost before any chain change is considered.

- **Per-node parallel LLM serving + request tiering.** Run Ollama with
  `OLLAMA_NUM_PARALLEL > 1` and tier requests across streams. Origin: Jesse,
  2026-07-30, prompted by the Step 1 probe showing 2-concurrent requests
  serialize at full per-request rate (Ollama default, matching the product's
  own request lock). Gate: P3 — measured per-stream rates under the real
  committed traffic profile; parallelism that halves per-stream rate is a
  regression, not a feature.

- **Redundancy-gap review (standing item).** Periodically ask: where does the
  architecture still have a single point? Origin: Jesse, 2026-07-30 — the
  observer's external pinger came from exactly this question ("who watches the
  witness"). Gate: none for the review itself (it is a question, not a change);
  each finding files here or as an issue with its own gate.
