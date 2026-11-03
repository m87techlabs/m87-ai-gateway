import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { send } from "../api";
import { useProjects } from "../components/filters";
import { Button, Card, ErrorNotice, Field, PageHeader, Skeleton, Table, useToast } from "../components/ui";
import { useFilters } from "../filters";
import { go } from "../router";

export function Projects() {
  const projects = useProjects();
  const client = useQueryClient();
  const toast = useToast();
  const { setProject, setApp } = useFilters();
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: () => send("/projects", { method: "POST", body: { project_id: id, name } }),
    onSuccess: () => {
      toast.success("Project created. Assign an application to it next.");
      setId("");
      setName("");
      client.invalidateQueries({ queryKey: ["projects"] });
    },
    onError: toast.failure,
  });
  return (
    <>
      <PageHeader title="Projects" description="Group applications to track their requests, tokens and logs together. Moving an application affects future requests only." />
      <div className="grid-2">
        <Card title="Projects">
          {projects.isError && <ErrorNotice error={projects.error} retry={() => projects.refetch()} />}
          {projects.isPending && <Skeleton />}
          {projects.data && (
            <Table
              rows={projects.data}
              rowKey={(item) => item.project_id}
              columns={[
                { header: "Name", render: (item) => item.name },
                { header: "ID", render: (item) => <span className="mono">{item.project_id}</span> },
                { header: "Applications", render: (item) => item.app_count, numeric: true },
                {
                  header: "",
                  render: (item) => (
                    <Button
                      small
                      onClick={() => {
                        setProject(item.project_id);
                        setApp("");
                        go("overview");
                      }}
                    >
                      View usage
                    </Button>
                  ),
                },
              ]}
            />
          )}
        </Card>
        <Card title="Create project">
          <form
            className="stack"
            onSubmit={(event) => {
              event.preventDefault();
              create.mutate();
            }}
          >
            <Field label="Project ID">
              <input value={id} onChange={(event) => setId(event.target.value)} required maxLength={100} pattern="[A-Za-z0-9_.\-]+" />
            </Field>
            <Field label="Name">
              <input value={name} onChange={(event) => setName(event.target.value)} required maxLength={100} />
            </Field>
            <div>
              <Button type="submit" variant="primary" disabled={create.isPending}>
                Create project
              </Button>
            </div>
          </form>
        </Card>
      </div>
    </>
  );
}
