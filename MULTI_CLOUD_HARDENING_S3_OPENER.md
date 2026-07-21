# TESS Engine — Multi-cloud ops hardening (session 3 opener)

## Context

Control plane on Hetzner (`5.78.186.223`). AWS standby (`i-0360ab28632a3c4a0`,
EIP `18.227.172.81`, `us-east-2`) is stopped-by-default.

**Session 1 shipped (2026-07-21):** SSH lockout + EIP cost docs; chaos kinds live
(`health_5xx` / `worker_down` / `redis_partition` / `cpu_burn` failover).

**Session 2 shipped (2026-07-21):**


| #   | Item                         | Outcome                                                                                                                                                          |
| --- | ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 4   | Mid-session browser failover | Failover to `prov_aws` in 3 probes; browser stayed **Connected**, **no** `provider_changed` banner; L4 job kept processing on Hetzner (silent continue)         |
| —   | `high_latency`               | **Option 1** — score-only mild pressure; keep `OPS_LATENCY_THRESHOLD_MS=5000` + 3 s sleep cap                                                                    |
| 5   | External uptime (docs)       | [External uptime](deploy/MULTI_CLOUD.md#external-uptime) subsection + endpoint verified `200 {"status":"ok","redis":"ok"}`; **monitor create still pending** |


Prior openers: [MULTI_CLOUD_HARDENING_S2_OPENER.md](MULTI_CLOUD_HARDENING_S2_OPENER.md),
[MULTI_CLOUD_HARDENING_OPENER.md](MULTI_CLOUD_HARDENING_OPENER.md).  
Reference: [deploy/MULTI_CLOUD.md](deploy/MULTI_CLOUD.md) (Last verified + External uptime),
[scripts/aws_standby.py](scripts/aws_standby.py).

Architecture / product chain: [AI_MAP.md](AI_MAP.md), [ROADMAP.md](ROADMAP.md).
This session is **ops hardening**, not LangGraph/POV work.

---



## Known gaps (carry forward)



### A. Mid-session `provider_changed` never reaches the browser (confirmed S2)

Failover clears assignments and switches `active_provider_id`, but
[`app/main.py`](app/main.py) `_ops_probe_loop` only **logs** failover — it does
**not** push `type: "provider_changed"` onto open WebSockets. With
`simulate-unhealthy`, Hetzner’s real stack stays up, so the browser WS stays
connected and the in-flight job can finish on Hetzner.

Frontend already handles the message + WS-close fallback
([`frontend/src/hooks/useWebSocket.ts`](frontend/src/hooks/useWebSocket.ts) →
banner in [`App.tsx`](frontend/src/App.tsx)).

**Not in this session** unless item 5–6 finish early and you explicitly pull it
forward. Backlog item: push `provider_changed` to open WS on failover.

### B. External uptime monitor not live yet

S2 documented the target; creating the UptimeRobot monitor needs operator login
at https://dashboard.uptimerobot.com/. That is **item 5 finish** below.

---



## This session goal

Two items from the ordered backlog: finish external uptime, then daily drift check.

### 5. External uptime — create the monitor (operator — do first)

Finish what S2 left as “docs done / create pending.”

**Steps:**

1. Log in (or sign up free) at https://dashboard.uptimerobot.com/.
2. Add HTTP(S) monitor:
   - URL: `http://5.78.186.223/health`
   - Interval: **5 minutes**
   - Expect HTTP 200; keyword `"status":"ok"` if the free plan supports it
3. Attach alert to the email/Telegram channel already used for ops.
4. Trigger a test alert once if the product allows (confirm the channel works).
5. Update [deploy/MULTI_CLOUD.md](deploy/MULTI_CLOUD.md) **External uptime**
   **Status** line: date, monitor name/ID, alert channel, “live”.

**Do not** build a custom watcher, GitHub Actions cron, or Lambda this session
unless UptimeRobot is unacceptable — then document why and pick one alternative
still outside Hetzner.

**Safe:** read-only against the control plane; no AWS wake required.

### 6. Daily drift check — AWS stopped when it should be

Catch “`cycle` died before `finally`” / forgotten `wake` leaving
`i-0360ab28632a3c4a0` running and burning compute.

**Default approach (keep small):**

1. Add a small script (prefer extend [`scripts/aws_standby.py`](scripts/aws_standby.py)
   with a `status` / `drift-check` subcommand, or `scripts/aws_standby_drift.py`) that:
   - `DescribeInstances` for `AWS_STANDBY_INSTANCE_ID` (default `i-0360ab28632a3c4a0`)
   - Exits **0** if state is `stopped` (or `stopping`)
   - Exits **non-zero** if `running` / `pending` (drift)
   - Prints instance id, state, public IP / EIP if any
2. Unit-test the exit logic with mocked boto3 (same style as
   [`tests/test_aws_standby.py`](tests/test_aws_standby.py)).
3. Schedule **once daily** outside the hot path:
   - Prefer operator laptop Task Scheduler / cron, **or** a free external cron
     hitting nothing on Hetzner — the check talks to **AWS API**, not the Tess box.
   - Document the schedule + how alerts surface (email from cron, Telegram bot,
     or “check CI mail”) under a short **Drift check** subsection in
     [deploy/MULTI_CLOUD.md](deploy/MULTI_CLOUD.md).
4. Optional (nice-to-have, same session if cheap): env flag
   `AWS_STANDBY_ALLOW_RUNNING=1` to skip fail when an intentional wake is in
   progress — default off so forgotten wakes still alarm.

**Do not** auto-`stop` from the drift job in v1 (alert only — avoid surprising
an in-progress smoke). Auto-stop can be a later session.

**Safe:** Describe-only IAM is enough; no stop/start from the checker.

---



## Definition of done (this session)

- [ ] UptimeRobot (or chosen) monitor **live**; MULTI_CLOUD.md External uptime
      Status updated with monitor id/name + alert channel
- [ ] Drift-check command/script + unit test(s)
- [ ] Drift schedule documented in MULTI_CLOUD.md; at least one dry-run shows
      `stopped` → exit 0 (and optionally a mocked/`--force-fail` path for non-zero)
- [ ] No LangGraph / POV changes; no auto-stop from drift v1; no
      `provider_changed` WS push unless explicitly pulled forward

---



## Ordered backlog (later sessions)


| #   | Item                                           | Notes                                                          |
| --- | ---------------------------------------------- | -------------------------------------------------------------- |
| 1–3 | SSH / EIP / chaos kinds                        | **Done** (S1)                                                  |
| 4   | Mid-session browser failover                   | **Done** (S2) — silent continue                                |
| —   | `high_latency`                                 | **Done** (S2) — score-only                                     |
| 5   | External uptime                                | **This session** — create monitor + Status live                |
| 6   | Daily drift check                              | **This session** — script + schedule + docs                    |
| 7   | Per-operator admin tokens + secrets manager    | Bigger lift; before any real client data                       |
| —   | Push `provider_changed` to open WS on failover | Confirmed needed (S2); next after 5–6 unless pulled forward    |


---



## Out of scope this session

- Phase 21 presenter / follow-up work
- Automating SG “My IP” updates or EIP release
- Auto-stopping a drifted AWS instance from the checker
- Multi-operator admin tokens / secrets manager (item 7)
- Implementing `provider_changed` WS push (unless explicitly pulled forward)
- Changing flap / latency thresholds

---



## Quick pointers


| Concern                 | Location                                                                                 |
| ----------------------- | ---------------------------------------------------------------------------------------- |
| External uptime (docs)  | [deploy/MULTI_CLOUD.md](deploy/MULTI_CLOUD.md#external-uptime)                           |
| Standby wake/sleep/cycle| [scripts/aws_standby.py](scripts/aws_standby.py)                                         |
| Standby unit tests      | [tests/test_aws_standby.py](tests/test_aws_standby.py)                                   |
| Failover / probe loop   | [`app/ops/failover.py`](app/ops/failover.py), [`app/main.py`](app/main.py)               |
| Provider notice UX      | [`frontend/src/hooks/useWebSocket.ts`](frontend/src/hooks/useWebSocket.ts)               |
| AWS instance            | `i-0360ab28632a3c4a0` / EIP `18.227.172.81` / SG `launch-wizard-1`                       |
| Control plane           | `http://5.78.186.223` (`/health`, `/ops`)                                                |
| UptimeRobot dashboard   | https://dashboard.uptimerobot.com/                                                       |
