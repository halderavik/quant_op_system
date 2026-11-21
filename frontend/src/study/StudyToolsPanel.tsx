import { useState } from "react";
import { cn } from "../ui";
import { LanguagesPanel } from "./LanguagesPanel";
import { SegmentsPanel } from "./SegmentsPanel";
import { TrackingPanel } from "./TrackingPanel";

type Tool = "tracking" | "languages" | "segments";

const TOOLS: [Tool, string][] = [
  ["tracking", "Tracking"],
  ["languages", "Languages"],
  ["segments", "Segments"],
];

/** Study tools: tracking waves, questionnaire languages, and segmentation. */
export function StudyToolsPanel({
  projectId,
  projectName,
  onOpenProject,
  onChanged,
}: {
  projectId: string;
  projectName: string;
  onOpenProject: (projectId: string) => Promise<void> | void;
  onChanged: () => Promise<void> | void;
}) {
  const [tool, setTool] = useState<Tool>("tracking");
  return (
    <div className="space-y-4 p-4 sm:p-5">
      <div aria-label="Study tools" className="flex gap-1 border-b border-line" role="tablist">
        {TOOLS.map(([value, label]) => (
          <button
            aria-selected={tool === value}
            className={cn(
              "-mb-px border-b-2 px-3 py-1.5 text-sm font-medium",
              tool === value ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink",
            )}
            key={value}
            onClick={() => setTool(value)}
            role="tab"
            type="button"
          >
            {label}
          </button>
        ))}
      </div>
      {tool === "tracking" && <TrackingPanel onOpenProject={onOpenProject} projectId={projectId} projectName={projectName} />}
      {tool === "languages" && <LanguagesPanel projectId={projectId} />}
      {tool === "segments" && <SegmentsPanel onChanged={onChanged} projectId={projectId} />}
    </div>
  );
}
