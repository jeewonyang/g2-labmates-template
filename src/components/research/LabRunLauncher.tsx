"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { Loader2, Play } from "lucide-react";
import { launchLabRunAction } from "@/lib/actions";
import { Button } from "@/components/ui/primitives";
import { Field, Input, Select, Textarea } from "@/components/ui/inputs";
import { LabProjectPicker, labProjectReady, type LabProjectChoice } from "@/components/research/LabProjectPicker";

type Assay = "flow" | "ultrasound" | "primer-design";

const ASSAY_HELP: Record<Assay, { path: string; placeholder: string; instructions: string }> = {
  flow: {
    path: "Run folder (.fcs / .mqd, optional .wsp)",
    placeholder: "D:\\Data\\MACSQuant\\2026-09-20",
    instructions: "e.g. Compare each construct with and without PPV. Is BFP a positive control here?",
  },
  ultrasound: {
    path: "Acquisition folder (plate, manual, BURST or in-vivo)",
    placeholder: "D:\\Data\\Verasonics\\260920_GE_plate",
    instructions: "e.g. Dox dose response, group by dox; report the stable voltage window.",
  },
  "primer-design": {
    path: "Starting plasmid map (.dna) or a folder of maps",
    placeholder: "labserf\\Sequences\\MyConstructs\\my-plasmid.dna",
    instructions:
      "e.g. Delete GvpA (1343..1555) and put a GS linker in its place; Gibson, primers to order.",
  },
};

const lines = (text: string) =>
  text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

/**
 * Launch one LabSerf job and have it land in the notebook.
 *
 * The request id is minted per submit so a double click reuses one run. The
 * form sends data paths and their instructions only - the runner owns the
 * commands, the model and where outputs go.
 */
export function LabRunLauncher({
  projects,
  defaultProject,
  disabledReason,
}: {
  projects: Array<{ code: string }>;
  defaultProject?: string;
  disabledReason?: string | null;
}) {
  const router = useRouter();
  const [assay, setAssay] = useState<Assay>("flow");
  const initialProject = (): LabProjectChoice =>
    projects.length
      ? { code: defaultProject || projects[0].code, isNew: false }
      : { code: "", isNew: true };
  const [project, setProject] = useState<LabProjectChoice>(initialProject);
  const [inputPath, setInputPath] = useState("");
  const [dnaPaths, setDnaPaths] = useState("");
  const [name, setName] = useState("");
  const [instructions, setInstructions] = useState("");
  const [negativeControl, setNegativeControl] = useState("");
  const [compare, setCompare] = useState("");
  const [highlight, setHighlight] = useState("");
  const [pipelineOnly, setPipelineOnly] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const help = ASSAY_HELP[assay];

  function submit() {
    setError(null);
    setNotice(null);
    start(async () => {
      try {
        await launchLabRunAction({
          clientRequestId: crypto.randomUUID(),
          assay,
          projectCode: project.code.trim(),
          newProject: project.isNew || undefined,
          mode: pipelineOnly && assay !== "primer-design" ? "pipeline" : "agent",
          inputPath,
          dnaPaths: assay === "primer-design" ? lines(dnaPaths) : undefined,
          instructions,
          name: name || undefined,
          options:
            assay === "flow"
              ? {
                  negativeControl: negativeControl || undefined,
                  highlight: highlight || undefined,
                  compare: lines(compare),
                }
              : undefined,
        });
        setNotice("Launched. It appears under Runs and files a notebook entry when it finishes.");
        setInputPath("");
        setDnaPaths("");
        setInstructions("");
        setName("");
        // A project created by this launch is now an ordinary Active project.
        if (project.isNew) setProject({ code: project.code.trim(), isNew: false });
        router.refresh();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Could not launch this run.");
      }
    });
  }

  if (disabledReason) {
    return <p className="text-sm text-[var(--amber)]">{disabledReason}</p>;
  }

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Analysis">
          <Select value={assay} onChange={(e) => setAssay(e.target.value as Assay)}>
            <option value="flow">Flow cytometry</option>
            <option value="ultrasound">Ultrasound</option>
            <option value="primer-design">Primer design</option>
          </Select>
        </Field>
        <LabProjectPicker projects={projects} value={project} onChange={setProject} />
        <Field label="Experiment name (optional)">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="ePPV in HEK, dox series" />
        </Field>
      </div>

      <Field label={help.path}>
        <Input
          value={inputPath}
          onChange={(e) => setInputPath(e.target.value)}
          placeholder={help.placeholder}
          spellCheck={false}
        />
      </Field>

      {assay === "primer-design" && (
        <Field label="More maps, one path per line (insert donors, parts)">
          <Textarea rows={2} value={dnaPaths} onChange={(e) => setDnaPaths(e.target.value)} spellCheck={false} />
        </Field>
      )}

      {assay === "flow" && (
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Negative-control well (substring)">
            <Input value={negativeControl} onChange={(e) => setNegativeControl(e.target.value)} placeholder="untransfected" />
          </Field>
          <Field label="Comparisons, one 'A,B' per line">
            <Textarea rows={2} value={compare} onChange={(e) => setCompare(e.target.value)} placeholder={"GvpC,GvpC+PPV"} />
          </Field>
          <Field label="Highlight condition (orange)">
            <Input value={highlight} onChange={(e) => setHighlight(e.target.value)} />
          </Field>
        </div>
      )}

      <Field label="Instructions for the agent">
        <Textarea rows={3} value={instructions} onChange={(e) => setInstructions(e.target.value)} placeholder={help.instructions} />
      </Field>

      <div className="flex flex-wrap items-center justify-between gap-2">
        {assay !== "primer-design" ? (
          <label className="flex items-center gap-2 text-xs text-[var(--ink-2)]">
            <input type="checkbox" checked={pipelineOnly} onChange={(e) => setPipelineOnly(e.target.checked)} />
            Pipeline only (no model; the entry records what ran, you write the interpretation)
          </label>
        ) : (
          <span className="text-xs text-[var(--ink-3)]">
            Designs land in LabSerf&apos;s Sequences/_designs staging folder, never in the collection.
          </span>
        )}
        <Button variant="primary" size="sm" onClick={submit} disabled={pending || !inputPath.trim() || !labProjectReady(project, projects)}>
          {pending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
          Launch
        </Button>
      </div>
      {error && <p className="text-xs text-[var(--red)]">{error}</p>}
      {notice && <p className="text-xs text-[var(--green)]">{notice}</p>}
    </div>
  );
}
