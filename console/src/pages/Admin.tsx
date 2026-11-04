import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { getJson, message, query, send } from "../api";
import { ScopeFilters } from "../components/filters";
import { Button, Card, Dialog, ErrorNotice, Field, Notice, PageHeader, Skeleton, Table, useToast } from "../components/ui";
import { useFilters } from "../filters";
import { dateTime } from "../format";
import { useReadOnly } from "../session";
import type { AuditEvent, Revision, RevisionDetail } from "../types";

function Restore({ revision, expected, onClose }: { revision: Revision; expected: number; onClose: () => void }) {
  const client = useQueryClient();
  const toast = useToast();
  const [confirmation, setConfirmation] = useState("");
  const [clear, setClear] = useState(false);
  const detail = useQuery({
    queryKey: ["revision", revision.revision_id],
    queryFn: () => getJson<RevisionDetail>(`/configuration/revisions/${revision.revision_id}`),
  });
  const restore = useMutation({
    mutationFn: () =>
      send(`/configuration/revisions/${revision.revision_id}/restore`, {
        method: "POST",
        body: { expected_revision: expected, confirmation: "RESTORE", clear_changed_credentials: clear },
      }),
    onSuccess: () => {
      toast.success("Settings restored and the response cache cleared");
      client.invalidateQueries();
      onClose();
    },
  });
  const data = detail.data;
  const changed = data ? [...data.changed_provider_bindings, ...(data.changed_export_binding ? ["log export (turned off after restore)"] : [])] : [];
  return (
    <Dialog wide title={`Restore revision ${revision.revision_id}`} description={data?.scope} onClose={onClose}>
      {detail.isError && <ErrorNotice error={detail.error} retry={() => detail.refetch()} />}
      {detail.isPending && <Skeleton lines={8} />}
      {data && (
        <form
          className="stack"
          onSubmit={(event) => {
            event.preventDefault();
            restore.mutate();
          }}
        >
          <pre style={{ maxHeight: 320 }}>{JSON.stringify(data.settings, null, 2)}</pre>
          {changed.length ? (
            <Notice tone="warning" title="Credentials will be removed">
              For: {changed.join(", ")}. Reconfigure them after restoring.
            </Notice>
          ) : (
            <Notice tone="info">Current credentials are kept. Old keys are never restored.</Notice>
          )}
          {changed.length > 0 && (
            <label className="check">
              <input type="checkbox" checked={clear} onChange={(event) => setClear(event.target.checked)} />
              Remove credentials for the changed connections
            </label>
          )}
          <Field label="Type RESTORE to activate these settings">
            <input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} autoComplete="off" required />
          </Field>
          {restore.isError && <Notice tone="critical">{message(restore.error)}</Notice>}
          <div className="row end">
            <Button onClick={onClose}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={restore.isPending || confirmation !== "RESTORE"}>
              Restore settings
            </Button>
          </div>
        </form>
      )}
    </Dialog>
  );
}

export function History() {
  const readOnly = useReadOnly();
  const [reviewing, setReviewing] = useState<Revision | null>(null);
  const revisions = useQuery({
    queryKey: ["revisions"],
    queryFn: () => getJson<{ items: Revision[]; current_revision: number | null }>("/configuration/revisions"),
  });
  const current = revisions.data?.current_revision ?? 0;
  return (
    <>
      <PageHeader title="Configuration history" description="Every saved settings change, for all projects. Restoring creates a new revision. Keys and application data are not included." />
      <Card>
        {revisions.isError && <ErrorNotice error={revisions.error} retry={() => revisions.refetch()} />}
        {revisions.isPending && <Skeleton lines={6} />}
        {revisions.data && (
          <Table
            rows={revisions.data.items}
            rowKey={(item) => String(item.revision_id)}
            columns={[
              { header: "Revision", render: (item) => `${item.revision_id}${item.revision_id === current ? " (current)" : ""}`, className: "nowrap" },
              { header: "Time", render: (item) => dateTime(item.created_at), className: "nowrap" },
              { header: "Change", render: (item) => <span className="mono">{item.action}</span> },
              { header: "Restored from", render: (item) => item.restored_from ?? "—" },
              {
                header: "",
                render: (item) => (
                  <Button small disabled={item.revision_id === current || readOnly} onClick={() => setReviewing(item)}>
                    Review and restore
                  </Button>
                ),
              },
            ]}
          />
        )}
      </Card>
      {reviewing && <Restore revision={reviewing} expected={current} onClose={() => setReviewing(null)} />}
    </>
  );
}

export function Audit() {
  const { project } = useFilters();
  const events = useQuery({
    queryKey: ["audit", project],
    queryFn: async () => (await getJson<{ items: AuditEvent[] }>(`/management-events${query({ limit: 250, project_id: project })}`)).items,
    refetchInterval: 30_000,
  });
  return (
    <>
      <PageHeader title="Audit log" description="Project, application, configuration, connection and key changes. Who made each change and who signed in. Credential values are never recorded." />
      <div className="filters">
        <ScopeFilters />
      </div>
      <Card>
        {events.isError && <ErrorNotice error={events.error} retry={() => events.refetch()} />}
        {events.isPending && <Skeleton lines={6} />}
        {events.data && (
          <Table
            rows={events.data}
            rowKey={(item) => `${item.created_at}-${item.action}-${item.key_id ?? ""}-${item.revision_id ?? ""}`}
            columns={[
              { header: "Time", render: (item) => dateTime(item.created_at), className: "nowrap" },
              { header: "Who", render: (item) => item.actor },
              { header: "Action", render: (item) => <span className="mono">{item.action}</span> },
              { header: "Project", render: (item) => item.project_id ?? "—" },
              { header: "Application", render: (item) => item.app_id ?? "—" },
              { header: "Key", render: (item) => (item.key_id ? <span className="mono">{item.key_id.slice(0, 8)}</span> : "—") },
              { header: "Provider", render: (item) => [item.provider, item.alias].filter(Boolean).join(" / ") || "—" },
              { header: "Revision", render: (item) => item.revision_id ?? "—" },
            ]}
          />
        )}
      </Card>
    </>
  );
}
