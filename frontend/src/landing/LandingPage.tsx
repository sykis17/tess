import './landing.css'

const ARCH_SECTIONS = [
  { id: 'self-report', label: '01 · Self-report /health' },
  { id: 'adapters', label: '02 · CloudAdapter pattern' },
  { id: 'failover', label: '03 · Failover policy' },
  { id: 'onboarding', label: '04 · Onboarding saga' },
] as const

export function LandingPage() {
  return (
    <div className="land-page">
      <div className="land-shell">
        <header className="land-hero">
          <p className="land-brand">TESS</p>
          <p className="land-kicker">Event-driven AI orchestration</p>
          <p className="land-lede">
            Multi-POV agents, chain profiles, and a multi-cloud control plane — with notes
            on the decisions that held under real failover load.
          </p>
          <div className="land-cta-row">
            <a className="land-cta land-cta--primary" href="/chat">
              Open chat
            </a>
            <a className="land-cta land-cta--ghost" href="/architecture/">
              Architecture notes
            </a>
          </div>
        </header>

        <section className="land-section" aria-labelledby="land-explore">
          <h2 id="land-explore">Explore</h2>
          <p className="land-section-intro">
            Public pages and ops tools for this deployment.
          </p>
          <ul className="land-links">
            <li>
              <a href="/chat">
                <p className="land-link-title">Chat engine</p>
                <p className="land-link-meta">
                  Live WebSocket session — send a prompt through the LangGraph pipeline.
                </p>
              </a>
            </li>
            <li>
              <a href="/architecture/">
                <p className="land-link-title">Architecture notes</p>
                <p className="land-link-meta">
                  ADR-style writeups on self-report health, thin adapters, failover, and the
                  three-cloud onboarding saga.
                </p>
              </a>
              <ul className="land-arch-anchors">
                {ARCH_SECTIONS.map((s) => (
                  <li key={s.id}>
                    <a href={`/architecture/#${s.id}`}>{s.label}</a>
                  </li>
                ))}
              </ul>
            </li>
            <li>
              <a href="/ops-status/">
                <p className="land-link-title">Ops status</p>
                <p className="land-link-meta">
                  Read-only fleet view — routing, scores, and recent events (admin token).
                </p>
              </a>
            </li>
            <li>
              <a href="/ops-ui/">
                <p className="land-link-title">Ops admin</p>
                <p className="land-link-meta">
                  Take providers offline, force active, probe now (admin token).
                </p>
              </a>
            </li>
          </ul>
        </section>

        <footer className="land-footer">TESS Engine · landing</footer>
      </div>
    </div>
  )
}
