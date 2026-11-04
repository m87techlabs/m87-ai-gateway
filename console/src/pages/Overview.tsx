import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { CheckCircle2, Circle } from "lucide-react";
import { useState } from "react";
import { getJson, query } from "../api";
import { BarList, ColumnChart } from "../components/charts";
import { ScopeFilters, WINDOWS, WindowSelect } from "../components/filters";
import { LogDetail, LogTable } from "../components/logs";
import { Card, Empty, ErrorNotice, LiveDot, Notice, PageHeader, Skeleton, Stat } from "../components/ui";
import { useFilters } from "../filters";
import { count, latency, number, percent } from "../format";
import { href } from "../router";
import type { Application, Diagnostics, LogsPage, Setup, Summary, Usage } from "../types";

const LIVE = 10_000;

function GettingStarted() {
  const setup = useQuery({ queryKey: ["setup"], queryFn: () => getJson<Setup>("/setup") });
  const apps = useQuery({
    queryKey: ["apps"],
    queryFn: async () => (await getJson<{ items: Application[] }>("/apps")).items,
  });
  const usage = useQuery({
    queryKey: ["overview", "all-time"],
    queryFn: () => getJson<Summary>("/overview?hours=2160"),
  });
  if (!setup.data || !apps.data || !usage.data) return null;
  if (usage.data.requests > 0) return null;
  const steps = [
    {
      done: setup.data.connections.some((item) => item.configured && item.config.enabled),
      label: "Connect a model provider",
      link: href("providers"),
    },
    { done: apps.data.length > 0, label: "Create an application and copy its key", link: href("applications") },
    { done: false, label: "Point your app at the gateway, or send a request from the Playground", link: href("playground") },
  ];
  return (
    <Card title="Get started" description="Three steps to your first request through the gateway.">
      <ol className="stack" style={{ margin: 0, padding: 0, listStyle: "none" }}>
        {steps.map((step) => (
          <li key={step.label} className="row" style={{ flexWrap: "nowrap" }}>
            {step.done ? (
              <CheckCircle2 size={16} className="muted" aria-label="Done" style={{ flex: "none" }} />
            ) : (
              <Circle size={16} className="muted" aria-label="To do" style={{ flex: "none" }} />
            )}
            <a href={step.link}>{step.label}</a>
          </li>
        ))}
      </ol>
    </Card>
  );
}

function Readiness() {
  const diagnostics = useQuery({
    queryKey: ["diagnostics"],
    queryFn: () => getJson<Diagnostics>("/diagnostics"),
    refetchInterval: LIVE,
  });
  const failing = diagnostics.data?.checks.filter((item) => !item.ok) ?? [];
  if (!failing.length) return null;
  return (
    <Notice tone="warning" title="The gateway needs configuration before it can serve requests">
      <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
        {failing.map((item) => (
          <li key={item.name}>{item.message}</li>
        ))}
      </ul>
    </Notice>
  );
}

export function Overview() {
  const { project, app } = useFilters();
  const [hours, setHours] = useState(24);
  const [open, setOpen] = useState<string | null>(null);
  const scope = { project_id: project, app_id: app };
  const summary = useQuery({
    queryKey: ["overview", project, app, hours],
    queryFn: () => getJson<Summary>(`/overview${query({ ...scope, hours })}`),
    refetchInterval: LIVE,
    placeholderData: keepPreviousData,
  });
  const usage = useQuery({
    queryKey: ["usage", project, app, hours],
    queryFn: () => getJson<Usage>(`/usage${query({ ...scope, hours })}`),
    refetchInterval: LIVE,
    placeholderData: keepPreviousData,
  });
  const recent = useQuery({
    queryKey: ["logs", "recent", project, app],
    queryFn: () => getJson<LogsPage>(`/logs${query({ ...scope, limit: 8 })}`),
    refetchInterval: LIVE,
    placeholderData: keepPreviousData,
  });
  const data = summary.data;
  const rangeLabel = WINDOWS.find((item) => item.hours === hours)?.label.toLowerCase();
  return (
    <>
      <PageHeader title="Overview" description="Traffic through this gateway." actions={<LiveDot paused={summary.isError} />} />
      <div className="filters">
        <WindowSelect hours={hours} onChange={setHours} />
        <ScopeFilters />
      </div>
      <Readiness />
      <GettingStarted />
      {summary.isError && <ErrorNotice error={summary.error} retry={() => summary.refetch()} />}
      <div className="grid-4">
        <Stat
          label="Requests"
          value={data ? number(data.requests) : "—"}
          detail={data ? `${number(data.cache_hits)} from cache` : undefined}
        />
        <Stat
          label="Tokens"
          value={data ? number(data.total_tokens) : "—"}
          detail={data ? `${number(data.prompt_tokens)} in · ${number(data.completion_tokens)} out` : undefined}
        />
        <Stat
          label="Errors"
          value={data ? number(data.errors) : "—"}
          detail={data ? `${percent(data.errors, data.requests)} of requests` : undefined}
        />
        <Stat
          label="Average latency"
          value={data ? latency(data.average_latency_ms) : "—"}
          detail={data?.usage_unknown ? `${count(data.usage_unknown, "request")} without usage` : undefined}
        />
      </div>
      {usage.isError && <ErrorNotice error={usage.error} retry={() => usage.refetch()} />}
      <Card className="grid-2">
        {usage.data ? (
          <>
            <ColumnChart title="Requests" series={usage.data.series} field="requests" unit="requests" />
            <ColumnChart title="Tokens" series={usage.data.series} field="total_tokens" unit="tokens" />
          </>
        ) : (
          <Skeleton lines={5} />
        )}
      </Card>
      <div className="grid-2">
        <Card title="Applications" description={`Tokens, ${rangeLabel}`}>
          {usage.data ? (
            <BarList
              unit="tokens"
              empty="No application traffic yet"
              items={usage.data.by_app.map((item) => ({
                key: item.app_id ?? "unauthenticated",
                label: item.app_id ?? "Unauthenticated",
                value: item.total_tokens ?? 0,
                href: item.app_id ? href("applications", item.app_id) : undefined,
                detail: `${count(item.requests, "request")} · ${count(item.errors, "error")}`,
              }))}
            />
          ) : (
            <Skeleton />
          )}
        </Card>
        <Card title="Models" description={`Tokens, ${rangeLabel}`}>
          {usage.data ? (
            <BarList
              unit="tokens"
              empty="No model traffic yet"
              items={usage.data.by_model.map((item) => ({
                key: item.model ?? "none",
                label: item.model ?? "Rejected before routing",
                value: item.total_tokens ?? 0,
                detail: `${count(item.requests, "request")} · ${count(item.errors, "error")}`,
              }))}
            />
          ) : (
            <Skeleton />
          )}
        </Card>
      </div>
      <Card
        title="Recent requests"
        actions={<a href={href("logs")}>View all logs</a>}
      >
        {recent.isError && <ErrorNotice error={recent.error} retry={() => recent.refetch()} />}
        {recent.isPending && <Skeleton lines={5} />}
        {recent.data && (
          <LogTable
            items={recent.data.items}
            onOpen={setOpen}
            empty={<Empty title="No requests yet">Requests appear here as soon as they pass through the gateway.</Empty>}
          />
        )}
      </Card>
      {open && <LogDetail requestId={open} onClose={() => setOpen(null)} />}
    </>
  );
}
