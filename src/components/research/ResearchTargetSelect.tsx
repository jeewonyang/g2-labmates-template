"use client";

export type ResearchTargetOption = { id: string; title: string };

export const BRAINSTORMING_TARGET = "brainstorming";

export type ResearchTargetOptions = {
  projects: ResearchTargetOption[];
  resources: ResearchTargetOption[];
  areas: ResearchTargetOption[];
};

/**
 * The one destination picker for a paper: Brainstorming, or a project,
 * resource, or area. Both places that file a paper against a project - the
 * bibliography row on /research and the save control on the CEO Brief - use
 * this, so the vocabulary and the encoded value cannot drift apart.
 */
export function parseResearchTarget(value: string): {
  targetType?: "project" | "resource" | "area";
  targetId?: string;
} {
  if (!value || value === BRAINSTORMING_TARGET) return {};
  const [targetType, targetId] = value.split(":", 2);
  if (
    !targetId ||
    (targetType !== "project" && targetType !== "resource" && targetType !== "area")
  ) {
    return {};
  }
  return { targetType, targetId };
}

export function ResearchTargetSelect({
  value,
  onChange,
  disabled,
  ariaLabel,
  projects,
  resources,
  areas,
  className = "min-w-52",
}: ResearchTargetOptions & {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  ariaLabel: string;
  className?: string;
}) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      aria-label={ariaLabel}
      disabled={disabled}
      className={`${className} rounded-[var(--radius-sm)] border bg-[var(--surface)] px-2 py-1.5 text-xs text-[var(--ink)] disabled:opacity-40`}
    >
      <option value={BRAINSTORMING_TARGET}>Brainstorming · unfiled</option>
      {areas.length > 0 && (
        <optgroup label="Areas">
          {areas.map((area) => (
            <option key={area.id} value={`area:${area.id}`}>
              {area.title}
            </option>
          ))}
        </optgroup>
      )}
      {projects.length > 0 && (
        <optgroup label="Projects">
          {projects.map((project) => (
            <option key={project.id} value={`project:${project.id}`}>
              {project.title}
            </option>
          ))}
        </optgroup>
      )}
      {resources.length > 0 && (
        <optgroup label="Resources">
          {resources.map((resource) => (
            <option key={resource.id} value={`resource:${resource.id}`}>
              {resource.title}
            </option>
          ))}
        </optgroup>
      )}
    </select>
  );
}
