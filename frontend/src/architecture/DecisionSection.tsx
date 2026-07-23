import type { ReactNode } from 'react'

type DecisionSectionProps = {
  id: string
  number: string
  title: string
  children: ReactNode
}

export function DecisionSection({ id, number, title, children }: DecisionSectionProps) {
  return (
    <section className="arch-decision" id={id} data-arch-section={id}>
      <p className="arch-decision-eyebrow">Decision {number}</p>
      <h2>{title}</h2>
      {children}
    </section>
  )
}

type BlockProps = {
  label: string
  children: ReactNode
}

export function ArchBlock({ label, children }: BlockProps) {
  return (
    <div className="arch-block">
      <h3>{label}</h3>
      {children}
    </div>
  )
}

export function FieldNote({ children }: { children: ReactNode }) {
  return (
    <aside className="arch-field-note">
      <strong>Field note</strong>
      {children}
    </aside>
  )
}

export function LimitationNote({ children }: { children: ReactNode }) {
  return (
    <aside className="arch-limitation-note" id="known-limitation">
      <strong>Known limitation</strong>
      {children}
    </aside>
  )
}

export function DiagramFrame({
  caption,
  children,
}: {
  caption: string
  children: ReactNode
}) {
  return (
    <figure className="arch-diagram" data-arch-diagram="">
      {children}
      <figcaption className="arch-diagram-caption">{caption}</figcaption>
    </figure>
  )
}
