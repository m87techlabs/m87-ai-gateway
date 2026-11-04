import { useQuery } from "@tanstack/react-query";
import { getJson } from "../api";
import { dateTime, latency, number, time } from "../format";
import type { LogEvent } from "../types";
import { Badge, Dialog, ErrorNotice, Notice, Skeleton, Table, type Column, type Tone } from "./ui";

export const statusTone = (event: LogEvent): Tone => {
  if (event.request_outcome === "cancelled") return "warning";
  return event.status_code >= 400 ? "critical" : "good";
};

const outcome = (event: LogEvent) => {
  if (event.request_outcome === "cancelled") return "Cancelled";
  return String(event.status_code);
};

export const logColumns: Column<LogEvent>[] = [
  { header: "Time", render: (item) => time(item.created_at), className: "nowrap" },
  { header: "Status", render: (item) => <Badge tone={statusTone(item)}>{outcome(item)}</Badge> },
  { header: "Application", render: (item) => item.app_id ?? "Unauthenticated", className: "nowrap" },
  {
    header: "Model",
    render: (item) => item.routed_model ?? item.model ?? "—",
    className: "break",
  },
  {
    header: "Type",
    render: (item) => (item.endpoint === "embeddings" ? "Embedding" : item.streaming ? "Stream" : "Chat"),
  },
  { header: "In", render: (item) => number(item.prompt_tokens), numeric: true },
  { header: "Out", render: (item) => number(item.completion_tokens), numeric: true },
  { header: "Latency", render: (item) => latency(item.latency_ms), numeric: true, className: "nowrap" },
];

const EXPLANATIONS: Record<string, string> = {
  disabled: "Capture was off for this request. Turn it on in Features for new requests.",
  expired: "Captured content expired under its retention policy. Request metadata and usage remain.",
  deleted: "Captured content was deleted by an operator. Request metadata and usage remain.",
  not_captured: "The request was rejected before content capture. Check its status and error above.",
  not_produced: "No output was captured. Inference may have failed or stopped before producing output.",
  unknown: "This older record has no capture-policy evidence. Missing content cannot be recovered.",
};

const yes = (value: unknown) => (value ? "Yes" : "No");

function readable(value: unknown): string {
  if (typeof value === "string") return value;
  if (!Array.isArray(value)) return JSON.stringify(value, null, 2);
  return value
    .map((item) => {
      const entry = item?.message ?? item;
      const content = entry?.content;
      const text =
        typeof content === "string"
          ? content
          : Array.isArray(content)
            ? JSON.stringify(content, null, 2)
            : typeof item === "string"
              ? item
              : (entry?.refusal ?? JSON.stringify(item, null, 2));
      return typeof item === "string" ? text : `${entry?.role ?? "assistant"}:\n${text}`;
    })
    .join("\n\n");
}

function Content({ label, value, status, event }: { label: string; value: unknown; status?: string; event: LogEvent }) {
  const flags = [
    status === "truncated" || status === "partial_truncated" ? "Truncated" : null,
    status === "partial" || status === "partial_truncated" ? "Partial" : null,
  ].filter(Boolean);
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="row">
        <h2>{label}</h2>
        {flags.map((flag) => (
          <Badge key={flag} tone="warning">
            {flag}
          </Badge>
        ))}
      </div>
      {value === null || value === undefined ? (
        <p className="muted">
          {EXPLANATIONS[status ?? ""] ?? "Content was not recorded for this request."}
          {event.request_outcome === "cancelled" && label === "Output" ? " The client disconnected." : ""}
        </p>
      ) : (
        <>
          <pre>{readable(value)}</pre>
          <details>
            <summary className="muted">Captured JSON</summary>
            <pre>{JSON.stringify(value, null, 2)}</pre>
          </details>
        </>
      )}
    </div>
  );
}

export function LogDetail({ requestId, onClose }: { requestId: string; onClose: () => void }) {
  const detail = useQuery({
    queryKey: ["log", requestId],
    queryFn: () => getJson<LogEvent>(`/logs/${encodeURIComponent(requestId)}`),
  });
  const item = detail.data;
  return (
    <Dialog side title="Request details" description={<code className="wrap-anywhere">{requestId}</code>} onClose={onClose}>
      {detail.isPending && <Skeleton lines={8} />}
      {detail.isError && <ErrorNotice error={detail.error} retry={() => detail.refetch()} />}
      {item && (
        <div className="stack-lg">
          <dl className="detail-grid">
            {(
              [
                ["Time", dateTime(item.created_at)],
                ["Status", item.status_code],
                ["HTTP status sent", item.http_status_code],
                ["Outcome", item.request_outcome],
                ["Application", item.app_id ?? "Unauthenticated"],
                ["Key", item.key_id?.slice(0, 8)],
                ["Project", item.project_id],
                ["Type", item.endpoint === "embeddings" ? "Embedding" : item.streaming ? "Stream" : "Chat"],
                ["Requested model", item.model],
                ["Routed model", item.routed_model],
                ["Provider status", item.upstream_status],
                ["Error", item.error_type],
                ["Latency", latency(item.latency_ms)],
                ["Attempts", item.provider_attempts],
                ["Input tokens", number(item.prompt_tokens)],
                ["Output tokens", number(item.completion_tokens)],
                ["Cache", item.cache_status],
                ["Partial output", yes(item.response_content_partial)],
                ["Queue", item.queue_outcome],
                ["Queue wait", item.queue_wait_ms === null || item.queue_wait_ms === undefined ? null : latency(item.queue_wait_ms)],
                ["Policy", item.guardrail_reason ?? item.guardrail_action],
                ["Client user hash", item.client_user_hash],
              ] as [string, unknown][]
            )
              .filter(([, value]) => value !== null && value !== undefined && value !== "")
              .map(([label, value]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>{String(value)}</dd>
                </div>
              ))}
          </dl>
          {item.content_hidden ? (
            <Notice>Input and output were captured for this request. Reading them needs the admin role.</Notice>
          ) : (
            <>
          <Content label="Input" value={item.request_content} status={item.request_content_status} event={item} />
          <Content label="Output" value={item.response_content} status={item.response_content_status} event={item} />
            </>
          )}
        </div>
      )}
    </Dialog>
  );
}

export const LogTable = ({
  items,
  onOpen,
  empty,
}: {
  items: LogEvent[];
  onOpen: (id: string) => void;
  empty?: React.ReactNode;
}) => (
  <Table columns={logColumns} rows={items} rowKey={(item) => item.request_id} onRow={(item) => onOpen(item.request_id)} empty={empty} />
);
