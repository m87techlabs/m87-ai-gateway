import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { useEffect, useState } from "react";
import { ApiError, getVersioned, send, type Versioned } from "../api";
import { Badge, Button, Card, ErrorNotice, Field, PageHeader, Skeleton, Switch, useToast } from "../components/ui";
import { href } from "../router";
import type { Feature, FeatureField } from "../types";

type Features = Versioned<{ items: Feature[] }>;
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
            {planned && <Badge>Planned</Badge>}
            {!planned && !feature.toggleable && <Badge>Always on</Badge>}
          </div>
          <p className="muted">{feature.summary}</p>
        </div>
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

const GROUPS = ["Traffic", "Safety", "Routing", "Observability"];

export function Features() {
  const features = useQuery({
    queryKey: ["features"],
    queryFn: () => getVersioned<Features["data"]>("/features"),
    refetchOnWindowFocus: false,
  });
  const items = features.data?.data.items;
  return (
    <>
      <PageHeader
        title="Features"
        description={
          <>
            Turn gateway features on and off. Changes apply to new requests straight away, survive restarts, and can be undone from{" "}
            <a href={href("history")}>Configuration history</a>.
          </>
        }
      />
      {features.isError && <ErrorNotice error={features.error} retry={() => features.refetch()} />}
      {features.isPending && <Skeleton lines={10} />}
      {items &&
        GROUPS.map((group) => (
          <Card key={group} className="feature-group">
            <h2>{group}</h2>
            {items
              .filter((item) => item.group === group)
              .map((item) => (
                <FeatureRow key={item.id} feature={item} etag={features.data?.etag ?? null} />
              ))}
            {group === "Observability" && (
              <div className="feature">
                <div className="feature-head">
                  <div>
                    <div className="feature-title">Log export</div>
                    <p className="muted">Send request metadata to a webhook or Loki.</p>
                  </div>
                  <a href={href("export")}>Configure</a>
                </div>
              </div>
            )}
          </Card>
        ))}
    </>
  );
}
