import { useState } from "react";
import { message, send } from "../api";
import { Button, Field, Notice } from "../components/ui";

export function Login({ onSuccess }: { onSuccess: () => void }) {
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <div className="login">
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          setError("");
          try {
            await send("/session", { method: "POST", body: { key } });
            setKey("");
            onSuccess();
          } catch (failure) {
            setError(message(failure));
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="brand" style={{ padding: 0 }}>
          <span className="brand-mark" aria-hidden>
            M87
          </span>
          AI Gateway
        </div>
        <div>
          <h1>Sign in to the console</h1>
          <p className="muted">You stay signed in for 12 hours on this browser, or until you lock it.</p>
        </div>
        <Field label="Admin key">
          <input
            type="password"
            value={key}
            onChange={(event) => setKey(event.target.value)}
            autoComplete="off"
            required
            autoFocus
          />
        </Field>
        {error && <Notice tone="critical">{error}</Notice>}
        <Button type="submit" variant="primary" disabled={busy || !key}>
          {busy ? "Signing in…" : "Sign in"}
        </Button>
        <details>
          <summary className="muted">Where do I find the key?</summary>
          <p className="muted" style={{ margin: "8px 0" }}>
            From your gateway checkout, run:
          </p>
          <pre>docker compose exec m87-ai-gateway cat /data/gateway/admin.key</pre>
        </details>
      </form>
    </div>
  );
}
