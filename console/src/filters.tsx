import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

interface Filters {
  project: string;
  app: string;
  setProject: (value: string) => void;
  setApp: (value: string) => void;
}

const Context = createContext<Filters | null>(null);

/** Project and application filters shared by Overview and Logs, and cleared with the session. */
export function FiltersProvider({ children }: { children: ReactNode }) {
  const [project, setProject] = useState("");
  const [app, setApp] = useState("");
  const value = useMemo(() => ({ project, app, setProject, setApp }), [project, app]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export const useFilters = () => {
  const value = useContext(Context);
  if (!value) throw new Error("useFilters needs FiltersProvider");
  return value;
};
