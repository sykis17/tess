import type { ChainProfile } from "./ChainProfileSelector";
import { CHAIN_PROFILES } from "./ChainProfileSelector";

interface CompareLevelsToggleProps {
  enabled: boolean;
  selectedLevels: ChainProfile[];
  onEnabledChange: (enabled: boolean) => void;
  onLevelsChange: (levels: ChainProfile[]) => void;
}

export function CompareLevelsToggle({
  enabled,
  selectedLevels,
  onEnabledChange,
  onLevelsChange,
}: CompareLevelsToggleProps) {
  const toggleLevel = (level: ChainProfile) => {
    if (selectedLevels.includes(level)) {
      onLevelsChange(selectedLevels.filter((item) => item !== level));
      return;
    }
    if (selectedLevels.length >= 3) {
      return;
    }
    onLevelsChange([...selectedLevels, level]);
  };

  return (
    <div className="compare-toggle">
      <label className="compare-toggle__enable">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => onEnabledChange(event.target.checked)}
        />
        <span>Compare levels</span>
      </label>
      {enabled && (
        <div className="compare-toggle__levels" role="group" aria-label="Levels to compare">
          {CHAIN_PROFILES.map((level) => (
            <label key={level} className="compare-toggle__level">
              <input
                type="checkbox"
                checked={selectedLevels.includes(level)}
                onChange={() => toggleLevel(level)}
              />
              <span>{level}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
