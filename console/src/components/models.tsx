import { useQueries, useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { getJson } from "../api";
import type { Setup } from "../types";
import { Button } from "./ui";

export const useSetup = () => useQuery({ queryKey: ["setup"], queryFn: () => getJson<Setup>("/setup") });

/** Models reported by each enabled connection. Unreachable servers simply list nothing. */
export function useDiscoveredModels() {
  const setup = useSetup();
  const connections = (setup.data?.connections ?? []).filter(
    (item) => item.configured && item.config.enabled && item.model_discovery,
  );
  const results = useQueries({
    queries: connections.map((item) => ({
      queryKey: ["models", item.provider],
      queryFn: async () => (await getJson<{ items: string[] }>(`/connections/${encodeURIComponent(item.provider)}/models`)).items,
      retry: false,
      staleTime: 60_000,
    })),
  });
  return [...new Set(results.flatMap((result) => result.data ?? []))].sort();
}

export function ModelPicker({ value, onChange }: { value: string[]; onChange: (models: string[]) => void }) {
  const discovered = useDiscoveredModels();
  const [manual, setManual] = useState("");
  const options = [...new Set(["auto", ...discovered, ...value])];
  const toggle = (model: string, checked: boolean) =>
    onChange(checked ? [...value, model] : value.filter((item) => item !== model));
  const add = () => {
    const model = manual.trim();
    if (model && !value.includes(model)) onChange([...value, model]);
    setManual("");
  };
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="pick-list" role="group" aria-label="Allowed models">
        {options.map((model) => (
          <label key={model}>
            <input type="checkbox" checked={value.includes(model)} onChange={(event) => toggle(model, event.target.checked)} />
            {model === "auto" ? "auto (the gateway chooses)" : model}
          </label>
        ))}
      </div>
      <div className="row" style={{ flexWrap: "nowrap" }}>
        <input
          aria-label="Add a model by name"
          placeholder="provider:model"
          value={manual}
          onChange={(event) => setManual(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              add();
            }
          }}
        />
        <Button small icon={<Plus size={14} aria-hidden />} onClick={add} disabled={!manual.trim()}>
          Add
        </Button>
      </div>
    </div>
  );
}

export const ModelChips = ({ models }: { models: string[] }) => (
  <div className="chips">
    {models.map((model) => (
      <span className="chip" key={model}>
        {model}
      </span>
    ))}
  </div>
);

