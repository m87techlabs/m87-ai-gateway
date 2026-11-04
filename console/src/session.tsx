import { createContext, useContext } from "react";

export interface Session {
  actor: string;
  role: "admin" | "readonly";
  method: "key" | "sso";
}

const SessionContext = createContext<Session | null>(null);
export const SessionProvider = SessionContext.Provider;
export const useSession = () => useContext(SessionContext);

/** Only hides what would be refused. The gateway enforces the role on every request. */
export const useReadOnly = () => useSession()?.role === "readonly";
