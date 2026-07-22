import { AdapterDiagram } from '../diagrams/AdapterDiagram'
import { FailoverDiagram } from '../diagrams/FailoverDiagram'
import { OverviewDiagram } from '../diagrams/OverviewDiagram'
import { SagaDiagram } from '../diagrams/SagaDiagram'
import { SelfReportDiagram } from '../diagrams/SelfReportDiagram'
import { ArchBlock, DecisionSection, DiagramFrame, FieldNote } from '../DecisionSection'

export function ContextStrip() {
  return (
    <>
      <div className="arch-context" id="context">
        <p>
          Users connect to a Tess stack over WebSocket. A control plane probes every
          registered provider on an interval, scores host health, and can fail active
          routing over to a standby when the threshold is met. These notes cover the
          decisions that made three-cloud failover (Hetzner, AWS, GCP) workable — including
          the messy parts.
        </p>
      </div>
      <DiagramFrame caption="Adapters may enrich metadata; they do not own health. The prober’s GET /health is the source of truth on every stack.">
        <OverviewDiagram />
      </DiagramFrame>
    </>
  )
}

export function DecisionSelfReport() {
  return (
    <DecisionSection
      id="self-report"
      number="01"
      title="Self-report /health as the source of truth"
    >
      <ArchBlock label="Context">
        <p>
          Failover needs comparable health across Hetzner, AWS, and GCP — and eventually
          anyone else’s Tess-compatible stack — without teaching the control plane every
          vendor metrics API.
        </p>
      </ArchBlock>

      <ArchBlock label="Decision">
        <p>
          Each stack self-reports via <code>GET /health</code>: <code>status</code>,{' '}
          <code>redis</code>, <code>cpu_percent</code>, <code>mem_percent</code>. The
          control plane HTTP-probes on an interval (~30s). CloudWatch, GCP Monitoring, and
          the Hetzner API are not the scoring path.
        </p>
      </ArchBlock>

      <DiagramFrame caption="Vendor pull lost on credential sprawl and inconsistent semantics. Self-report gives one contract everywhere.">
        <SelfReportDiagram />
      </DiagramFrame>

      <ArchBlock label="Alternatives considered">
        <ul>
          <li>
            Pull CPU/mem from each cloud’s monitoring API — credential sprawl, mismatched
            semantics, and a “double penalty” if probe and vendor disagree.
          </li>
          <li>
            Agent or sidecar push into the control plane — more moving parts than v1 needed.
          </li>
          <li>
            Binary uptime ping only — too coarse for load-aware failover.
          </li>
        </ul>
      </ArchBlock>

      <ArchBlock label="Consequences">
        <p>
          Scoring is apples-to-apples. Cloud credentials stay on wake/sleep scripts, not on
          the live scoring path.
        </p>
        <p>
          That same contract is why a future BYO (<code>customer</code>) provider only needs
          a healthy <code>/health</code> plus an <code>org_id</code> — customers never hand
          over their own cloud credentials. Hyperscaler adapters stay thin because the health
          model was never “talk to CloudWatch.”
        </p>
        <p>
          Tradeoff: you trust the host’s self-report. A compromised box can lie. Acceptable
          for stacks we operate or contract for in v1; not a substitute for attestation later.
        </p>
      </ArchBlock>
    </DecisionSection>
  )
}

export function DecisionAdapters() {
  return (
    <DecisionSection
      id="adapters"
      number="02"
      title="Thin CloudAdapter per provider"
    >
      <ArchBlock label="Context">
        <p>
          Providers differ in API shape, regions, and standby scripts, but they must plug
          into one registry, bootstrap path, and ops surface.
        </p>
      </ArchBlock>

      <ArchBlock label="Decision">
        <p>
          A <code>CloudAdapter</code> ABC with <code>HetznerAdapter</code>,{' '}
          <code>AwsAdapter</code>, <code>GcpAdapter</code>, and{' '}
          <code>CustomerAdapter</code>. <code>fetch_metrics</code> is mostly metadata or a
          stub. The prober owns <code>/health</code>; adapters enrich, they do not score.
        </p>
      </ArchBlock>

      <DiagramFrame caption="Registry resolves an adapter for connection metadata. Bold path for health is always the HTTP probe.">
        <AdapterDiagram />
      </DiagramFrame>

      <ArchBlock label="Alternatives considered">
        <ul>
          <li>
            Fat adapters that each implement health and failover — duplicates probe logic and
            diverges the BYO path.
          </li>
          <li>
            No adapter layer (<code>if provider_type</code> everywhere) — painful by cloud #3.
          </li>
          <li>
            A shared multi-cloud SDK abstraction — overkill for the current surface area.
          </li>
        </ul>
      </ArchBlock>

      <ArchBlock label="Consequences">
        <p>
          GCP onboarding was largely “port the AWS standby and probe pattern.” A new cloud
          adds an adapter and a bootstrap seed, not a new health model.
        </p>
        <p>
          Cost: adapters look empty until enrichment is real. That emptiness is intentional —
          not an unfinished accident.
        </p>
      </ArchBlock>
    </DecisionSection>
  )
}

export function DecisionFailover() {
  return (
    <DecisionSection
      id="failover"
      number="03"
      title="Consecutive failures and a score floor"
    >
      <ArchBlock label="Context">
        <p>
          Probes run about every 30 seconds. Transient blips — a latency spike, a brief Redis
          hiccup, a deploy blip — must not thrash the active provider. In v1, a switch drops
          sessions (no seamless migration yet), so false failovers are expensive.
        </p>
      </ArchBlock>

      <ArchBlock label="Decision">
        <p>
          An unhealthy probe increments <code>consecutive_failures</code>. Failover trips when
          the count reaches the threshold (default <strong>3</strong>). Health is a 0–100
          score from latency, Redis, CPU, and memory, with a floor of{' '}
          <strong>40</strong>. Recovery needs consecutive successes (default{' '}
          <strong>2</strong>). The standby with the best score wins; optional failback returns
          to a preferred provider after it recovers.
        </p>
      </ArchBlock>

      <DiagramFrame caption="Three strikes before switch. Chaos testing treated mild high-latency as score pressure, not an instant flap.">
        <FailoverDiagram />
      </DiagramFrame>

      <ArchBlock label="Alternatives considered">
        <ul>
          <li>Binary up/down on a single failed probe — flaps under noise.</li>
          <li>
            Latency-only or HTTP-only gates — miss overloaded-but-up hosts.
          </li>
          <li>Instant failback to preferred — oscillation between preferred and standby.</li>
        </ul>
      </ArchBlock>

      <ArchBlock label="Consequences">
        <p>
          Stable demos and a production posture with standbys stopped by default for cost.
          Known footgun: if the prober’s hardcoded score floor and the routing policy’s{' '}
          <code>min_score_for_healthy</code> diverge, behavior gets confusing — today both
          sit at 40.
        </p>
        <p>
          Honesty for readers: v1 still clears sessions on switch and publishes a provider
          change notice so clients can reconnect. Seamless migration is explicitly not claimed.
        </p>
      </ArchBlock>

      <FieldNote>
        <p>
          During live three-way runs, a background prober race could jump the failure count
          (for example 2→4) on the switch probe. The selected standby was still correct — a
          reminder that thresholds absorb timing noise better than single-shot triggers.
        </p>
      </FieldNote>
    </DecisionSection>
  )
}

export function DecisionOnboarding() {
  return (
    <DecisionSection
      id="onboarding"
      number="04"
      title="Ship against real standbys early"
    >
      <ArchBlock label="Context">
        <p>
          Multi-cloud on paper is cheap. Contact with three vendors is the design review.
          The meta-decision: bring real standbys online while the control plane is still
          malleable, and treat every bring-up bug as signal about the architecture — not as
          noise to hide.
        </p>
      </ArchBlock>

      <ArchBlock label="Decision">
        <p>
          Operate Hetzner as the always-on active stack; wake AWS and GCP for smoke and
          failover drills; leave standbys stopped by default. Document failures in the rollout
          path instead of auto-mutating cloud IAM or firewalls from wake scripts.
        </p>
      </ArchBlock>

      <DiagramFrame caption="Three incidents, three failure modes: operator access, capacity under build load, and cloud identity UX.">
        <SagaDiagram />
      </DiagramFrame>

      <div className="arch-saga-beats">
        <div className="arch-saga-beat">
          <p className="arch-saga-beat-tag">access · AWS</p>
          <h4>Stale security-group IPs</h4>
          <p>
            The launch security group was locked to the laptop IP from first boot. Later SSH
            hung; lockout risk was real. Fix was updating My IP — wake preflight now prints
            the public IP and reminds the operator, and deliberately does not auto-edit the
            security group. Lesson: control-plane health is not the operator access path.
          </p>
        </div>
        <div className="arch-saga-beat">
          <p className="arch-saga-beat-tag">capacity · AWS</p>
          <h4>t3.micro OOM under build load</h4>
          <p>
            Vite and Docker builds hung until 1GB of swap was added. After that, smoke landed
            healthy (roughly 61% mem, score ~87). Lesson: failover sizing is not always-on
            LangGraph sizing. Instance resize stays parked until AWS must remain active under
            real graph load.
          </p>
        </div>
        <div className="arch-saga-beat">
          <p className="arch-saga-beat-tag">identity · GCP</p>
          <h4>ADC credentials and host permissions</h4>
          <p>
            Wake needed Application Default Credentials and the right Compute IAM. The git
            clone owned by <code>tessops</code> blocked docker/git for the operator until{' '}
            <code>chown</code> and a docker group fix. Lesson: “port the AWS pattern” still
            leaves a credentials and host-permissions gap — adapter sameness does not erase
            cloud identity UX.
          </p>
        </div>
      </div>

      <ArchBlock label="Alternatives considered">
        <ul>
          <li>Paper-only multi-cloud design until the control plane felt “done.”</li>
          <li>Stay single-cloud forever and call failover theoretical.</li>
          <li>
            Auto-fixing wake scripts that mutate firewall or IAM without an operator in the
            loop.
          </li>
        </ul>
      </ArchBlock>

      <ArchBlock label="Consequences">
        <p>
          Confidence that self-report and thin adapters survive three vendors. Resting ops
          state: Hetzner active; AWS and GCP stopped by default. The rollout checklist carries
          the troubleshooting table so the next wake is faster than the first.
        </p>
      </ArchBlock>
    </DecisionSection>
  )
}
