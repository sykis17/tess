export type ChainProfile = "L0" | "L1" | "L1+" | "L2" | "L3" | "L4";

/** Sentinel: omit chain_profile from WS JSON so server resolves from product mode. */
export type ChainProfileSelection = ChainProfile | "default";

export const CHAIN_PROFILES: ChainProfile[] = [
  "L0",
  "L1",
  "L1+",
  "L2",
  "L3",
  "L4",
];

const PROFILE_LABELS: Record<ChainProfile, string> = {
  L0: "Direct",
  L1: "Routed",
  "L1+": "Parallel",
  L2: "Reviewed",
  L3: "Grounded",
  L4: "Full chain",
};

export function formatChainProfileDisplayName(profile: string): string {
  if (profile in PROFILE_LABELS) {
    return PROFILE_LABELS[profile as ChainProfile];
  }
  return profile;
}

interface ChainProfileSelectorProps {
  value: ChainProfileSelection;
  onChange: (profile: ChainProfileSelection) => void;
}

export function ChainProfileSelector({
  value,
  onChange,
}: ChainProfileSelectorProps) {
  return (
    <label className="chain-selector">
      <span className="chain-selector__label">Depth</span>
      <select
        className="chain-selector__select"
        value={value}
        onChange={(event) =>
          onChange(event.target.value as ChainProfileSelection)
        }
        aria-label="Chain profile"
      >
        <option value="default">Auto (by mode)</option>
        {CHAIN_PROFILES.map((profile) => (
          <option key={profile} value={profile}>
            {profile} — {PROFILE_LABELS[profile]}
          </option>
        ))}
      </select>
    </label>
  );
}
