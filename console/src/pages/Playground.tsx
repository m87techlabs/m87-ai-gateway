import { useEffect, useRef, useState } from "react";
import { useDiscoveredModels } from "../components/models";
import { Button, Card, Empty, Field, Notice, PageHeader } from "../components/ui";
import { latency } from "../format";
import { href } from "../router";

interface Result {
  status?: number;
  elapsed?: number;
  requestId?: string;
  text: string;
  usage?: string;
  raw?: string;
  note?: string;
  streaming?: boolean;
}

export function Playground() {
  const models = useDiscoveredModels();
  const [appKey, setAppKey] = useState("");
  const [model, setModel] = useState("auto");
  const [prompt, setPrompt] = useState("Say hello in one short sentence.");
  const [maxTokens, setMaxTokens] = useState("256");
  const [stream, setStream] = useState(true);
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  const run = async () => {
    const abort = new AbortController();
    controller.current = abort;
    const timeout = window.setTimeout(() => abort.abort(), 180_000);
    const started = performance.now();
    setBusy(true);
    setResult({ text: "", streaming: true });
    try {
      const response = await fetch("/v1/chat/completions", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${appKey}` },
        cache: "no-store",
        signal: abort.signal,
        body: JSON.stringify({
          model,
          stream,
          ...(stream ? { stream_options: { include_usage: true } } : {}),
          messages: [{ role: "user", content: prompt }],
          max_tokens: Number(maxTokens),
        }),
      });
      const requestId = response.headers.get("X-Request-ID") ?? undefined;
      const base = { status: response.status, requestId };
      if (!stream || !response.ok || !response.body) {
        const data = await response.json();
        setResult({
          ...base,
          elapsed: performance.now() - started,
          text: data.choices?.[0]?.message?.content ?? data.error?.message ?? "",
          usage: data.usage ? `${data.usage.prompt_tokens} in · ${data.usage.completion_tokens} out` : undefined,
          raw: JSON.stringify(data, null, 2),
        });
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let text = "";
      let usage: string | undefined;
      let failure: string | undefined;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() ?? "";
        for (const event of events) {
          const line = event.split("\n").find((item) => item.startsWith("data: "));
          if (!line || line === "data: [DONE]") continue;
          const data = JSON.parse(line.slice(6));
          if (data.error) failure = data.error.message;
          text += data.choices?.[0]?.delta?.content ?? "";
          if (data.usage) usage = `${data.usage.prompt_tokens} in · ${data.usage.completion_tokens} out`;
        }
        setResult({ ...base, text, usage, streaming: true, note: failure });
      }
      setResult({ ...base, text, usage, elapsed: performance.now() - started, note: failure });
    } catch (error) {
      const aborted = error instanceof Error && error.name === "AbortError";
      setResult((current) => ({
        ...(current ?? { text: "" }),
        streaming: false,
        elapsed: performance.now() - started,
        note: aborted ? "Stopped. The gateway has closed the request; check Logs for its outcome." : "The gateway could not be reached.",
      }));
    } finally {
      window.clearTimeout(timeout);
      setBusy(false);
      if (controller.current === abort) controller.current = null;
    }
  };

  return (
    <>
      <PageHeader
        title="Playground"
        description="Send a real request through the gateway, with the same limits and logging as your apps. Provider calls may use quota."
      />
      <div className="grid-2">
        <Card>
          <form
            className="stack"
            onSubmit={(event) => {
              event.preventDefault();
              void run();
            }}
          >
            <Field label="Application key" help="Decides the application and project. Held only while this page is open.">
              <input type="password" value={appKey} onChange={(event) => setAppKey(event.target.value)} autoComplete="off" required />
            </Field>
            <Field label="Model" help="auto, a provider:model name, or the upstream name of a default-provider model.">
              <input value={model} onChange={(event) => setModel(event.target.value)} list="playground-models" required />
            </Field>
            <datalist id="playground-models">
              {models.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
            <Field label="Prompt">
              <textarea rows={6} maxLength={65536} value={prompt} onChange={(event) => setPrompt(event.target.value)} required />
            </Field>
            <Field label="Maximum output tokens">
              <input type="number" min={1} max={8192} value={maxTokens} onChange={(event) => setMaxTokens(event.target.value)} required style={{ maxWidth: 160 }} />
            </Field>
            <label className="check">
              <input type="checkbox" checked={stream} onChange={(event) => setStream(event.target.checked)} />
              Stream the response
            </label>
            <div className="row">
              <Button type="submit" variant="primary" disabled={busy || !appKey}>
                {busy ? "Running…" : "Send"}
              </Button>
              {busy && <Button onClick={() => controller.current?.abort()}>Stop</Button>}
            </div>
          </form>
        </Card>
        <Card
          title="Response"
          actions={
            result?.requestId && !busy ? <a href={`${href("logs")}?request_id=${encodeURIComponent(result.requestId)}`}>Open in Logs</a> : undefined
          }
        >
          {!result ? (
            <Empty title="Nothing sent yet">The response and its request ID appear here.</Empty>
          ) : (
            <div className="stack">
              <div className="row muted">
                {result.status !== undefined && <span>HTTP {result.status}</span>}
                {result.elapsed !== undefined && <span>· {latency(result.elapsed)}</span>}
                {result.usage && <span>· {result.usage}</span>}
              </div>
              {result.note && <Notice tone="warning">{result.note}</Notice>}
              <pre aria-live="polite">{result.text || (busy ? "Waiting for the first token…" : "No text in the response.")}</pre>
              {result.raw && (
                <details>
                  <summary className="muted">Full response</summary>
                  <pre>{result.raw}</pre>
                </details>
              )}
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
