import { useMemo, useRef, useEffect, useState } from "react";

import type { Panel } from "../types/panel";

export const PIPELINE_STAGES = [
  "routing",
  "agents",
  "combining",
  "defense",
  "presenting",
  "done",
] as const;

export type PipelineStageId = (typeof PIPELINE_STAGES)[number];

const STAGE_LABELS: Record<PipelineStageId, string> = {
  routing: "Routing",
  agents: "Agents",
  combining: "Combining",
  defense: "Defense",
  presenting: "Presenting",
  done: "Done",
};

const ROUTING_NAMES = new Set(["Wide Receiver"]);
const COMBINING_NAMES = new Set(["Combiner Mayor", "Combiner Micro", "Collector"]);
const DEFENSE_NAMES = new Set(["Defense Delegator", "Defense Review"]);
const PRESENTING_NAMES = new Set(["Presenter", "Direct Responder"]);

function stageForAgentDisplayName(name: string): PipelineStageId {
  if (ROUTING_NAMES.has(name)) return "routing";
  if (COMBINING_NAMES.has(name)) return "combining";
  if (DEFENSE_NAMES.has(name)) return "defense";
  if (PRESENTING_NAMES.has(name)) return "presenting";
  return "agents";
}

function allowsCombiners(profile: string): boolean {
  return profile === "L4";
}

function allowsDefense(profile: string): boolean {
  return profile === "L2" || profile === "L3" || profile === "L4";
}

export function predictedStages(
  chainProfile: string | undefined,
  agentsInvolved: string[],
): PipelineStageId[] {
  const profile = chainProfile ?? "L4";

  if (profile === "L0") {
    return ["presenting", "done"];
  }

  const stages: PipelineStageId[] = [];
  const seen = new Set<PipelineStageId>();

  for (const name of agentsInvolved) {
    const stage = stageForAgentDisplayName(name);
    if (!seen.has(stage)) {
      stages.push(stage);
      seen.add(stage);
    }
  }

  let filtered = stages;
  if (!allowsCombiners(profile)) {
    filtered = filtered.filter((s) => s !== "combining");
  }
  if (!allowsDefense(profile)) {
    filtered = filtered.filter((s) => s !== "defense");
  }

  if (!seen.has("presenting")) {
    filtered.push("presenting");
  }
  filtered.push("done");

  const ordered = new Set(filtered);
  return PIPELINE_STAGES.filter((s) => ordered.has(s));
}

export function formatStageLabel(stage: string): string {
  return STAGE_LABELS[stage as PipelineStageId] ?? stage;
}

function agentsForCurrentStage(
  stage: string | null | undefined,
  agentsInvolved: string[],
): string[] {
  if (!stage) {
    return agentsInvolved.filter(
      (name) =>
        !ROUTING_NAMES.has(name) &&
        !COMBINING_NAMES.has(name) &&
        !DEFENSE_NAMES.has(name) &&
        !PRESENTING_NAMES.has(name) &&
        name !== "Resource Finder" &&
        name !== "Resource Reader",
    );
  }

  switch (stage) {
    case "routing":
      return agentsInvolved.filter((name) => ROUTING_NAMES.has(name));
    case "combining":
      return agentsInvolved.filter((name) => COMBINING_NAMES.has(name));
    case "defense":
      return agentsInvolved.filter((name) => DEFENSE_NAMES.has(name));
    case "presenting":
      return agentsInvolved.filter((name) => PRESENTING_NAMES.has(name));
    case "agents":
    default:
      return agentsInvolved.filter(
        (name) =>
          !ROUTING_NAMES.has(name) &&
          !COMBINING_NAMES.has(name) &&
          !DEFENSE_NAMES.has(name) &&
          !PRESENTING_NAMES.has(name) &&
          name !== "Resource Finder" &&
          name !== "Resource Reader",
      );
  }
}

function formatStatusSubtitle(panel: Panel): string {
  const content = panel.content;
  if (panel.is_streaming && content.length > 100) {
    return `${content.slice(0, 100).trim()}…`;
  }
  return content;
}

function isInFlight(panel: Panel): boolean {
  return panel.status === "processing" || panel.status === "review_passed";
}

export interface PipelineStatus {
  visible: boolean;
  currentStage: string | null;
  predictedSteps: PipelineStageId[];
  activeAgents: string[];
  subtitle: string | null;
  elapsedMs: number;
  focusPanelId: string | null;
}

export function usePipelineStatus(
  panels: Panel[],
  isProcessing: boolean,
): PipelineStatus {
  const startTimesRef = useRef<Map<string, number>>(new Map());
  const [tick, setTick] = useState(0);

  const inFlight = useMemo(
    () => panels.filter(isInFlight),
    [panels],
  );

  const focusPanel = inFlight.length > 0 ? inFlight[inFlight.length - 1] : null;

  useEffect(() => {
    if (!isProcessing) {
      startTimesRef.current.clear();
      return;
    }
    for (const panel of inFlight) {
      if (!startTimesRef.current.has(panel.panel_id)) {
        startTimesRef.current.set(panel.panel_id, Date.now());
      }
    }
  }, [isProcessing, inFlight]);

  useEffect(() => {
    if (!isProcessing || inFlight.length === 0) {
      return;
    }
    const id = window.setInterval(() => setTick((value) => value + 1), 1000);
    return () => window.clearInterval(id);
  }, [isProcessing, inFlight]);

  const elapsedMs = useMemo(() => {
    if (!focusPanel) return 0;
    const start = startTimesRef.current.get(focusPanel.panel_id) ?? Date.now();
    return Date.now() - start;
  }, [focusPanel, tick]);

  const earliestProcessing = useMemo(() => {
    if (!focusPanel) return null;
    return (
      panels.find(
        (p) =>
          p.panel_id === focusPanel.panel_id && p.status === "processing",
      ) ?? focusPanel
    );
  }, [panels, focusPanel]);

  const predictedSteps = useMemo(() => {
    const agents = earliestProcessing?.agents_involved ?? focusPanel?.agents_involved ?? [];
    const profile = focusPanel?.output_level ?? earliestProcessing?.output_level;
    return predictedStages(profile, agents);
  }, [earliestProcessing, focusPanel]);

  const stageAgents = useMemo(() => {
    const agents = focusPanel?.agents_involved ?? [];
    return agentsForCurrentStage(focusPanel?.pipeline_stage, agents);
  }, [focusPanel]);

  return {
    visible: isProcessing && focusPanel !== null,
    currentStage: focusPanel?.pipeline_stage ?? null,
    predictedSteps,
    activeAgents: stageAgents,
    subtitle:
      focusPanel && focusPanel.status !== "completed"
        ? formatStatusSubtitle(focusPanel)
        : null,
    elapsedMs,
    focusPanelId: focusPanel?.panel_id ?? null,
  };
}
