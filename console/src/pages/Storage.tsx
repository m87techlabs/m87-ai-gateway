import { useMutation, useQuery } from "@tanstack/react-query";
import { getJson, send } from "../api";
import { Badge, Button, Card, ErrorNotice, Notice, PageHeader, Skeleton, Stat, Table, useToast } from "../components/ui";
import { bytes } from "../format";
import type { Diagnostics, StorageReport } from "../types";

export function Storage() {
  const toast = useToast();
  const report = useQuery({ queryKey: ["storage"], queryFn: () => getJson<StorageReport>("/storage") });
  const diagnostics = useQuery({ queryKey: ["diagnostics"], queryFn: () => getJson<Diagnostics>("/diagnostics") });
  const verify = useMutation({
    mutationFn: () => send<StorageReport>("/storage/check", { method: "POST" }),
    onError: toast.failure,
  });
  const data = verify.data ?? report.data;
  return (
    <>
      <PageHeader
        title="Storage"
        description="The gateway's local database and readiness."
        actions={
          <Button disabled={verify.isPending} onClick={() => verify.mutate()}>
            {verify.isPending ? "Verifying…" : "Verify integrity and write access"}
          </Button>
        }
      />
      {report.isError && <ErrorNotice error={report.error} retry={() => report.refetch()} />}
      {report.isPending && <Skeleton lines={6} />}
      {data && (
        <>
          <div className="row">
            <Badge tone={data.ok ? "good" : "critical"}>{data.ok ? "Healthy" : "Needs attention"}</Badge>
            <small className="muted">
              {data.backend} · schema {data.schema_version ?? "unknown"} · {data.verified ? "integrity and write access verified" : "basic checks"}
            </small>
          </div>
          {!!data.warnings?.length && <Notice tone="warning">{data.warnings.join(" ")}</Notice>}
          <div className="grid-3">
            <Stat label="Database" value={bytes(data.database_bytes)} />
            <Stat label="Write-ahead log" value={bytes(data.wal_bytes)} />
            <Stat label="Free disk" value={bytes(data.free_disk_bytes)} />
          </div>
          <Card title="Storage checks">
            <Table
              rows={data.checks}
              rowKey={(item) => item.name}
              columns={[
                { header: "Check", render: (item) => item.name },
                { header: "Status", render: (item) => <Badge tone={item.ok ? "good" : "critical"}>{item.ok ? "OK" : "Needs attention"}</Badge> },
                { header: "Action", render: (item) => (item.ok ? "—" : item.message) },
              ]}
            />
          </Card>
        </>
      )}
      {diagnostics.data && (
        <Card
          title="Readiness"
          description={`Checks configuration and storage, not whether a provider is reachable. ${diagnostics.data.active_requests} active requests, ${diagnostics.data.queued_requests ?? 0} queued.`}
          actions={<Badge tone={diagnostics.data.ready ? "good" : "warning"}>{diagnostics.data.ready ? "Ready" : "Needs configuration"}</Badge>}
        >
          <Table
            rows={diagnostics.data.checks}
            rowKey={(item) => item.name}
            columns={[
              { header: "Check", render: (item) => item.name },
              { header: "Status", render: (item) => <Badge tone={item.ok ? "good" : "warning"}>{item.ok ? "OK" : "Needs attention"}</Badge> },
              { header: "Action", render: (item) => (item.ok ? "—" : item.message) },
            ]}
          />
        </Card>
      )}
    </>
  );
}
