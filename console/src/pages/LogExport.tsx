import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ApiError, getJson, getVersioned, message, send } from "../api";
import { Badge, Button, Card, ErrorNotice, Field, Notice, PageHeader, Skeleton, Table, useToast } from "../components/ui";
import { number } from "../format";
import type { Destination, ExportConfig, ExportSettings } from "../types";

type Auth = "none" | "stored" | "environment";
const NUMBERS: [keyof ExportConfig, string, number, number, number][] = [
  ["max_pending", "Maximum pending records", 1, 100000, 1],
  ["retention_hours", "Queue retention (hours)", 1, 2160, 1],
  ["timeout_seconds", "Request timeout (seconds)", 0.1, 30, 0.1],
  ["poll_seconds", "Poll interval (seconds)", 0.1, 60, 0.1],
  ["retry_seconds", "First retry delay (seconds)", 0.1, 300, 0.1],
  ["max_retry_seconds", "Longest retry delay (seconds)", 0.1, 3600, 0.1],
];

function ExportForm({ settings, etag }: { settings: ExportSettings; etag: string | null }) {
  const client = useQueryClient();
  const toast = useToast();
  const [config, setConfig] = useState(settings.config);
  const [auth, setAuth] = useState<Auth>(settings.config.use_stored_key ? "stored" : settings.config.api_key_env ? "environment" : "none");
  const [token, setToken] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [testStatus, setTestStatus] = useState<{ tone: "info" | "good" | "critical"; text: string } | null>(null);
  const [saveError, setSaveError] = useState("");
  const [busy, setBusy] = useState(false);
  const probe = useRef<AbortController | null>(null);
  useEffect(() => () => probe.current?.abort(), []);

  const edited = () => {
    if (probe.current) {
      probe.current.abort();
      probe.current = null;
    }
    setTestStatus({ tone: "info", text: "Draft changed. Test again before saving." });
  };
  const change = (values: Partial<ExportConfig>) => {
    setConfig({ ...config, ...values });
    edited();
  };
  const payload = () => ({
    config: {
      enabled: config.enabled,
      adapter: config.adapter,
      endpoint: config.endpoint?.trim() || null,
      use_stored_key: auth === "stored",
      api_key_env: auth === "environment" ? config.api_key_env?.trim() || null : null,
      ...Object.fromEntries(NUMBERS.map(([name]) => [name, Number(config[name])])),
    },
    clear_key: clearKey,
    ...(token ? { key: token } : {}),
  });
  const save = async () => {
    probe.current?.abort();
    setBusy(true);
    setSaveError("");
    try {
      await send("/log-export", { method: "PUT", etag, body: payload() });
      setToken("");
      setClearKey(false);
      toast.success("Export settings saved and applied. Pending records keep their original destination.");
      client.invalidateQueries({ queryKey: ["log-export"] });
    } catch (error) {
      setToken("");
      setSaveError(error instanceof ApiError && error.status === 409 ? `${message(error)} Refresh before retrying, and re-enter a new token if you need one.` : message(error));
    } finally {
      setBusy(false);
    }
  };
  const test = async () => {
    probe.current?.abort();
    const controller = new AbortController();
    probe.current = controller;
    setTestStatus({ tone: "info", text: "Sending one synthetic event. Nothing is saved." });
    try {
      const result = await send<{ ok?: boolean; message: string }>("/log-export/test", { method: "POST", body: payload(), signal: controller.signal });
      if (probe.current === controller) setTestStatus({ tone: result.ok === false ? "critical" : "good", text: result.message });
    } catch (error) {
      if (probe.current === controller) setTestStatus({ tone: "critical", text: message(error) });
    } finally {
      if (probe.current === controller) probe.current = null;
    }
  };
  const credential = settings.has_stored_key
    ? "A credential is saved for this destination. Leave blank to keep it."
    : settings.has_any_stored_key
      ? "A credential is saved for another destination. Changing destination needs a new token or explicit removal."
      : "No credential is saved for this destination.";
  return (
    <Card title="Destination" description="Sends request metadata only. Input and output stay in local Logs.">
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <label className="check">
          <input type="checkbox" checked={config.enabled} onChange={(event) => change({ enabled: event.target.checked })} />
          Export request metadata
        </label>
        <div className="grid-2">
          <Field label="Format">
            <select value={config.adapter} onChange={(event) => change({ adapter: event.target.value })}>
              {settings.adapters.map((name) => (
                <option key={name} value={name}>
                  {name === "loki" ? "Loki" : name === "webhook" ? "Webhook" : name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Authentication">
            <select
              value={auth}
              onChange={(event) => {
                setAuth(event.target.value as Auth);
                setToken("");
                edited();
              }}
            >
              <option value="none">None</option>
              <option value="stored">Token stored in the gateway</option>
              <option value="environment">Environment variable</option>
            </select>
          </Field>
        </div>
        <Field label="Receiver URL" help={config.adapter === "loki" ? "Use the full /loki/api/v1/push URL. Works with single-tenant Loki or a bearer-authenticated proxy." : undefined}>
          <input type="url" maxLength={2048} placeholder="https://collector.example.com/events" value={config.endpoint ?? ""} onChange={(event) => change({ endpoint: event.target.value })} />
        </Field>
        {auth === "stored" && (
          <Field label="New bearer token" help={credential}>
            <input
              type="password"
              maxLength={4096}
              autoComplete="new-password"
              value={token}
              onChange={(event) => {
                setToken(event.target.value);
                edited();
              }}
            />
          </Field>
        )}
        {auth === "environment" && (
          <Field label="Token environment variable">
            <input autoComplete="off" placeholder="GATEWAY_EXPORT_TOKEN" value={config.api_key_env ?? ""} onChange={(event) => change({ api_key_env: event.target.value })} />
          </Field>
        )}
        <label className="check">
          <input
            type="checkbox"
            checked={clearKey}
            onChange={(event) => {
              setClearKey(event.target.checked);
              edited();
            }}
          />
          Remove the previously saved credential when saving
        </label>
        <details>
          <summary className="muted">Delivery settings</summary>
          <div className="grid-3" style={{ marginTop: 12 }}>
            {NUMBERS.map(([name, label, minimum, maximum, step]) => (
              <Field key={name} label={label}>
                <input type="number" min={minimum} max={maximum} step={step} required value={String(config[name])} onChange={(event) => change({ [name]: event.target.value } as Partial<ExportConfig>)} />
              </Field>
            ))}
          </div>
        </details>
        {testStatus && <Notice tone={testStatus.tone}>{testStatus.text}</Notice>}
        {saveError && <Notice tone="critical">{saveError}</Notice>}
        <div className="row">
          <Button type="submit" variant="primary" disabled={busy}>
            {busy ? "Saving…" : "Save and apply"}
          </Button>
          <Button onClick={test} disabled={busy}>
            Send test event
          </Button>
        </div>
      </form>
    </Card>
  );
}

export function LogExport() {
  const settings = useQuery({
    queryKey: ["log-export"],
    queryFn: () => getVersioned<ExportSettings>("/log-export"),
    refetchOnWindowFocus: false,
  });
  const destinations = useQuery({
    queryKey: ["destinations"],
    queryFn: async () => (await getJson<{ items: Destination[] }>("/destinations")).items,
  });
  const data = settings.data?.data;
  const health = data?.health;
  return (
    <>
      <PageHeader title="Log export" description="Send request metadata to your own log system. Settings apply to all projects." />
      {settings.isError && <ErrorNotice error={settings.error} retry={() => settings.refetch()} />}
      {settings.isPending && <Skeleton lines={8} />}
      {data && health && (
        <>
          <Card title="Delivery" actions={<Badge tone={!health.enabled ? "neutral" : health.delivery_state === "healthy" ? "good" : "warning"}>{health.enabled ? health.delivery_state : "Off"}</Badge>}>
            <p className="muted">
              {number(health.pending)} pending · {number(health.delivered ?? 0)} delivered · {number(health.failed_attempts ?? 0)} failed attempts · {number(health.dropped ?? 0)} dropped · {number(health.expired ?? 0)} expired
            </p>
          </Card>
          <ExportForm key={settings.data?.etag ?? "export"} settings={data} etag={settings.data?.etag ?? null} />
        </>
      )}
      <Card title="Where data goes">
        {destinations.isError && <ErrorNotice error={destinations.error} retry={() => destinations.refetch()} />}
        {destinations.data && (
          <Table
            rows={destinations.data}
            rowKey={(item) => item.name}
            columns={[
              { header: "Destination", render: (item) => item.name, className: "nowrap" },
              { header: "Data", render: (item) => item.type },
              { header: "Target", render: (item) => <span className="wrap-anywhere">{item.target ?? "—"}</span> },
              { header: "Status", render: (item) => <Badge tone={item.enabled ? "good" : "neutral"}>{item.enabled ? "On" : "Off"}</Badge> },
            ]}
          />
        )}
      </Card>
    </>
  );
}
