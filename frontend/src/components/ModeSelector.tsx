export type ProductMode = "auto" | "research" | "planner" | "coding" | "builder";

export const PRODUCT_MODES: ProductMode[] = [
  "auto",
  "research",
  "planner",
  "coding",
  "builder",
];

const MODE_LABELS: Record<ProductMode, string> = {
  auto: "Auto",
  research: "Research",
  planner: "Planner",
  coding: "Coding",
  builder: "Builder",
};

export function formatProductModeDisplayName(mode: string): string {
  if (mode in MODE_LABELS) {
    return MODE_LABELS[mode as ProductMode];
  }
  return mode.charAt(0).toUpperCase() + mode.slice(1);
}

interface ModeSelectorProps {
  value: ProductMode;
  onChange: (mode: ProductMode) => void;
}

export function ModeSelector({ value, onChange }: ModeSelectorProps) {
  return (
    <label className="mode-selector">
      <span className="mode-selector__label">Mode</span>
      <select
        className="mode-selector__select"
        value={value}
        onChange={(event) => onChange(event.target.value as ProductMode)}
        aria-label="Product mode"
      >
        {PRODUCT_MODES.map((mode) => (
          <option key={mode} value={mode}>
            {MODE_LABELS[mode]}
          </option>
        ))}
      </select>
    </label>
  );
}
