import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, KeyRound, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { ApiError, getJson, message, query, send } from "../api";
import { BarList, ColumnChart } from "../components/charts";
import { useProjects, WindowSelect } from "../components/filters";
import { LogDetail, LogTable } from "../components/logs";
import { ModelPicker, useSetup } from "../components/models";
import { ConnectSnippets } from "../components/snippets";
import { Badge, Button, Card, Empty, ErrorNotice, Field, Notice, PageHeader, Secret, Skeleton, Stat, Table, useConfirm, useToast } from "../components/ui";
import { ago, count, dateTime, latency, number, percent } from "../format";
import { go, href } from "../router";
import type { AppKey, Application, LogsPage, Summary, Usage } from "../types";
import { useApps } from "./Applications";

function Activity({ appId }: { appId: string }) {
  const [hours, setHours] = useState(24);
  const [open, setOpen] = useState<string | null>(null);
  const summary = useQuery({
    queryKey: ["overview", "", appId, hours],
    queryFn: () => getJson<Summary>(`/overview${query({ app_id: appId, hours })}`),
    refetchInterval: 10_000,
    placeholderData: keepPreviousData,
  });
  const usage = useQuery({
    queryKey: ["usage", "", appId, hours],
    queryFn: () => getJson<Usage>(`/usage${query({ app_id: appId, hours })}`),
    refetchInterval: 10_000,
    placeholderData: keepPreviousData,
  });
  const logs = useQuery({
    queryKey: ["logs", "recent", "", appId],
    queryFn: () => getJson<LogsPage>(`/logs${query({ app_id: appId, limit: 10 })}`),
    refetchInterval: 10_000,
  });
  const data = summary.data;
  return (
    <div className="stack-lg">
      <div className="filters">
        <WindowSelect hours={hours} onChange={setHours} />
      </div>
      {summary.isError && <ErrorNotice error={summary.error} retry={() => summary.refetch()} />}
      <div className="grid-4">
        <Stat label="Requests" value={data ? number(data.requests) : "—"} />
        <Stat label="Tokens" value={data ? number(data.total_tokens) : "—"} detail={data ? `${number(data.prompt_tokens)} in · ${number(data.completion_tokens)} out` : undefined} />
        <Stat label="Errors" value={data ? number(data.errors) : "—"} detail={data ? `${percent(data.errors, data.requests)} of requests` : undefined} />
        <Stat label="Average latency" value={data ? latency(data.average_latency_ms) : "—"} />
      </div>
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
      {usage.data && (
        <div className="grid-2">
          <Card title="Models">
            <BarList
              unit="tokens"
              empty="No model traffic in this period"
              items={usage.data.by_model.map((item) => ({
                key: item.model ?? "none",
                label: item.model ?? "Rejected before routing",
                value: item.total_tokens ?? 0,
                detail: `${count(item.requests, "request")} · ${count(item.errors, "error")}`,
              }))}
            />
          </Card>
          <Card title="Request types">
            <BarList
              unit="requests"
              empty="No requests in this period"
              items={(usage.data.by_endpoint ?? []).map((item) => ({
                key: item.endpoint ?? "chat",
                label: item.endpoint === "embeddings" ? "Embeddings" : "Chat",
                value: item.requests,
                detail: `${count(item.total_tokens ?? 0, "token")} · ${count(item.errors, "error")}`,
              }))}
            />
          </Card>
        </div>
      )}
      <Card title="Recent requests" actions={<ViewLogsLink appId={appId} />}>
        {logs.data ? (
          <LogTable items={logs.data.items} onOpen={setOpen} empty={<Empty title="No requests yet" />} />
        ) : (
          <Skeleton lines={4} />
        )}
      </Card>
      {open && <LogDetail requestId={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

const ViewLogsLink = ({ appId: _appId }: { appId: string }) => <a href={href("logs")}>View all logs</a>;

const keyState = (key: AppKey) =>
  key.revoked_at ? <Badge>Revoked</Badge> : key.active ? <Badge tone="good">Active</Badge> : <Badge tone="warning">Expired</Badge>;

function Keys({ appId }: { appId: string }) {
  const client = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const [days, setDays] = useState("");
  const [revokeOld, setRevokeOld] = useState(false);
  const path = `/apps/${encodeURIComponent(appId)}/keys`;
  const keys = useQuery({
    queryKey: ["keys", appId],
    queryFn: async () => (await getJson<{ items: AppKey[] }>(path)).items,
    refetchInterval: 15_000,
  });
  const refresh = () => {
    client.invalidateQueries({ queryKey: ["keys", appId] });
    client.invalidateQueries({ queryKey: ["apps"] });
  };
  const issue = useMutation({
    mutationFn: (body: { revoke_existing: boolean; expires_in_days?: number }) =>
      send<{ api_key: string }>(path, { method: "POST", body }),
    onSuccess: () => {
      setRevokeOld(false);
      setDays("");
      refresh();
    },
    onError: toast.failure,
  });
  const revoke = useMutation({
    mutationFn: (key: AppKey) => send(`${path}/${encodeURIComponent(key.key_id)}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Key revoked");
      refresh();
    },
    onError: toast.failure,
  });
  return (
    <div className="stack-lg">
      {issue.data && <Secret value={issue.data.api_key}>Update your app, check the old key's Last used has stopped changing, then revoke it.</Secret>}
      <Card title="Keys" description="All of an application's keys share its permissions and limits.">
        {keys.isError && <ErrorNotice error={keys.error} retry={() => keys.refetch()} />}
        {keys.isPending && <Skeleton />}
        {keys.data && (
          <Table
            rows={keys.data}
            rowKey={(item) => item.key_id}
            empty={<Empty title="No keys" />}
            columns={[
              { header: "Key", render: (item) => <span className="mono" title={item.key_id}>{item.key_prefix}…</span> },
              { header: "Status", render: keyState },
              { header: "Last used", render: (item) => <span title={dateTime(item.last_used_at)}>{item.last_used_at ? ago(item.last_used_at) : "No use recorded"}</span> },
              { header: "Created", render: (item) => dateTime(item.created_at), className: "nowrap" },
              { header: "Expires", render: (item) => (item.expires_at ? dateTime(item.expires_at) : "Never"), className: "nowrap" },
              {
                header: "",
                render: (item) =>
                  item.active && (
                    <Button
                      small
                      variant="danger"
                      disabled={revoke.isPending}
                      onClick={async () => {
                        if (
                          await confirm({
                            title: `Revoke key ${item.key_prefix}…?`,
                            danger: true,
                            action: "Revoke key",
                            body: `Callers using this key for ${appId} will be rejected. Last used: ${item.last_used_at ? ago(item.last_used_at) : "no use recorded"}.`,
                          })
                        )
                          revoke.mutate(item);
                      }}
                    >
                      Revoke
                    </Button>
                  ),
              },
            ]}
          />
        )}
      </Card>
      <Card title="Create another key" description="Both keys work during the overlap, so you can rotate without downtime.">
        <form
          className="stack"
          onSubmit={async (event) => {
            event.preventDefault();
            if (
              revokeOld &&
              !(await confirm({
                title: "Revoke existing keys now?",
                danger: true,
                action: "Create and revoke",
                body: `Callers using the current keys for ${appId} will be rejected immediately.`,
              }))
            )
              return;
            issue.mutate({ revoke_existing: revokeOld, ...(days ? { expires_in_days: Number(days) } : {}) });
          }}
        >
          <Field label="Expires after (days)">
            <input type="number" min={1} max={3650} placeholder="Never" value={days} onChange={(event) => setDays(event.target.value)} style={{ maxWidth: 200 }} />
          </Field>
          <label className="check">
            <input type="checkbox" checked={revokeOld} onChange={(event) => setRevokeOld(event.target.checked)} />
            Revoke existing keys immediately
          </label>
          <div>
            <Button type="submit" icon={<KeyRound size={14} aria-hidden />} disabled={issue.isPending}>
              {issue.isPending ? "Creating…" : "Create key"}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}

function Settings({ app }: { app: Application }) {
  const client = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const projects = useProjects();
  const setup = useSetup();
  const base = `/apps/${encodeURIComponent(app.app_id)}`;
  const [models, setModels] = useState(app.allowed_models);
  const [rate, setRate] = useState(app.rate_limit_per_minute?.toString() ?? "");
  const [concurrent, setConcurrent] = useState(app.max_concurrent_requests?.toString() ?? "");
  useEffect(() => setModels(app.allowed_models), [app.allowed_models]);
  const refresh = () => client.invalidateQueries({ queryKey: ["apps"] });
  const patch = useMutation({
    mutationFn: ({ path, body }: { path: string; body: unknown; done: string }) => send(`${base}/${path}`, { method: "PATCH", body }),
    onSuccess: (_, variables) => {
      toast.success(variables.done);
      refresh();
    },
    onError: toast.failure,
  });
  const remove = useMutation({
    mutationFn: () => send(base, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Application deleted and its keys revoked");
      refresh();
      client.invalidateQueries({ queryKey: ["app-names"] });
      go("applications");
    },
    onError: toast.failure,
  });
  const modelsChanged = JSON.stringify([...models].sort()) !== JSON.stringify([...app.allowed_models].sort());
  const sampleModel = app.allowed_models.find((item) => item !== "auto") ?? "auto";
  const defaultProvider = setup.data?.default_model.split(":")[0];
  return (
    <div className="stack-lg">
      <Card title="Connect your app" description="Use a key from the Keys tab. Only the base URL and key differ from a normal OpenAI client.">
        <ConnectSnippets model={sampleModel.startsWith(`${defaultProvider}:`) ? sampleModel.slice(sampleModel.indexOf(":") + 1) : sampleModel} />
      </Card>
      <Card title="Allowed models" description="Saving does not change the application's keys.">
        <div className="stack">
          <ModelPicker value={models} onChange={setModels} />
          <div>
            <Button
              variant="primary"
              disabled={!modelsChanged || !models.length || patch.isPending}
              onClick={() => patch.mutate({ path: "models", body: { allowed_models: models }, done: "Allowed models saved" })}
            >
              Save models
            </Button>
          </div>
        </div>
      </Card>
      <div className="grid-2">
        <Card title="Limits" description="Blank uses the gateway's limits. Active requests are not interrupted.">
          <form
            className="stack"
            onSubmit={(event) => {
              event.preventDefault();
              patch.mutate({
                path: "limits",
                body: {
                  rate_limit_per_minute: rate ? Number(rate) : null,
                  max_concurrent_requests: concurrent ? Number(concurrent) : null,
                },
                done: "Limits saved",
              });
            }}
          >
            <Field label="Requests per minute">
              <input type="number" min={1} max={100000} placeholder="Unlimited" value={rate} onChange={(event) => setRate(event.target.value)} />
            </Field>
            <Field label="Concurrent requests">
              <input type="number" min={1} max={10000} placeholder="Gateway limit" value={concurrent} onChange={(event) => setConcurrent(event.target.value)} />
            </Field>
            <div>
              <Button type="submit" disabled={patch.isPending}>
                Save limits
              </Button>
            </div>
          </form>
        </Card>
        <Card title="Project" description="Affects future requests. Past usage stays with its original project.">
          <Field label="Project">
            <select
              value={app.project_id}
              onChange={(event) =>
                patch.mutate({ path: "project", body: { project_id: event.target.value }, done: "Project changed for future requests" })
              }
            >
              {projects.data?.map((item) => (
                <option key={item.project_id} value={item.project_id}>
                  {item.name}
                </option>
              ))}
            </select>
          </Field>
        </Card>
      </div>
      <Card title="Delete application" description="Revokes all of its keys. Logs and usage remain.">
        <Button
          variant="danger"
          icon={<Trash2 size={14} aria-hidden />}
          disabled={remove.isPending}
          onClick={async () => {
            if (
              await confirm({
                title: `Delete ${app.app_id}?`,
                danger: true,
                action: "Delete application",
                body: "This revokes all of its keys, so callers using them will be rejected. Logs and usage remain.",
              })
            )
              remove.mutate();
          }}
        >
          Delete application
        </Button>
      </Card>
    </div>
  );
}

export function ApplicationDetail({ appId }: { appId: string }) {
  const apps = useApps();
  const [tab, setTab] = useState<"activity" | "keys" | "settings">("activity");
  const app = apps.data?.find((item) => item.app_id === appId);
  const managed = Boolean(app);
  return (
    <>
      <PageHeader
        eyebrow={
          <a href={href("applications")} className="row" style={{ gap: 4 }}>
            <ArrowLeft size={14} aria-hidden /> Applications
          </a>
        }
        title={appId}
        description={app ? `${count(app.allowed_models.length, "allowed model")} · project ${app.project_id}` : undefined}
      />
      {apps.data && !managed && (
        <Notice tone="info">This application was deleted or comes from a YAML file, so it has no settings here. Its history remains.</Notice>
      )}
      {apps.isError && !(apps.error instanceof ApiError && apps.error.status === 404) && <Notice tone="critical">{message(apps.error)}</Notice>}
      {managed && (
        <div className="tabs" role="tablist">
          {(["activity", "keys", "settings"] as const).map((name) => (
            <button key={name} type="button" role="tab" aria-selected={tab === name} onClick={() => setTab(name)}>
              {name[0].toUpperCase() + name.slice(1)}
            </button>
          ))}
        </div>
      )}
      {tab === "activity" && <Activity appId={appId} />}
      {tab === "keys" && managed && <Keys appId={appId} />}
      {tab === "settings" && app && <Settings app={app} />}
    </>
  );
}
