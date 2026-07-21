# TESS Engine — Multi-cloud ops hardening (session 2 opener)

## Context

Control plane on Hetzner (`5.78.186.223`). AWS standby (`i-0360ab28632a3c4a0`,
EIP `18.227.172.81`, `us-east-2`) is stopped-by-default.

**Session 1 shipped (2026-07-21):**


| #   | Item                       | Outcome                                                                                                                                                                         |
| --- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | SSH lockout docs           | [If you're locked out](deploy/MULTI_CLOUD.md#if-youre-locked-out) — path B My IP; path A Instance Connect + `com.amazonaws.us-east-2.ec2-instance-connect` (does not bypass SG) |
| 2   | EIP / public IPv4 cost     | [Cost note](deploy/MULTI_CLOUD.md#elastic-ip--public-ipv4-cost) — no hardcoded $/hr; **keep EIP**; CE IAM gaps noted (`ce:GetCostAndUsage`, `DescribeAddresses`)                |
| 3   | Remaining chaos kinds live | `health_5xx`, `worker_down`, `redis_partition`, `cpu_burn` → failover in 2–3 probes. `high_latency` **did not trip** (gap — see below)                                          |


Prior opener: [MULTI_CLOUD_HARDENING_OPENER.md](MULTI_CLOUD_HARDENING_OPENER.md).  
Reference: [deploy/MULTI_CLOUD.md](deploy/MULTI_CLOUD.md) (Last verified),
[scripts/aws_standby.py](scripts/aws_standby.py),
[scripts/ops_failover_live_smoke.py](scripts/ops_failover_live_smoke.py).

Architecture / product chain: [AI_MAP.md](AI_MAP.md), [ROADMAP.md](ROADMAP.md).
This session is **ops hardening**, not LangGraph/POV work.

---



## Known gaps (carry forward)



### A. `high_latency` chaos ≠ failover

Live run: default `latency_ms=2500` → measured ~2512 ms; score 45; `healthy=True`;
`OPS_LATENCY_THRESHOLD_MS=5000`; failures stayed 0 across 12 probes. Prober also
caps injected sleep at **3 s** (`[app/ops/prober.py](app/ops/prober.py)`), so
default chaos cannot cross the 5 s latency threshold.

**Do not silently tweak thresholds to make the test pass.** Decide first:


| Option                          | Meaning                                                                                                                                                               |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1 — Document as score-only**  | `high_latency` is mild pressure; failover is for hard failures. Update MULTI_CLOUD.md chaos table.                                                                    |
| **2 — Align chaos with policy** | Raise default chaos `latency_ms` and/or remove/raise the 3 s sleep cap so injected latency can exceed `OPS_LATENCY_THRESHOLD_MS` when intentionally testing failover. |


Recommend **option 2** if the product claim is “every chaos kind can trip failover”;
**option 1** if 5 s is the real SLO and mild latency should not flap.

### B. Mid-session `provider_changed` may not reach the browser

Failover clears assignments and switches `active_provider_id`, but the background
probe loop (`[app/main.py](app/main.py)`) **logs** failover and does **not** push
`type: "provider_changed"` onto open WebSockets. Frontend already handles that
message and a WS-close fallback (`[frontend/src/hooks/useWebSocket.ts](frontend/src/hooks/useWebSocket.ts)`
→ dismissible banner in `[App.tsx](frontend/src/App.tsx)`).

With `simulate-unhealthy`, Hetzner’s real stack stays up — the browser WS often
stays connected and the in-flight Celery job can finish on Hetzner even after
routing flipped to AWS. Item 4 exists to observe what a real user sees.

---



## This session goal

Three items: one manual observation, one decision (+ small code/docs if option 2),
one small external monitor.

### 1. Mid-session browser failover (operator — do first)

Manual; do **not** script a browser automation.

**Steps:**

1. Wake AWS: `python scripts/aws_standby.py wake` (expect small cost).
2. Open frontend `http://5.78.186.223`, wait until input is enabled (WS connected).
3. Send a long-running prompt (Research / L4) so processing is visibly in flight.
4. From another terminal: inject chaos or simulate-unhealthy on Hetzner, probe until
  `GET /ops/routing` shows `active_provider_id=prov_aws` (threshold 3; background
   prober is every ~30 s if you wait instead of probing).
5. Watch the browser; note banner / disconnect / silent continue.
6. Clear chaos, force Hetzner active, `python scripts/aws_standby.py sleep`.

**Record in MULTI_CLOUD.md Last verified:** date, what you saw (banner text? WS drop?
answer finished on Hetzner anyway?), and whether that matches “failover v1 drops
sessions” UX expectations.

**Safe:** chaos/simulate-unhealthy is control-plane side only — does not take down
Hetzner Docker/Redis/SSH. Side effect: assignments cleared; other users interrupted;
AWS burns while awake.

### 2. Resolve `high_latency` gap

After (or in parallel with) the decision above:

- If **option 1:** doc-only — chaos kinds table + Last verified note.
- If **option 2:** minimal prober/chaos change + re-run **only** `high_latency`
live once (wake → inject → probe → clear → sleep); append Last verified line.
Keep `OPS_LATENCY_THRESHOLD_MS` unless you explicitly choose to change the SLO.



### 3. External uptime check on the control plane

Something **outside Hetzner** watching Hetzner so a total box death is visible.

**Default approach (keep small):**

- Free external ping (UptimeRobot, Better Stack, or Healthchecks.io) hitting
`http://5.78.186.223/health` on a short interval (e.g. 5 minutes).
- Alert to email/Telegram already used by the operator.
- Document URL, interval, and expected JSON (`{"status":"ok",...}`) under a short
**External uptime** subsection in [deploy/MULTI_CLOUD.md](deploy/MULTI_CLOUD.md).

Do **not** build a custom watcher service this session. Optional later: GitHub
Actions cron or AWS Lambda from the standby account — only if the free ping
product is unacceptable.

---



## Definition of done (this session)

- [x] Operator ran mid-session browser failover once; observation in Last verified
- [x] `high_latency` gap decided (option 1) and reflected in docs
- [x] External uptime documented in MULTI_CLOUD.md (endpoint verified; UptimeRobot
      monitor create needs operator login at dashboard.uptimerobot.com)
- [x] No LangGraph / POV changes; no silent threshold tweaks without an explicit decision

---



## Ordered backlog (later sessions)


| #   | Item                                           | Notes                                                                             |
| --- | ---------------------------------------------- | --------------------------------------------------------------------------------- |
| 1–3 | SSH / EIP / chaos kinds                        | **Done** (S1)                                                                     |
| 4   | Mid-session browser failover                   | **Done** (S2) — silent continue; no banner under simulate-unhealthy               |
| —   | `high_latency` gap                             | **Done** (S2) — option 1 score-only                                               |
| 5   | External uptime                                | **Docs done** (S2); create UptimeRobot monitor (operator login)                    |
| 6   | Daily drift check                              | Cron/script: AWS stopped when it should be (catch `cycle` dying before `finally`) |
| 7   | Per-operator admin tokens + secrets manager    | Bigger lift; before any real client data                                          |
| —   | Push `provider_changed` to open WS on failover | **Confirmed needed** by S2 browser observation                                    |


---



## Out of scope this session

- Phase 21 presenter / follow-up work
- Automating SG “My IP” updates or EIP release
- Implementing drift cron or multi-operator tokens (items 6–7)
- Changing flap thresholds except as part of an explicit `high_latency` decision

---



## Quick pointers


| Concern                       | Location                                                                                                                   |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Standby + Last verified       | [deploy/MULTI_CLOUD.md](deploy/MULTI_CLOUD.md)                                                                             |
| Wake / sleep / cycle          | [scripts/aws_standby.py](scripts/aws_standby.py)                                                                           |
| Live smoke (`mark_unhealthy`) | [scripts/ops_failover_live_smoke.py](scripts/ops_failover_live_smoke.py)                                                   |
| Chaos / probe                 | `[app/ops/chaos.py](app/ops/chaos.py)`, `[app/ops/prober.py](app/ops/prober.py)`                                           |
| Failover                      | `[app/ops/failover.py](app/ops/failover.py)`                                                                               |
| Provider notice UX            | `[frontend/src/hooks/useWebSocket.ts](frontend/src/hooks/useWebSocket.ts)`, `[frontend/src/App.tsx](frontend/src/App.tsx)` |
| AWS instance                  | `i-0360ab28632a3c4a0` / EIP `18.227.172.81` / SG `launch-wizard-1`                                                         |
| Control plane                 | `http://5.78.186.223` (HTTP for `/ops` and `/health`)                                                                      |


