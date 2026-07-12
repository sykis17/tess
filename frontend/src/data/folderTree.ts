/**
 * Virtual folder tree — keep in sync with app/core/folder_tree.py
 */
export const FOLDER_TREE = [
  { label: "Science", children: ["Science/Chemistry", "Science/Biology"] },
  { label: "Social Studies", children: ["Social Studies/Economics"] },
  { label: "Arts", children: ["Arts/Visual"] },
  { label: "Design", children: ["Design/UI"] },
  { label: "Coding", children: ["Coding/Projects"] },
  { label: "Research", children: ["Research/Topics"] },
  { label: "Assistant", children: ["Assistant/General"] },
  { label: "Media", children: ["Media/Photo", "Media/Video", "Media/Audio"] },
] as const;

export type FolderBranch = (typeof FOLDER_TREE)[number];
