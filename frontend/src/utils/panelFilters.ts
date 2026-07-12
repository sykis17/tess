import type { Panel } from "../types/panel";

const INTERMEDIATE_TIERS = new Set(["mayor", "micro", "usable"]);

export function isIntermediatePanel(panel: Panel): boolean {
  return panel.data_tier !== undefined && INTERMEDIATE_TIERS.has(panel.data_tier);
}

/** Panels visible in the default results wall (hide combiner intermediate tiers). */
export function filterWallPanels(panels: Panel[]): Panel[] {
  const latestProcessing = new Map<string, Panel>();

  for (const panel of panels) {
    if (panel.status === "processing") {
      latestProcessing.set(panel.panel_id, panel);
    }
  }

  const visible: Panel[] = [];

  for (const panel of panels) {
    if (isIntermediatePanel(panel)) {
      continue;
    }
    if (panel.status === "processing") {
      const latest = latestProcessing.get(panel.panel_id);
      if (latest && latest !== panel) {
        continue;
      }
    }
    visible.push(panel);
  }

  return visible;
}

export function panelMatchesFolder(panel: Panel, selectedFolder: string | null): boolean {
  if (!selectedFolder) {
    return true;
  }
  if (selectedFolder.includes("/")) {
    return panel.folder_path === selectedFolder;
  }
  return panel.folder_path.startsWith(`${selectedFolder}/`);
}

export function countCompletedForFolder(panels: Panel[], folderPath: string): number {
  return panels.filter(
    (p) => p.status === "completed" && p.folder_path === folderPath,
  ).length;
}

export function countCompletedForBranch(panels: Panel[], branchLabel: string): number {
  const prefix = `${branchLabel}/`;
  return panels.filter(
    (p) => p.status === "completed" && p.folder_path.startsWith(prefix),
  ).length;
}
