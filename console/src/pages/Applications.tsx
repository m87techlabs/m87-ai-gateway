import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { getJson, message, send } from "../api";
import { useProjects } from "../components/filters";
import { ModelPicker, useSetup } from "../components/models";
import { ConnectSnippets } from "../components/snippets";
import { Badge, Button, Card, Dialog, Empty, ErrorNotice, Field, Notice, PageHeader, Secret, Skeleton, Table } from "../components/ui";
import { go, href } from "../router";
import type { Application } from "../types";

export const useApps = () =>
  useQuery({
    queryKey: ["apps"],
    queryFn: async () => (await getJson<{ items: Application[] }>("/apps")).items,
  });

function CreateApp({ onClose }: { onClose: () => void }) {
  const client = useQueryClient();
  const projects = useProjects();
  const setup = useSetup();
  const [appId, setAppId] = useState("");
  const [project, setProject] = useState("default");
  const [models, setModels] = useState<string[] | null>(null);
  const [rate, setRate] = useState("");
  const [concurrent, setConcurrent] = useState("");
  const chosen = models ?? (setup.data ? ["auto", setup.data.default_model] : []);
  const create = useMutation({
    mutationFn: () =>
      send<Application & { api_key: string }>("/apps", {
        method: "POST",
        body: {
          app_id: appId,
          project_id: project,
          allowed_models: chosen,
          ...(rate ? { rate_limit_per_minute: Number(rate) } : {}),
          ...(concurrent ? { max_concurrent_requests: Number(concurrent) } : {}),
        },
      }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["apps"] });
      client.invalidateQueries({ queryKey: ["app-names"] });
      client.invalidateQueries({ queryKey: ["projects"] });
    },
  });
  if (create.data) {
    const model = chosen.find((item) => item !== "auto") ?? "auto";
    return (
      <Dialog wide title={`${appId} is ready`} description="Point your app at the gateway with this key." onClose={onClose}>
        <div className="stack">
          <Secret value={create.data.api_key} />
          <ConnectSnippets apiKey={create.data.api_key} model={model.includes(":") && model.split(":")[0] === setup.data?.default_model.split(":")[0] ? model.slice(model.indexOf(":") + 1) : model} />
          <div className="row end">
            <Button variant="primary" onClick={onClose}>
              Done
            </Button>
          </div>
        </div>
      </Dialog>
    );
  }
  return (
    <Dialog title="Create application" description="Each app gets its own key, so its traffic is easy to find." onClose={onClose}>
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <Field label="Name" help="Letters, numbers, dots, dashes and underscores.">
          <input value={appId} onChange={(event) => setAppId(event.target.value)} required maxLength={100} pattern="[A-Za-z0-9_.\-]+" autoFocus />
        </Field>
        <Field label="Project">
          <select value={project} onChange={(event) => setProject(event.target.value)}>
            {projects.data?.map((item) => (
              <option key={item.project_id} value={item.project_id}>
                {item.name}
              </option>
            ))}
          </select>
        </Field>
        <div className="field">
          <span className="field-label">Allowed models</span>
          <ModelPicker value={chosen} onChange={setModels} />
        </div>
        <div className="grid-2">
          <Field label="Requests per minute">
            <input type="number" min={1} max={100000} placeholder="Unlimited" value={rate} onChange={(event) => setRate(event.target.value)} />
          </Field>
          <Field label="Concurrent requests">
            <input type="number" min={1} max={10000} placeholder="Gateway limit" value={concurrent} onChange={(event) => setConcurrent(event.target.value)} />
          </Field>
        </div>
        {create.isError && <Notice tone="critical">{message(create.error)}</Notice>}
        <div className="row end">
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" disabled={create.isPending || !appId || !chosen.length}>
            {create.isPending ? "Creating…" : "Create application"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

export function Applications() {
  const apps = useApps();
  const projects = useProjects();
  const [creating, setCreating] = useState(false);
  const projectName = (id: string) => projects.data?.find((item) => item.project_id === id)?.name ?? id;
  return (
    <>
      <PageHeader
        title="Applications"
        description="One application per calling app. Its key decides which models it can use, and everything it does is reported under its name."
        actions={
          <Button variant="primary" icon={<Plus size={15} aria-hidden />} onClick={() => setCreating(true)}>
            Create application
          </Button>
        }
      />
      <Card>
        {apps.isError && <ErrorNotice error={apps.error} retry={() => apps.refetch()} />}
        {apps.isPending && <Skeleton lines={4} />}
        {apps.data && (
          <Table
            rows={apps.data}
            rowKey={(item) => item.app_id}
            onRow={(item) => go("applications", item.app_id)}
            empty={
              <Empty title="No applications yet">
                Create one to get a key for your app.
              </Empty>
            }
            columns={[
              { header: "Application", render: (item) => <a href={href("applications", item.app_id)} onClick={(event) => event.stopPropagation()}>{item.app_id}</a> },
              { header: "Project", render: (item) => projectName(item.project_id) },
              { header: "Models", render: (item) => `${item.allowed_models.length} allowed` },
              {
                header: "Keys",
                render: (item) =>
                  item.active_key_count ? (
                    <span className="mono">{item.key_prefix}…</span>
                  ) : (
                    <Badge tone="warning">No active key</Badge>
                  ),
              },
              {
                header: "Limits",
                render: (item) =>
                  [
                    item.rate_limit_per_minute ? `${item.rate_limit_per_minute}/min` : null,
                    item.max_concurrent_requests ? `${item.max_concurrent_requests} at once` : null,
                  ]
                    .filter(Boolean)
                    .join(" · ") || "Gateway defaults",
              },
            ]}
          />
        )}
      </Card>
      {creating && <CreateApp onClose={() => setCreating(false)} />}
    </>
  );
}
