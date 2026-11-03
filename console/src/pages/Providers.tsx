import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Settings2 } from "lucide-react";
import { useRef, useState } from "react";
import { getVersioned, getJson, message, send } from "../api";
import { useDiscoveredModels } from "../components/models";
import { Badge, Button, Card, Dialog, ErrorNotice, Field, Notice, PageHeader, Skeleton, Table, useConfirm, useToast } from "../components/ui";
import { dateTime } from "../format";
import type { Connection, Setup } from "../types";

const useVersionedSetup = () => useQuery({ queryKey: ["setup-versioned"], queryFn: () => getVersioned<Setup>("/setup") });

function ConnectionDialog({ connection, etag, onClose }: { connection: Connection; etag: string | null; onClose: () => void }) {
  const client = useQueryClient();
  const toast = useToast();
  const [baseUrl, setBaseUrl] = useState(connection.config.base_url ?? "");
  const [timeoutSeconds, setTimeoutSeconds] = useState(String(connection.config.timeout_seconds));
  const [key, setKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  // Setting up a connection for the first time means you want to use it.
  const [enabled, setEnabled] = useState(connection.configured ? connection.config.enabled : true);
  const [test, setTest] = useState<{ tone: "good" | "critical" | "info"; text: string } | null>(null);
  const [saveError, setSaveError] = useState("");
  const [testing, setTesting] = useState(false);
  const generation = useRef(0);
  const provider = encodeURIComponent(connection.provider);
  const payload = () => ({
    config: { base_url: baseUrl, timeout_seconds: Number(timeoutSeconds), enabled },
    clear_key: clearKey,
    ...(key ? { key } : {}),
  });
  // Any edit makes an in-flight or finished test about a different endpoint.
  const edited = () => {
    generation.current += 1;
    setTesting(false);
    setTest(null);
  };
  const save = useMutation({
    mutationFn: () => send(`/connections/${provider}`, { method: "PUT", etag, body: payload() }),
    onSuccess: () => {
      toast.success(`${connection.label} saved`);
      setKey("");
      client.invalidateQueries({ queryKey: ["setup-versioned"] });
      client.invalidateQueries({ queryKey: ["setup"] });
      client.invalidateQueries({ queryKey: ["models"] });
      onClose();
    },
    onError: (error) => setSaveError(message(error)),
  });
  const runTest = async () => {
    const current = ++generation.current;
    setTesting(true);
    setTest({ tone: "info", text: "Checking from the gateway…" });
    try {
      const data = await send<{ ok: boolean; message: string; latency_ms: number }>(`/connections/${provider}/test`, {
        method: "POST",
        body: payload(),
      });
      if (current !== generation.current) return;
      setTest({ tone: data.ok ? "good" : "critical", text: `${data.ok ? "Connected" : "Connection failed"}: ${data.message} (${Math.round(data.latency_ms)} ms)` });
    } catch (error) {
      if (current === generation.current) setTest({ tone: "critical", text: `Connection failed: ${message(error)}` });
    } finally {
      if (current === generation.current) setTesting(false);
    }
  };
  const capabilities = connection.capability_matrix;
  return (
    <Dialog title={connection.label} description="Provider credentials stay in the gateway and are never returned." onClose={onClose}>
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          setSaveError("");
          save.mutate();
        }}
      >
        <label className="check">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => {
              setEnabled(event.target.checked);
              edited();
            }}
          />
          Enable this connection
        </label>
        <Field label="Endpoint URL" help="For a model server on this machine from Docker, use http://host.docker.internal:11434.">
          <input
            type="url"
            value={baseUrl}
            required
            placeholder="http://localhost:11434"
            onChange={(event) => {
              setBaseUrl(event.target.value);
              edited();
            }}
          />
        </Field>
        <Field label="Timeout (seconds)" help="Large local models can take minutes to load.">
          <input
            type="number"
            min={1}
            max={600}
            required
            value={timeoutSeconds}
            onChange={(event) => {
              setTimeoutSeconds(event.target.value);
              edited();
            }}
            style={{ maxWidth: 160 }}
          />
        </Field>
        <Field
          label={connection.requires_key ? "API key" : "API key (optional)"}
          help={connection.has_stored_key ? "A key is stored. Leave blank to keep it." : "Stored encrypted. Never shown again."}
        >
          <input
            type="password"
            autoComplete="off"
            value={key}
            onChange={(event) => {
              setKey(event.target.value);
              edited();
            }}
          />
        </Field>
        {connection.has_stored_key && (
          <label className="check">
            <input
              type="checkbox"
              checked={clearKey}
              onChange={(event) => {
                setClearKey(event.target.checked);
                edited();
              }}
            />
            Remove the stored key
          </label>
        )}
        {test && <Notice tone={test.tone}>{test.text}</Notice>}
        {saveError && <Notice tone="critical">{saveError}</Notice>}
        <div className="row between">
          <Button onClick={runTest} disabled={testing || !baseUrl || !connection.model_discovery}>
            {testing ? "Testing…" : "Test connection"}
          </Button>
          <div className="row">
            <Button onClick={onClose}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={save.isPending}>
              {save.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </div>
        <small className="muted">
          Testing lists models using what is typed above, without saving or sending a completion. Supports:{" "}
          {["streaming", "tools", "embeddings", "images"].filter((name) => capabilities[name]).join(", ") || "text chat"}.
        </small>
      </form>
    </Dialog>
  );
}

function DefaultModel({ setup, etag }: { setup: Setup; etag: string | null }) {
  const client = useQueryClient();
  const toast = useToast();
  const discovered = useDiscoveredModels();
  const [model, setModel] = useState(setup.default_model);
  const save = useMutation({
    mutationFn: () => send("/setup", { method: "PUT", etag, body: { default_model: model, capture_content: setup.capture_content } }),
    onSuccess: () => {
      toast.success("Default model saved");
      client.invalidateQueries({ queryKey: ["setup-versioned"] });
      client.invalidateQueries({ queryKey: ["setup"] });
    },
    onError: toast.failure,
  });
  return (
    <Card title="Default model" description="Used for model auto. Upstream names like qwen3:14b also resolve through this model's provider.">
      <form
        className="row"
        style={{ flexWrap: "nowrap" }}
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <input aria-label="Default model" list="default-models" value={model} onChange={(event) => setModel(event.target.value)} required placeholder="provider:model" />
        <datalist id="default-models">
          {discovered.map((name) => (
            <option key={name} value={name} />
          ))}
        </datalist>
        <Button type="submit" variant="primary" disabled={save.isPending || model === setup.default_model}>
          Save
        </Button>
      </form>
    </Card>
  );
}

interface StoredKey {
  provider: string;
  alias: string;
  updated_at: string;
}

function StoredKeys({ connections }: { connections: Connection[] }) {
  const client = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const [adding, setAdding] = useState(false);
  const [provider, setProvider] = useState(connections[0]?.provider ?? "openai");
  const [alias, setAlias] = useState("default");
  const [key, setKey] = useState("");
  const keys = useQuery({ queryKey: ["provider-keys"], queryFn: async () => (await getJson<{ items: StoredKey[] }>("/provider-keys")).items });
  const refresh = () => {
    client.invalidateQueries({ queryKey: ["provider-keys"] });
    client.invalidateQueries({ queryKey: ["setup-versioned"] });
  };
  const store = useMutation({
    mutationFn: () => send("/provider-keys", { method: "PUT", body: { provider, alias, key } }),
    onSuccess: () => {
      toast.success("Provider key stored");
      setKey("");
      setAdding(false);
      refresh();
    },
    onError: toast.failure,
  });
  const remove = useMutation({
    mutationFn: (item: StoredKey) => send(`/provider-keys/${encodeURIComponent(item.provider)}/${encodeURIComponent(item.alias)}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Provider key removed");
      refresh();
    },
    onError: toast.failure,
  });
  return (
    <Card
      title="Stored provider keys"
      description="Encrypted before they are stored, and never returned."
      actions={
        <Button small icon={<Plus size={14} aria-hidden />} onClick={() => setAdding(true)}>
          Add key
        </Button>
      }
    >
      {keys.isError && <ErrorNotice error={keys.error} retry={() => keys.refetch()} />}
      {keys.data && (
        <Table
          rows={keys.data}
          rowKey={(item) => `${item.provider}/${item.alias}`}
          empty={<p className="muted">No provider keys stored.</p>}
          columns={[
            { header: "Provider", render: (item) => item.provider },
            { header: "Alias", render: (item) => item.alias },
            { header: "Updated", render: (item) => dateTime(item.updated_at) },
            {
              header: "",
              render: (item) => (
                <Button
                  small
                  variant="danger"
                  onClick={async () => {
                    if (await confirm({ title: `Remove the ${item.provider} key?`, danger: true, action: "Remove key", body: `Requests to ${item.provider} will fail until a new key is added.` })) remove.mutate(item);
                  }}
                >
                  Remove
                </Button>
              ),
            },
          ]}
        />
      )}
      {adding && (
        <Dialog title="Add provider key" onClose={() => setAdding(false)}>
          <form
            className="stack"
            onSubmit={(event) => {
              event.preventDefault();
              store.mutate();
            }}
          >
            <Field label="Provider">
              <select value={provider} onChange={(event) => setProvider(event.target.value)}>
                {connections.map((item) => (
                  <option key={item.provider} value={item.provider}>
                    {item.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Alias">
              <input value={alias} onChange={(event) => setAlias(event.target.value)} required />
            </Field>
            <Field label="Secret key">
              <input type="password" autoComplete="off" value={key} onChange={(event) => setKey(event.target.value)} required />
            </Field>
            <div className="row end">
              <Button onClick={() => setAdding(false)}>Cancel</Button>
              <Button type="submit" variant="primary" disabled={store.isPending}>
                Store key
              </Button>
            </div>
          </form>
        </Dialog>
      )}
    </Card>
  );
}

export function Providers() {
  const setup = useVersionedSetup();
  const [editing, setEditing] = useState<string | null>(null);
  const data = setup.data?.data;
  const selected = data?.connections.find((item) => item.provider === editing);
  return (
    <>
      <PageHeader title="Providers" description="Where the gateway sends requests. Apps never see these credentials." />
      {setup.isError && <ErrorNotice error={setup.error} retry={() => setup.refetch()} />}
      {setup.isPending && <Skeleton lines={6} />}
      {data && (
        <>
          <div className="grid-3">
            {data.connections.map((item) => (
              <Card
                key={item.provider}
                title={item.label}
                actions={
                  <Badge tone={item.configured && item.config.enabled ? "good" : "neutral"}>
                    {item.configured && item.config.enabled ? "Connected" : "Not set up"}
                  </Badge>
                }
              >
                <div className="stack" style={{ gap: 10 }}>
                  <p className="muted wrap-anywhere">{item.config.base_url ?? "No endpoint set"}</p>
                  <div>
                    <Button small icon={<Settings2 size={14} aria-hidden />} aria-label={`Configure ${item.label}`} onClick={() => setEditing(item.provider)}>
                      Configure
                    </Button>
                  </div>
                </div>
              </Card>
            ))}
          </div>
          <DefaultModel key={data.default_model} setup={data} etag={setup.data?.etag ?? null} />
          <StoredKeys connections={data.connections} />
          {selected && <ConnectionDialog connection={selected} etag={setup.data?.etag ?? null} onClose={() => setEditing(null)} />}
        </>
      )}
    </>
  );
}
