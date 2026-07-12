import { useState } from "react";

import { FOLDER_TREE } from "../data/folderTree";
import type { Panel } from "../types/panel";
import {
  countCompletedForBranch,
  countCompletedForFolder,
} from "../utils/panelFilters";

interface FolderTreeProps {
  panels: Panel[];
  selectedFolder: string | null;
  onSelectFolder: (folder: string | null) => void;
}

export function FolderTree({
  panels,
  selectedFolder,
  onSelectFolder,
}: FolderTreeProps) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(FOLDER_TREE.map((b) => [b.label, true])),
  );

  const totalCompleted = panels.filter((p) => p.status === "completed").length;

  const toggleBranch = (label: string) => {
    setExpanded((prev) => ({ ...prev, [label]: !prev[label] }));
  };

  return (
    <nav className="folder-tree" aria-label="Result folders">
      <button
        type="button"
        className={`folder-tree__item folder-tree__item--all${
          selectedFolder === null ? " folder-tree__item--selected" : ""
        }`}
        onClick={() => onSelectFolder(null)}
      >
        <span>All</span>
        {totalCompleted > 0 && (
          <span className="folder-tree__badge">{totalCompleted}</span>
        )}
      </button>

      {FOLDER_TREE.map((branch) => {
        const branchCount = countCompletedForBranch(panels, branch.label);
        const isBranchSelected = selectedFolder === branch.label;
        const isOpen = expanded[branch.label] ?? true;

        return (
          <div key={branch.label} className="folder-tree__branch">
            <button
              type="button"
              className={`folder-tree__item folder-tree__item--branch${
                isBranchSelected ? " folder-tree__item--selected" : ""
              }`}
              onClick={() => onSelectFolder(branch.label)}
            >
              <span
                className="folder-tree__toggle"
                onClick={(e) => {
                  e.stopPropagation();
                  toggleBranch(branch.label);
                }}
                onKeyDown={(e) => e.stopPropagation()}
                role="presentation"
              >
                {isOpen ? "▼" : "▶"}
              </span>
              <span>{branch.label}</span>
              {branchCount > 0 && (
                <span className="folder-tree__badge">{branchCount}</span>
              )}
            </button>

            {isOpen &&
              branch.children.map((leaf) => {
                const leafCount = countCompletedForFolder(panels, leaf);
                const leafLabel = leaf.split("/").pop() ?? leaf;
                return (
                  <button
                    key={leaf}
                    type="button"
                    className={`folder-tree__item folder-tree__item--leaf${
                      selectedFolder === leaf
                        ? " folder-tree__item--selected"
                        : ""
                    }`}
                    onClick={() => onSelectFolder(leaf)}
                  >
                    <span>{leafLabel}</span>
                    {leafCount > 0 && (
                      <span className="folder-tree__badge">{leafCount}</span>
                    )}
                  </button>
                );
              })}
          </div>
        );
      })}
    </nav>
  );
}
