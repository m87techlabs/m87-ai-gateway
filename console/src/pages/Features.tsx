import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Coins, Gauge, KeyRound, Plus, RefreshCw, ScrollText, ShieldCheck, Waypoints, X, Zap } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { ApiError, getJson, getVersioned, send } from "../api";
import { Badge, Button, Card, Empty, ErrorNotice, Field, PageHeader, Skeleton, Switch, useToast } from "../components/ui";
import { count, number, percent } from "../format";
import { href } from "../router";
import type { Capability, Feature, FeatureField, Summary } from "../types";

type Route = { task: string; model: string };

const toDraft = (field: FeatureField, value: unknown): unknown => {
  if (field.kind === "terms") return ((value as string[]) ?? []).join("\n");
  if (field.kind === "routes") return value ?? [];
  return String(value ?? "");
};

const fromDraft = (field: FeatureField, value: unknown): unknown => {
  if (field.kind === "terms") {
    return String(value)
      .split("\n")
      .map((item) => item.trim())
      .filter(Boolean);
  }
  if (field.kind === "routes") return value;
  return Number(value);
};

function Routes({ value, onChange }: { value: Route[]; onChange: (routes: Route[]) => void }) {
  const update = (index: number, change: Partial<Route>) => onChange(value.map((item, position) => (position === index ? { ...item, ...change } : item)));
  return (
    <div className="stack" style={{ gap: 8 }}>
      {value.map((route, index) => (
        <div className="route-row" key={index}>
          <input aria-label={`Task ${index + 1}`} placeholder="Task, such as code" value={route.task} onChange={(event) => update(index, { task: event.target.value })} />
          <input aria-label={`Model ${index + 1}`} placeholder="provider:model" value={route.model} onChange={(event) => update(index, { model: event.target.value })} />
          <Button small variant="ghost" aria-label={`Remove route ${index + 1}`} icon={<X size={14} aria-hidden />} onClick={() => onChange(value.filter((_, position) => position !== index))} />
        </div>
      ))}
      <div>
        <Button small icon={<Plus size={14} aria-hidden />} onClick={() => onChange([...value, { task: "", model: "" }])}>
          Add route
        </Button>
      </div>
    </div>
  );
}

function FeatureRow({ feature, etag }: { feature: Feature; etag: string | null }) {
  const client = useQueryClient();
  const toast = useToast();
  const initial = () => Object.fromEntries(feature.fields.map((field) => [field.name, toDraft(field, feature.values[field.name])]));
  const [draft, setDraft] = useState<Record<string, unknown>>(initial);
  const serverValues = JSON.stringify(feature.values);
  useEffect(() => setDraft(initial()), [serverValues]); // eslint-disable-line react-hooks/exhaustive-deps
  const dirty = feature.fields.some((field) => JSON.stringify(draft[field.name]) !== JSON.stringify(toDraft(field, feature.values[field.name])));
  const save = useMutation({
    mutationFn: (body: { enabled?: boolean; values?: Record<string, unknown> }) =>
      send<Feature>(`/features/${encodeURIComponent(feature.id)}`, { method: "PUT", etag, body }),
    onSuccess: (_, body) => {
      toast.success(body.enabled === undefined ? `${feature.name} saved` : `${feature.name} turned ${body.enabled ? "on" : "off"}`);
      client.invalidateQueries({ queryKey: ["features"] });
      client.invalidateQueries({ queryKey: ["setup"] });
      client.invalidateQueries({ queryKey: ["setup-versioned"] });
      client.invalidateQueries({ queryKey: ["logging-health"] });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        toast.failure(new Error("Settings changed elsewhere. The latest values are loaded; try again."));
        client.invalidateQueries({ queryKey: ["features"] });
      } else toast.failure(error);
    },
  });
  const planned = feature.status === "planned";
  const clearCache = useMutation({
    mutationFn: () => send("/cache/clear", { method: "POST" }),
    onSuccess: () => toast.success("Response cache cleared"),
    onError: toast.failure,
  });
  return (
    <div className="feature" data-feature={feature.id}>
      <div className="feature-head">
        <div>
          <div className="feature-title">
            {feature.name}
            {!planned && !feature.toggleable && !feature.link && <Badge>{feature.badge ?? "Always on"}</Badge>}
          </div>
          <p className="muted">{feature.summary}</p>
        </div>
        {feature.link && <a href={href(feature.link)}>Open</a>}
        {feature.toggleable && (
          <Switch checked={feature.enabled} disabled={save.isPending} label={feature.name} onChange={(enabled) => save.mutate({ enabled })} />
        )}
      </div>
      {feature.note && <small className="muted">{feature.note}</small>}
      {feature.fields.length > 0 && (!feature.toggleable || feature.enabled) && (
        <form
          className="stack"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate({ values: Object.fromEntries(feature.fields.map((field) => [field.name, fromDraft(field, draft[field.name])])) });
          }}
        >
          <div className="feature-fields" style={feature.fields.some((field) => field.kind !== "number") ? { gridTemplateColumns: "minmax(0, 1fr)" } : undefined}>
            {feature.fields.map((field) => (
              <Field key={field.name} label={field.unit ? `${field.label} (${field.unit})` : field.label} help={field.help}>
                {field.kind === "terms" ? (
                  <textarea rows={4} value={String(draft[field.name])} onChange={(event) => setDraft({ ...draft, [field.name]: event.target.value })} />
                ) : field.kind === "routes" ? (
                  <Routes value={draft[field.name] as Route[]} onChange={(routes) => setDraft({ ...draft, [field.name]: routes })} />
                ) : (
                  <input
                    type="number"
                    min={field.minimum ?? undefined}
                    max={field.maximum ?? undefined}
                    step={field.step ?? undefined}
                    required
                    value={String(draft[field.name])}
                    onChange={(event) => setDraft({ ...draft, [field.name]: event.target.value })}
                  />
                )}
              </Field>
            ))}
          </div>
          {dirty && (
            <div className="row">
              <Button type="submit" small variant="primary" disabled={save.isPending}>
                Save
              </Button>
              <Button small onClick={() => setDraft(initial())}>
                Discard
              </Button>
            </div>
          )}
        </form>
      )}
      {feature.id === "response_cache" && feature.enabled && (
        <div>
          <Button small disabled={clearCache.isPending} onClick={() => clearCache.mutate()}>
            Clear cache
          </Button>
        </div>
      )}
    </div>
  );
}

const ICONS: Record<string, ReactNode> = {
  authentication: <KeyRound size={18} aria-hidden />,
  routing: <Waypoints size={18} aria-hidden />,
  caching: <Zap size={18} aria-hidden />,
  rate_limits: <Gauge size={18} aria-hidden />,
  reliability: <RefreshCw size={18} aria-hidden />,
  guardrails: <ShieldCheck size={18} aria-hidden />,
  logging: <ScrollText size={18} aria-hidden />,
  monitoring: <Activity size={18} aria-hidden />,
  cost: <Coins size={18} aria-hidden />,
};

const useFeatures = () =>
  useQuery({
    queryKey: ["features"],
    queryFn: () => getVersioned<{ capabilities: Capability[]; items: Feature[] }>("/features"),
    refetchOnWindowFocus: false,
  });

/** A real number from the last 24 hours, only where a capability has one worth showing. */
function liveFact(capability: Capability, active: boolean, summary?: Summary) {
  if (!summary) return null;
  switch (capability.id) {
    case "caching":
      return active && summary.requests > 0 ? `${percent(summary.cache_hits, summary.requests)} of requests served from cache in the last 24 hours` : null;
    case "logging":
      return `${count(summary.requests, "request")} logged in the last 24 hours`;
    case "cost":
      return `${number(summary.total_tokens)} tokens used in the last 24 hours`;
    default:
      return null;
  }
}

function CapabilityCard({ capability, items, summary }: { capability: Capability; items: Feature[]; summary?: Summary }) {
  const available = items.filter((item) => item.status !== "planned");
  const on = available.filter((item) => item.enabled).length;
  const planned = items.length - available.length;
  const fact = liveFact(capability, on > 0, summary);
  return (
    <a className="card capability" href={href("features", capability.id)} data-capability={capability.id}>
      <div className="capability-head">
        <span className="capability-icon">{ICONS[capability.id]}</span>
        <h2>{capability.name}</h2>
        {available.length === 0 ? <Badge>Planned</Badge> : on > 0 ? <Badge tone="good">On</Badge> : <Badge>Off</Badge>}
      </div>
      <p className="muted">{capability.summary}</p>
      {fact && <p className="capability-fact">{fact}</p>}
      <small className="muted">
        {available.length > 0 && `${on} of ${available.length} on`}
        {available.length > 0 && planned > 0 && " · "}
        {planned > 0 && `${planned} planned`}
      </small>
    </a>
  );
}

export function Features() {
  const features = useFeatures();
  const summary = useQuery({
    queryKey: ["overview", "features"],
    queryFn: () => getJson<Summary>("/overview?hours=24"),
    refetchInterval: 30_000,
  });
  const data = features.data?.data;
  return (
    <>
      <PageHeader
        title="Features"
        description="The jobs this gateway does between your apps and your models. Open one to see what it does and change its settings."
      />
      {features.isError && <ErrorNotice error={features.error} retry={() => features.refetch()} />}
      {features.isPending && <Skeleton lines={10} />}
      {data && (
        <div className="capabilities">
          {data.capabilities.map((capability) => (
            <CapabilityCard
              key={capability.id}
              capability={capability}
              items={data.items.filter((item) => item.group === capability.id)}
              summary={summary.data}
            />
          ))}
        </div>
      )}
    </>
  );
}

export function CapabilityPage({ id }: { id: string }) {
  const features = useFeatures();
  const data = features.data?.data;
  const capability = data?.capabilities.find((item) => item.id === id);
  const items = data?.items.filter((item) => item.group === id) ?? [];
  const available = items.filter((item) => item.status !== "planned");
  const planned = items.filter((item) => item.status === "planned");
  return (
    <>
      {features.isError && <ErrorNotice error={features.error} retry={() => features.refetch()} />}
      {features.isPending && <Skeleton lines={10} />}
      {data && !capability && <Empty title="That feature does not exist" />}
      {capability && (
        <>
          <PageHeader
            eyebrow={<a href={href("features")}>Features</a>}
            title={capability.name}
            description={
              <>
                {capability.summary} Changes apply to new requests straight away, survive restarts, and can be undone from{" "}
                <a href={href("history")}>Configuration history</a>.
              </>
            }
          />
          {available.length > 0 && (
            <Card className="feature-group">
              {available.map((item) => (
                <FeatureRow key={item.id} feature={item} etag={features.data?.etag ?? null} />
              ))}
            </Card>
          )}
          {planned.length > 0 && (
            <Card className="feature-group">
              <h2>Planned</h2>
              {planned.map((item) => (
                <FeatureRow key={item.id} feature={item} etag={null} />
              ))}
            </Card>
          )}
        </>
      )}
    </>
  );
}
