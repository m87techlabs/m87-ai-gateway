import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { getJson, message, send } from "../api";
import { Button, Field, Notice } from "../components/ui";

/** Fixed wording: the gateway sends a code, never text from the identity provider. */
const SIGN_IN_ERRORS: Record<string, string> = {
  no_role: "Your account has no role on this gateway. Ask an admin to give you the admin or read-only role.",
  expired: "That sign-in took too long or started in another browser. Try again.",
  unavailable: "The identity provider can't be reached. Try again, or use the admin key.",
  failed: "Single sign-on failed. Try again, or use the admin key.",
};

export function Login({ onSuccess }: { onSuccess: () => void }) {
  const [key, setKey] = useState("");
  const [error, setError] = useState(() => {
    const code = new URLSearchParams(window.location.search).get("sign_in_error");
    return code ? (SIGN_IN_ERRORS[code] ?? SIGN_IN_ERRORS.failed) : "";
  });
  const [busy, setBusy] = useState(false);
  const options = useQuery({
    queryKey: ["sign-in-options"],
    queryFn: () => getJson<{ sso: boolean }>("/sign-in-options"),
    staleTime: Infinity,
  });
  const sso = options.data?.sso ?? false;
  // A refresh should not repeat an old error.
  useEffect(() => {
    if (window.location.search.includes("sign_in_error")) {
      window.history.replaceState(null, "", window.location.pathname + window.location.hash);
    }
  }, []);
  const keyForm = (
    <>
      <Field label="Admin key">
        <input
          type="password"
          value={key}
          onChange={(event) => setKey(event.target.value)}
          autoComplete="off"
          required
          autoFocus={!sso}
        />
      </Field>
      <Button type="submit" variant={sso ? "secondary" : "primary"} disabled={busy || !key}>
        {busy ? "Signing in…" : "Sign in"}
      </Button>
      <details>
        <summary className="muted">Where do I find the key?</summary>
        <p className="muted" style={{ margin: "8px 0" }}>
          From your gateway checkout, run:
        </p>
        <pre>docker compose exec m87-ai-gateway cat /data/gateway/admin.key</pre>
      </details>
    </>
  );
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
          {!sso && <p className="muted">You stay signed in for 12 hours on this browser, or until you lock it.</p>}
        </div>
        {error && <Notice tone="critical">{error}</Notice>}
        {sso ? (
          <>
            <a className="button primary" href="/admin/auth/login">
              Sign in with SSO
            </a>
            <details className="stack">
              <summary className="muted">Use the admin key instead</summary>
              {keyForm}
            </details>
          </>
        ) : (
          keyForm
        )}
      </form>
    </div>
  );
}
