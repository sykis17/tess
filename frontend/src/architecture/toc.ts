export const TOC_ITEMS = [
  { id: 'self-report', label: 'Self-report /health' },
  { id: 'adapters', label: 'CloudAdapter pattern' },
  { id: 'failover', label: 'Failover policy' },
  { id: 'onboarding', label: 'Onboarding saga' },
] as const

export type TocId = (typeof TOC_ITEMS)[number]['id']
