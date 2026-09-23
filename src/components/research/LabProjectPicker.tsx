"use client";

import { Field, Input, Select } from "@/components/ui/inputs";

export const NEW_PROJECT = "__new__";

export type LabProjectChoice = { code: string; isNew: boolean };

/** Letters and digits, starting with a letter - the ProjectID in every entry title. */
export const LAB_PROJECT_CODE = /^[A-Za-z][A-Za-z0-9]{0,39}$/;

/**
 * The project for a launch or a new entry: one of the Active projects, or a
 * new one (the owner, 2026-09-21). One picker for both surfaces. A new project
 * is created on submit - its Research-Private folder and an Active planner
 * project with the same name - not when it is typed.
 */
export function LabProjectPicker({
  projects,
  value,
  onChange,
}: {
  projects: Array<{ code: string }>;
  value: LabProjectChoice;
  onChange: (next: LabProjectChoice) => void;
}) {
  const invalid = value.isNew && value.code.trim() !== "" && !LAB_PROJECT_CODE.test(value.code.trim());
  const taken =
    value.isNew && projects.some((p) => p.code.toLowerCase() === value.code.trim().toLowerCase());
  return (
    <>
      <Field label="Project">
        <Select
          value={value.isNew ? NEW_PROJECT : value.code}
          onChange={(e) =>
            onChange(
              e.target.value === NEW_PROJECT
                ? { code: "", isNew: true }
                : { code: e.target.value, isNew: false },
            )
          }
        >
          {projects.map((p) => (
            <option key={p.code} value={p.code}>
              {p.code}
            </option>
          ))}
          <option value={NEW_PROJECT}>+ New project…</option>
        </Select>
      </Field>
      {value.isNew && (
        <Field label="New project name">
          <Input
            autoFocus
            value={value.code}
            onChange={(e) => onChange({ code: e.target.value, isNew: true })}
            placeholder="e.g. AcousticSwitch"
            spellCheck={false}
            maxLength={40}
          />
          <span className="mt-1 block text-[11px] text-[var(--ink-3)]">
            {invalid
              ? "Letters and digits only, starting with a letter."
              : taken
                ? "That project already exists - pick it from the list."
                : "Creates its notebook folder and an Active planner project with this name."}
          </span>
        </Field>
      )}
    </>
  );
}

export function labProjectReady(choice: LabProjectChoice, projects: Array<{ code: string }>): boolean {
  const code = choice.code.trim();
  if (!code) return false;
  if (!choice.isNew) return true;
  return LAB_PROJECT_CODE.test(code) && !projects.some((p) => p.code.toLowerCase() === code.toLowerCase());
}
