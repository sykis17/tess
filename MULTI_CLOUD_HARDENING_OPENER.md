# TESS Engine — Multi-cloud ops hardening (session opener)

## Context

Multi-cloud ops control plane is live on Hetzner (`5.78.186.223`). AWS standby
(`i-0360ab28632a3c4a0`, EIP `18.227.172.81`, `us-east-2`) is stopped-by-default.

**Verified 2026-07-21:** `python scripts/aws_standby.py cycle` completed end-to-end:

- Budget guard (`tess-monthly-ops`)
- Wake → `/health` OK
- `prov_aws` connect + probe
- Live failover smoke: Hetzner simulate-unhealthy → switch to AWS after 3 probes → recover
- AWS stopped again in `finally`

Reference: [deploy/MULTI_CLOUD.md](deploy/MULTI_CLOUD.md) (Last verified block),
[scripts/aws_standby.py](scripts/aws_standby.py),
[scripts/ops_failover_live_smoke.py](scripts/ops_failover_live_smoke.py).

Architecture / product chain docs: [AI_MAP.md](AI_MAP.md), [ROADMAP.md](ROADMAP.md).
This session is **ops hardening**, not LangGraph/POV work.

---

## This session goal (two small items)

Documentation / verification only — **no failover logic changes**.

### 1. SSH access resilience (do first)

Add a short **"If you're locked out"** subsection under AWS standby in
[deploy/MULTI_CLOUD.md](deploy/MULTI_CLOUD.md).

**Facts to document:**

| Item | Detail |
|------|--------|
| Security group | `launch-wizard-1` |
| Current SSH rule | Source `186.99.129.21/32` (launch-time operator IP) |
| Symptom on IP change | SSH hangs / times out with no useful error |
| Key pair | `tess-aws-key` (AWS); Hetzner uses separate `hetzner_tess` key |

**Recovery path A — EC2 Instance Connect (console):**

1. AWS Console → EC2 → select `i-0360ab28632a3c4a0` (must be **running**)
2. **Connect** → **EC2 Instance Connect** → Connect

**Do not claim it bypasses the security group.** Per AWS docs, console Instance
Connect still requires inbound SSH (port 22) from the **EC2 Instance Connect
service** IP ranges for the region. For `us-east-2`, allow source:

- AWS-managed prefix list: `com.amazonaws.us-east-2.ec2-instance-connect`

If that prefix-list rule is missing, console Connect will fail even when the
instance is up. Document adding that rule as a one-time SG improvement (alongside
keeping "My IP" for laptop SSH).

Alternative when Instance Connect is not set up: **EC2 Serial Console** (if
enabled for the account) or temporary SG open — prefer Instance Connect prefix
list over `0.0.0.0/22`.

**Recovery path B — update security group (fastest if you only need laptop SSH):**

1. EC2 → Security Groups → `launch-wizard-1`
2. Edit inbound rules → SSH → Source **My IP** (or new CIDR)
3. Save

Manual only — no IP-drift automation this session.

### 2. Elastic IP idle-charge verification

EIP `18.227.172.81` stays associated while the instance is **stopped** most of the
time. Confirm whether (and how much) public IPv4 charges appear on the bill.

#### What docs say (as of research 2026-07-21)

- Since **2024-02-01**, AWS charges for **all** public IPv4 addresses, including
  EIPs associated with **running or stopped** instances, and idle unassociated EIPs.
- Official pointer: [Elastic IP addresses](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/elastic-ip-addresses-eip.html)
  → Public IPv4 pricing on the [Amazon VPC pricing](https://aws.amazon.com/vpc/pricing/) page
  (Public IPv4 Address tab).
- **Do not hardcode a stale $/hour in MULTI_CLOUD.md.** Note “check current VPC
  public IPv4 pricing” and that the doc’s cost assumption may go stale.
- Trade-off to record: keep EIP (stable `OPS_AWS_BASE_URL`) vs release EIP and
  accept IP-drift handling on wake (already partially supported in `aws_standby.py`).

#### CLI checks (run on Windows with `tess-ops-laptop` creds)

May need `ce:GetCostAndUsage` on the IAM user (add if AccessDenied).

```powershell
# Last 7 days — group by usage type (look for PublicIPv4 / ElasticIP lines)
aws ce get-cost-and-usage `
  --time-period Start=2026-07-14,End=2026-07-21 `
  --granularity DAILY `
  --metrics UnblendedCost `
  --group-by Type=DIMENSION,Key=USAGE_TYPE `
  --filter file://ce-filter-ec2-other.json
```

Simpler first pass (no filter file):

```powershell
aws ce get-cost-and-usage `
  --time-period Start=2026-07-01,End=2026-07-22 `
  --granularity MONTHLY `
  --metrics UnblendedCost `
  --group-by Type=DIMENSION,Key=USAGE_TYPE `
  --query "ResultsByTime[].Groups[?contains(Keys[0], 'PublicIPv4') || contains(Keys[0], 'ElasticIP')]"
```

Also:

```powershell
# Confirm association state (still attached while stopped?)
aws ec2 describe-addresses --region us-east-2 `
  --filters "Name=public-ip,Values=18.227.172.81" `
  --query "Addresses[].{PublicIp:PublicIp,InstanceId:InstanceId,AssociationId:AssociationId}"
```

#### Console path (if CLI / CE permissions missing)

1. Billing → **Cost Explorer**
2. Service filter: **EC2 - Other** and/or **VPC** (naming varies)
3. Group by **Usage type**
4. Look for usage types containing `PublicIPv4:InUseAddress`, `PublicIPv4:IdleAddress`,
   or legacy `ElasticIP:*`
5. Optional: VPC → **Public IP insights** (inventory + estimated cost)

#### MULTI_CLOUD.md note to add

Under AWS standby / EIP metadata: expected that a **small ongoing public IPv4
charge** applies while the EIP is allocated (running or stopped); verify on the
bill; link to current VPC public IPv4 pricing; decision: keep EIP vs release and
rely on wake-time URL patch.

---

## Definition of done (this session)

- [ ] MULTI_CLOUD.md has **If you're locked out** (SG IP lock + path A + path B;
      Instance Connect prefix-list caveat accurate)
- [ ] MULTI_CLOUD.md has **EIP cost** note (no hardcoded stale $/hr; console + CLI
      verification pointers)
- [ ] Operator ran CE / Public IP insights once and recorded the finding in the
      Last verified / EIP note (charge present? keep EIP? yes/no)
- [ ] No failover / LangGraph code changes unless a one-line doc-linked script
      comment is clearly needed

---

## Ordered backlog (later sessions)

Tackle in this order across subsequent sessions:

| # | Item | Notes |
|---|------|--------|
| 1 | SSH access resilience | **This session** — docs |
| 2 | Confirm/close EIP idle charge | **This session** — bill check + doc note; decide keep vs release |
| 3 | Remaining chaos kinds once each | `high_latency`, `redis_partition`, `cpu_burn`, `worker_down` — flap thresholds |
| 4 | Real mid-session failover from a browser tab | Confirm `provider_changed` UX for a real user |
| 5 | External uptime check on control plane | Something outside Hetzner watching Hetzner |
| 6 | Daily drift check | Cron: AWS stopped when it should be (catch cycle dying before `finally`) |
| 7 | Per-operator admin tokens + secrets manager | Bigger lift; before any real client data |

---

## Out of scope this session

- Changing failover thresholds, smoke script assertions, or LangGraph nodes
- Automating SG IP updates or EIP release/re-associate
- Implementing items 3–7 above (capture only as backlog)

---

## Quick pointers

| Concern | Location |
|---------|----------|
| Standby docs | [deploy/MULTI_CLOUD.md](deploy/MULTI_CLOUD.md) |
| Wake/sleep/cycle | [scripts/aws_standby.py](scripts/aws_standby.py) |
| Live smoke | [scripts/ops_failover_live_smoke.py](scripts/ops_failover_live_smoke.py) |
| Chaos API | `POST /ops/chaos/{id}?kind=...` |
| AWS instance | `i-0360ab28632a3c4a0` / EIP `18.227.172.81` / SG `launch-wizard-1` |
| Control plane | `http://5.78.186.223` (IP-only; use HTTP not HTTPS for `/ops`) |
