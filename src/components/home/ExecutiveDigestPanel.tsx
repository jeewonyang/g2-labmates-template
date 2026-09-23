import { ExecutiveBriefClient } from "@/components/home/ExecutiveBriefClient";
import { listAreas } from "@/lib/services/areas";
import { listProjects } from "@/lib/services/projects";
import { listResources } from "@/lib/services/resources";
import { getDailyExecutiveBrief } from "@/lib/services/executive-digest";
import {
  getBrainstormingAreaId,
  getDigestLibraryIndex,
} from "@/lib/services/research";

/** Latest daily Scientific Research output, grouped for a fast scan. */
export async function ExecutiveDigestPanel() {
  const [brief, library, projects, resources, areas, brainstormingId] =
    await Promise.all([
      getDailyExecutiveBrief(),
      getDigestLibraryIndex(),
      listProjects(),
      listResources(),
      listAreas(),
      getBrainstormingAreaId(),
    ]);

  return (
    <ExecutiveBriefClient
      brief={brief}
      library={library}
      targets={{
        projects: projects
          .filter((project) => project.status === "active")
          .map((project) => ({ id: project.id, title: project.title })),
        // Every unfiled paper is its own resource inside Brainstorming. Those
        // are entries, not destinations, so they stay out of the picker.
        resources: resources
          .filter((resource) => resource.area?.id !== brainstormingId)
          .map((resource) => ({ id: resource.id, title: resource.title })),
        areas: areas
          .filter((area) => area.id !== brainstormingId)
          .map((area) => ({ id: area.id, title: area.title })),
      }}
    />
  );
}
