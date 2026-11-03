import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Boxes,
  Database,
  FlaskConical,
  FolderKanban,
  History as HistoryIcon,
  LayoutDashboard,
  Lock,
  Moon,
  Plug,
  ScrollText,
  Send,
  ShieldCheck,
  Sun,
  ToggleRight,
} from "lucide-react";
import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { ApiError, getJson, onSessionExpired, reachability, send } from "./api";
import { ConfirmProvider, Empty, ErrorNotice, Notice, Skeleton, ToastProvider } from "./components/ui";
import { FiltersProvider } from "./filters";
import { ApplicationDetail } from "./pages/ApplicationDetail";
import { Applications } from "./pages/Applications";
import { Audit, History } from "./pages/Admin";
import { Features } from "./pages/Features";
import { LogExport } from "./pages/LogExport";
import { Login } from "./pages/Login";
import { Logs } from "./pages/Logs";
import { Overview } from "./pages/Overview";
import { Playground } from "./pages/Playground";
import { Projects } from "./pages/Projects";
import { Providers } from "./pages/Providers";
import { Storage } from "./pages/Storage";
import { href, useRoute } from "./router";
import { currentTheme, saveTheme, type Theme } from "./theme";

const NAVIGATION: { group: string; items: { id: string; label: string; icon: ReactNode }[] }[] = [
  {
    group: "Monitor",
    items: [
      { id: "overview", label: "Overview", icon: <LayoutDashboard size={16} aria-hidden /> },
      { id: "logs", label: "Logs", icon: <ScrollText size={16} aria-hidden /> },
    ],
  },
  {
    group: "Build",
    items: [
      { id: "applications", label: "Applications", icon: <Boxes size={16} aria-hidden /> },
      { id: "playground", label: "Playground", icon: <FlaskConical size={16} aria-hidden /> },
    ],
  },
  {
    group: "Configure",
    items: [
      { id: "providers", label: "Providers", icon: <Plug size={16} aria-hidden /> },
      { id: "features", label: "Features", icon: <ToggleRight size={16} aria-hidden /> },
      { id: "export", label: "Log export", icon: <Send size={16} aria-hidden /> },
    ],
  },
  {
    group: "Administer",
    items: [
      { id: "projects", label: "Projects", icon: <FolderKanban size={16} aria-hidden /> },
      { id: "history", label: "Configuration history", icon: <HistoryIcon size={16} aria-hidden /> },
      { id: "audit", label: "Audit log", icon: <ShieldCheck size={16} aria-hidden /> },
      { id: "storage", label: "Storage", icon: <Database size={16} aria-hidden /> },
    ],
  },
];

function Page() {
  const route = useRoute();
  const [view, detail] = route.path;
  switch (view) {
    case "overview":
      return <Overview />;
    case "logs":
      return <Logs requestId={route.params.get("request_id") ?? ""} />;
    case "applications":
      return detail ? <ApplicationDetail key={detail} appId={detail} /> : <Applications />;
    case "playground":
      return <Playground />;
    case "providers":
      return <Providers />;
    case "features":
      return <Features />;
    case "export":
      return <LogExport />;
    case "projects":
      return <Projects />;
    case "history":
      return <History />;
    case "audit":
      return <Audit />;
    case "storage":
      return <Storage />;
    default:
      return <Empty title="That page does not exist" />;
  }
}

/** One calm message during an outage. Checks for the gateway, then refreshes everything. */
function Reconnecting() {
  const client = useQueryClient();
  const reachable = useSyncExternalStore(reachability.subscribe, reachability.get);
  const wasReachable = useRef(reachable);
  useEffect(() => {
    if (reachable && !wasReachable.current) client.invalidateQueries();
    wasReachable.current = reachable;
    if (reachable) return;
    const timer = window.setInterval(() => void getJson("/session").catch(() => undefined), 3000);
    return () => window.clearInterval(timer);
  }, [reachable, client]);
  if (reachable) return null;
  return (
    <Notice tone="warning" title="The gateway can't be reached">
      Showing the last data received. This page reconnects by itself when the gateway is back.
    </Notice>
  );
}

function Shell({ onLock }: { onLock: () => void }) {
  const route = useRoute();
  const [theme, setTheme] = useState<Theme>(currentTheme);
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden>
            M87
          </span>
          AI Gateway
        </div>
        <nav aria-label="Main">
          {NAVIGATION.map((section) => (
            <div className="nav-group" key={section.group}>
              <span>{section.group}</span>
              {section.items.map((item) => (
                <a
                  key={item.id}
                  className={`nav-link${route.path[0] === item.id ? " active" : ""}`}
                  aria-current={route.path[0] === item.id ? "page" : undefined}
                  href={href(item.id)}
                >
                  {item.icon}
                  {item.label}
                </a>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-foot">
          <button
            type="button"
            className="button ghost small"
            onClick={() => {
              const next = theme === "dark" ? "light" : "dark";
              saveTheme(next);
              setTheme(next);
            }}
          >
            {theme === "dark" ? <Sun size={14} aria-hidden /> : <Moon size={14} aria-hidden />}
            {theme === "dark" ? "Light theme" : "Dark theme"}
          </button>
          <button type="button" className="button ghost small" onClick={onLock}>
            <Lock size={14} aria-hidden />
            Lock console
          </button>
        </div>
      </aside>
      <main>
        <div className="content">
          <Reconnecting />
          <Page />
        </div>
      </main>
    </div>
  );
}

export function App() {
  const client = useQueryClient();
  const [session, setSession] = useState(0);
  const check = useQuery({
    queryKey: ["session", session],
    queryFn: async () => {
      try {
        await getJson("/session");
        return true;
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return false;
        throw error;
      }
    },
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  useEffect(() => {
    if (check.data !== undefined) setSignedIn(check.data);
  }, [check.data]);
  useEffect(() => {
    onSessionExpired(() => {
      client.clear();
      setSignedIn(false);
    });
  }, [client]);

  // The sample app links here with ?request_id=, which predates client-side routes.
  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("request_id");
    if (requested && requested.length <= 128 && !window.location.hash) {
      window.location.hash = `#/logs?request_id=${encodeURIComponent(requested)}`;
    }
  }, []);

  if (signedIn === null) {
    return (
      <div className="login">
        {check.isError ? (
          <ErrorNotice error={check.error} retry={() => check.refetch()} />
        ) : (
          <div className="stack" style={{ width: 320 }}>
            <Skeleton />
          </div>
        )}
      </div>
    );
  }
  if (!signedIn) {
    return (
      <Login
        onSuccess={() => {
          setSession((value) => value + 1);
          setSignedIn(true);
        }}
      />
    );
  }
  return (
    <ToastProvider>
      <ConfirmProvider>
        {/* A new session remounts everything, so nothing from the last one can reappear. */}
        <FiltersProvider key={session}>
          <Shell
            key={session}
            onLock={async () => {
              try {
                await send("/session", { method: "DELETE" });
              } finally {
                client.cancelQueries();
                client.clear();
                setSignedIn(false);
              }
            }}
          />
        </FiltersProvider>
      </ConfirmProvider>
    </ToastProvider>
  );
}
