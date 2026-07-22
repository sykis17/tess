import { useEffect, useState } from 'react'
import {
  ContextStrip,
  DecisionAdapters,
  DecisionFailover,
  DecisionOnboarding,
  DecisionSelfReport,
} from './decisions/content'
import { TOC_ITEMS, type TocId } from './toc'

function useRevealOnScroll() {
  useEffect(() => {
    const nodes = document.querySelectorAll<HTMLElement>(
      '.arch-decision, .arch-diagram',
    )
    if (nodes.length === 0) return

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced) {
      nodes.forEach((n) => n.classList.add('is-visible'))
      return
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible')
            observer.unobserve(entry.target)
          }
        }
      },
      { rootMargin: '0px 0px -8% 0px', threshold: 0.12 },
    )

    nodes.forEach((n) => observer.observe(n))
    return () => observer.disconnect()
  }, [])
}

function useActiveSection(): TocId {
  const [active, setActive] = useState<TocId>(TOC_ITEMS[0].id)

  useEffect(() => {
    const sections = TOC_ITEMS.map((item) =>
      document.getElementById(item.id),
    ).filter((el): el is HTMLElement => el != null)

    if (sections.length === 0) return

    const ids = new Set<string>(TOC_ITEMS.map((item) => item.id))

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)
        const id = visible[0]?.target.id
        if (id && ids.has(id)) {
          setActive(id as TocId)
        }
      },
      { rootMargin: '-20% 0px -55% 0px', threshold: [0.1, 0.25, 0.5] },
    )

    sections.forEach((s) => observer.observe(s))
    return () => observer.disconnect()
  }, [])

  return active
}

export function ArchitecturePage() {
  useRevealOnScroll()
  const active = useActiveSection()

  return (
    <div className="arch-page">
      <div className="arch-shell">
        <aside className="arch-toc" aria-label="On this page">
          <p className="arch-toc-label">On this page</p>
          <nav>
            {TOC_ITEMS.map((item) => (
              <a
                key={item.id}
                href={`#${item.id}`}
                className={active === item.id ? 'is-active' : undefined}
              >
                {item.label}
              </a>
            ))}
          </nav>
        </aside>

        <main className="arch-main">
          <header className="arch-hero">
            <p className="arch-brand">TESS</p>
            <p className="arch-hero-kicker">Architecture notes</p>
            <p className="arch-hero-lede">
              Decisions behind multi-cloud failover — what was chosen, what lost, and which
              bugs forced the design to earn its keep.
            </p>
          </header>

          <nav className="arch-mobile-nav" aria-label="Decisions">
            {TOC_ITEMS.map((item) => (
              <a key={item.id} href={`#${item.id}`}>
                {item.label}
              </a>
            ))}
          </nav>

          <ContextStrip />
          <DecisionSelfReport />
          <DecisionAdapters />
          <DecisionFailover />
          <DecisionOnboarding />

          <section className="arch-close" aria-label="Closing">
            <p>
              This page is a sample of how Tess decisions get made: probeable contracts, thin
              edges, thresholds that respect costly failovers, and production contact as the
              test — not a highlight reel.
            </p>
          </section>

          <footer className="arch-footer">
            TESS Engine · architecture explainer · public
          </footer>
        </main>
      </div>
    </div>
  )
}
