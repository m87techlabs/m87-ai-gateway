import { useQuery } from "@tanstack/react-query";
import { getJson } from "../api";
import { useFilters } from "../filters";
import type { Project } from "../types";

export const useProjects = () =>
  useQuery({
    queryKey: ["projects"],
    queryFn: async () => (await getJson<{ items: Project[] }>("/projects")).items,
  });

export const useAppNames = () =>
  useQuery({
    queryKey: ["app-names"],
    queryFn: async () => (await getJson<{ items: string[] }>("/app-names")).items,
  });

export function ScopeFilters() {
  const { project, app, setProject, setApp } = useFilters();
  const projects = useProjects();
  const names = useAppNames();
  const options = [...new Set([...(names.data ?? []), ...(app ? [app] : [])])].sort();
  return (
    <>
      <select aria-label="Project" value={project} onChange={(event) => setProject(event.target.value)}>
        <option value="">All projects</option>
        {project && !projects.data?.some((item) => item.project_id === project) && (
          <option value={project}>{project}</option>
        )}
        {projects.data?.map((item) => (
          <option key={item.project_id} value={item.project_id}>
            {item.name}
          </option>
        ))}
      </select>
      <select aria-label="Application" value={app} onChange={(event) => setApp(event.target.value)}>
        <option value="">All applications</option>
        {options.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </select>
    </>
  );
}

export const WINDOWS = [
  { hours: 24, label: "Last 24 hours" },
  { hours: 168, label: "Last 7 days" },
  { hours: 720, label: "Last 30 days" },
];

export const WindowSelect = ({ hours, onChange }: { hours: number; onChange: (value: number) => void }) => (
  <select aria-label="Time window" value={hours} onChange={(event) => onChange(Number(event.target.value))}>
    {WINDOWS.map((item) => (
      <option key={item.hours} value={item.hours}>
        {item.label}
      </option>
    ))}
  </select>
);
