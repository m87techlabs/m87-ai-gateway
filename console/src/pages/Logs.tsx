import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Download, Search, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { call, getJson, query, send } from "../api";
import { ScopeFilters } from "../components/filters";
import { LogDetail, LogTable } from "../components/logs";
import { Badge, Button, Card, Empty, ErrorNotice, LiveDot, Notice, PageHeader, Skeleton, useConfirm, useToast } from "../components/ui";
import { useFilters } from "../filters";
import { count, number } from "../format";
import type { LoggingHealth, LogsPage } from "../types";

const PAGE = 50;

function Recording() {
  const health = useQuery({
    queryKey: ["logging-health"],
    queryFn: () => getJson<LoggingHealth>("/logging-health"),
    refetchInterval: 15_000,
  });
  const data = health.data;
  if (!data) return null;
  const delivery = data.export;
  const backlog = delivery?.enabled && (delivery.delivery_state === "retrying" || delivery.delivery_state === "storage_unavailable");
  return (
    <>
      {!data.ok && (
        <Notice tone="critical" title="Recording needs attention">
          {data.items
            .filter((item) => item.last_write_ok === false)
            .map((item) => `${item.destination}: ${number(item.failed_writes)} failed writes`)
            .join(" · ")}
          . Check <a href="#/storage">Storage</a>.
        </Notice>
      )}
      {backlog && (
        <Notice tone="warning" title="Log export is retrying">
          {number(delivery?.pending)} records are waiting, {number(delivery?.failed_attempts)} attempts have failed and{" "}
          {number(delivery?.dropped)} were dropped. Pending records survive a restart. See <a href="#/export">Log export</a>.
        </Notice>
      )}
      <div className="row muted">
        <Badge tone={data.capture_enabled ? "warning" : "neutral"}>Capture {data.capture_enabled ? "on" : "off"}</Badge>
        <small>
          Input and output kept {data.content_retention_days} days · request metadata {data.traffic_retention_days} days · usage{" "}
          {data.usage_retention_days} days
        </small>
      </div>
    </>
  );
}

export function Logs({ requestId }: { requestId: string }) {
  const { project, app } = useFilters();
  const toast = useToast();
  const confirm = useConfirm();
  const client = useQueryClient();
  const [search, setSearch] = useState(requestId);
  const [submitted, setSubmitted] = useState(requestId);
  const [status, setStatus] = useState("");
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [includeContent, setIncludeContent] = useState(false);
  const [open, setOpen] = useState<string | null>(requestId || null);
  const page = cursors.length - 1;
  const filters = { project_id: project, app_id: app, request_id: submitted, status };
  useEffect(() => {
    setCursors([null]);
  }, [project, app, submitted, status]);
  useEffect(() => {
    if (requestId) {
      setSearch(requestId);
      setSubmitted(requestId);
      setOpen(requestId);
    }
  }, [requestId]);
  const logs = useQuery({
    queryKey: ["logs", filters, cursors[page]],
    queryFn: () => getJson<LogsPage>(`/logs${query({ ...filters, limit: PAGE, cursor: cursors[page] })}`),
    // Only the newest page moves; an older page holding still is what makes it readable.
    refetchInterval: page === 0 ? 10_000 : false,
    placeholderData: keepPreviousData,
  });
  const refresh = () => {
    client.invalidateQueries({ queryKey: ["logs"] });
    client.invalidateQueries({ queryKey: ["logging-health"] });
  };
  const scopeName = project ? `project ${project}` : "all projects";
  const remove = useMutation({
    mutationFn: async (target: "logs" | "content") => {
      const path = target === "logs" ? "/logs" : "/logs/content";
      return send<{ deleted: number }>(path, {
        method: "DELETE",
        body: { confirmation: "DELETE", project_id: project || null },
      });
    },
    onSuccess: (data, target) => {
      toast.success(`${count(data.deleted, target === "logs" ? "record" : "content record")} deleted`);
      refresh();
    },
    onError: toast.failure,
  });
  const download = useMutation({
    mutationFn: async () => {
      const response = await call(`/logs/export${query({ ...filters, include_content: includeContent })}`);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "gateway-events.json";
      link.click();
      URL.revokeObjectURL(url);
    },
    onError: toast.failure,
  });
  return (
    <>
      <PageHeader
        title="Logs"
        description="Every request through the gateway, newest first."
        actions={<LiveDot paused={page > 0 || logs.isError} />}
      />
      <Recording />
      <form
        className="filters"
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          setSubmitted(search.trim());
        }}
      >
        <ScopeFilters />
        <select aria-label="Outcome" value={status} onChange={(event) => setStatus(event.target.value)}>
          <option value="">All outcomes</option>
          <option value="success">Successful</option>
          <option value="error">Failed or cancelled</option>
        </select>
        <input
          aria-label="Request ID"
          placeholder="Request ID"
          maxLength={128}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <Button type="submit" icon={<Search size={14} aria-hidden />}>
          Search
        </Button>
        {(submitted || status) && (
          <Button
            variant="ghost"
            onClick={() => {
              setSearch("");
              setSubmitted("");
              setStatus("");
            }}
          >
            Clear
          </Button>
        )}
      </form>
      <Card>
        {logs.isError && <ErrorNotice error={logs.error} retry={() => logs.refetch()} />}
        {logs.isPending && <Skeleton lines={8} />}
        {logs.data && (
          <LogTable
            items={logs.data.items}
            onOpen={setOpen}
            empty={<Empty title="No matching requests">Try a wider filter, or send a request from the Playground.</Empty>}
          />
        )}
        <div className="row between" style={{ marginTop: 12 }}>
          <span className="muted">
            Page {page + 1}
            {logs.data ? ` · ${count(logs.data.items.length, "record")}` : ""}
          </span>
          <div className="row">
            <Button small disabled={page === 0} icon={<ChevronLeft size={14} aria-hidden />} onClick={() => setCursors((items) => items.slice(0, -1))}>
              Newer
            </Button>
            <Button
              small
              disabled={!logs.data?.next_cursor}
              icon={<ChevronRight size={14} aria-hidden />}
              onClick={() => logs.data?.next_cursor && setCursors((items) => [...items, logs.data.next_cursor])}
            >
              Older
            </Button>
          </div>
        </div>
      </Card>
      <Card title="Export and delete" description="Exports use the filters above, up to 1,000 newest records. Deleting ignores the application and search filters.">
        <div className="row between">
          <div className="row">
            <Button icon={<Download size={14} aria-hidden />} disabled={download.isPending} onClick={() => download.mutate()}>
              Export JSON
            </Button>
            <label className="check">
              <input type="checkbox" checked={includeContent} onChange={(event) => setIncludeContent(event.target.checked)} />
              Include captured input and output
            </label>
          </div>
          <div className="row">
            <Button
              variant="danger"
              icon={<Trash2 size={14} aria-hidden />}
              disabled={remove.isPending}
              onClick={async () => {
                if (
                  await confirm({
                    title: "Delete captured content?",
                    danger: true,
                    action: "Delete content",
                    body: `This deletes captured input and output for ${scopeName}. Request metadata and usage remain. Separate JSONL files and in-flight requests are unaffected.`,
                  })
                )
                  remove.mutate("content");
              }}
            >
              Delete captured content
            </Button>
            <Button
              variant="danger"
              icon={<Trash2 size={14} aria-hidden />}
              disabled={remove.isPending}
              onClick={async () => {
                if (
                  await confirm({
                    title: `Delete logs for ${scopeName}?`,
                    danger: true,
                    action: "Delete logs",
                    body: "Usage totals are preserved. Separate JSONL files and in-flight requests are unaffected.",
                  })
                )
                  remove.mutate("logs");
              }}
            >
              {project ? "Delete selected project logs" : "Delete all logs"}
            </Button>
          </div>
        </div>
      </Card>
      {open && <LogDetail requestId={open} onClose={() => setOpen(null)} />}
    </>
  );
}
