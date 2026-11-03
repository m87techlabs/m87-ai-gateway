import { useState } from "react";
import { CopyButton } from "./ui";

const snippets = (base: string, key: string, model: string) => ({
  Python: `from openai import OpenAI

client = OpenAI(
    base_url="${base}",
    api_key="${key}",
)
reply = client.chat.completions.create(
    model="${model}",
    messages=[{"role": "user", "content": "Hello"}],
)
print(reply.choices[0].message.content)`,
  JavaScript: `import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "${base}",
  apiKey: "${key}",
});
const reply = await client.chat.completions.create({
  model: "${model}",
  messages: [{ role: "user", content: "Hello" }],
});
console.log(reply.choices[0].message.content);`,
  curl: `curl ${base}/chat/completions \\
  -H "Authorization: Bearer ${key}" \\
  -H "Content-Type: application/json" \\
  -d '{"model":"${model}","messages":[{"role":"user","content":"Hello"}]}'`,
  Environment: `OPENAI_BASE_URL=${base}
OPENAI_API_KEY=${key}`,
});

/** Copy-paste setup for an app. Only the base URL and key change from a normal OpenAI client. */
export function ConnectSnippets({ apiKey, model }: { apiKey?: string; model: string }) {
  const [tab, setTab] = useState<keyof ReturnType<typeof snippets>>("Python");
  const base = `${window.location.origin}/v1`;
  const all = snippets(base, apiKey ?? "<application key>", model);
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="row between">
        <div className="tabs" role="tablist" aria-label="Language">
          {(Object.keys(all) as (keyof typeof all)[]).map((name) => (
            <button key={name} type="button" role="tab" aria-selected={tab === name} onClick={() => setTab(name)}>
              {name}
            </button>
          ))}
        </div>
        <CopyButton value={all[tab]} />
      </div>
      <pre>{all[tab]}</pre>
    </div>
  );
}
