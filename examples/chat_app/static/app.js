"use strict";
const $ = (id) => document.getElementById(id);
let history = [];
let busy = false;
let controller = null;
$("stop").addEventListener("click", () => controller?.abort());
window.addEventListener("pagehide", () => controller?.abort());

async function readStream(response, onText) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "", text = "", model = "", usage = {}, done = false;
  try {
    while (!done) {
      const block = await reader.read();
      buffer += decoder.decode(block.value || new Uint8Array(), {stream: !block.done});
      buffer = buffer.replaceAll("\r\n", "\n");
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
        if (frame.length > 65536) throw new Error("Gateway stream event is too large");
        const data = frame.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
        if (!data) continue;
        if (data === "[DONE]") { done = true; break; }
        const value = JSON.parse(data);
        if (value.error) throw new Error(value.error.message || "Gateway stream failed");
        model = value.model || model;
        if (value.usage) usage = value.usage;
        for (const choice of value.choices || []) {
          text += choice.delta?.content || choice.delta?.refusal || "";
          if (text.length > 8192) throw new Error("Response is too long for this sample conversation");
          onText(text);
        }
      }
      if (buffer.length > 65536) throw new Error("Gateway stream event is too large");
      if (block.done && !done) throw new Error("Gateway stream ended before completion");
    }
    if (!text.trim()) throw new Error("Model returned no text");
    return {content: text, model, usage, request_id: response.headers.get("x-request-id"), cache_status: "BYPASS"};
  } finally {
    try { await reader.cancel(); } finally { reader.releaseLock(); }
  }
}

function bubble(role, content) {
  $("empty")?.remove();
  const article = document.createElement("article");
  article.className = role;
  const title = document.createElement("strong");
  title.textContent = role === "user" ? "You" : "Assistant";
  const text = document.createElement("p");
  text.textContent = content;
  article.append(title, text);
  $("messages").append(article);
  article.scrollIntoView?.({block: "nearest"});
  return article;
}
function resetDetails() {
  for (const id of ["input-tokens", "output-tokens", "total-tokens", "latency", "response-model", "request-id", "cache-status", "retry-after"]) $(id).textContent = "—";
  $("error").hidden = true;
}
$("clear").addEventListener("click", () => {
  if (busy) return;
  history = [];
  $("messages").replaceChildren();
  resetDetails();
  $("prompt").value = "";
  $("prompt").focus();
});
$("chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const content = $("prompt").value.trim();
  if (busy || !content) return;
  const messages = [...history, {role: "user", content}];
  if (messages.length > 31 || messages.reduce((sum, item) => sum + item.content.length, 0) > 32768) {
    $("error").textContent = "This conversation is full. Start a new conversation.";
    $("error").hidden = false;
    return;
  }
  busy = true;
  controller = new AbortController();
  const started = performance.now();
  const streaming = $("streaming").checked;
  $("streaming").disabled = true;
  $("stop").hidden = false;
  $("send").disabled = $("clear").disabled = $("prompt").disabled = true;
  $("send").textContent = "Waiting for model…";
  resetDetails();
  const pending = bubble("user", content);
  let assistant = null;
  try {
    const response = await fetch(streaming ? "/api/chat/stream" : "/api/chat", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({messages}), signal: controller.signal});
    $("request-id").textContent = response.headers.get("x-request-id") || "Unavailable";
    const result = streaming && response.ok ? await readStream(response, (text) => {
      assistant ||= bubble("assistant", ""); assistant.querySelector("p").textContent = text;
    }) : await response.json();
    if (streaming) result.latency_ms = Math.round(performance.now() - started);
    $("request-id").textContent = result.request_id || "Unavailable";
    $("cache-status").textContent = result.cache_status || "—";
    $("retry-after").textContent = result.retry_after == null ? "—" : `${result.retry_after} seconds`;
    if (!response.ok) throw new Error(result.error || "Request failed. Check the gateway logs.");
    history = [...messages, {role: "assistant", content: result.content}];
    if (!assistant) bubble("assistant", result.content);
    $("prompt").value = "";
    $("response-model").textContent = result.model;
    $("input-tokens").textContent = result.usage.prompt_tokens ?? "Unknown";
    $("output-tokens").textContent = result.usage.completion_tokens ?? "Unknown";
    $("total-tokens").textContent = result.usage.total_tokens ?? "Unknown";
    $("latency").textContent = `${result.latency_ms} ms`;
  } catch (error) {
    if (assistant) assistant.querySelector("strong").textContent = "Assistant · Partial response";
    else pending.remove();
    $("error").textContent = error.name === "AbortError" ? "Request stopped. Partial output is excluded from conversation history." : error.message || "Cannot reach the sample application.";
    $("error").hidden = false;
  } finally {
    busy = false;
    controller = null;
    $("stop").hidden = true;
    $("streaming").disabled = false;
    $("send").disabled = $("clear").disabled = $("prompt").disabled = false;
    $("send").textContent = "Send message";
    $("prompt").focus();
  }
});
fetch("/api/status").then((response) => response.json()).then((result) => {
  $("status").textContent = result.gateway_reachable ? "Gateway reachable · Ready to chat" : "Gateway unavailable · Start the gateway and check its URL";
  $("model").textContent = `Model: ${result.model}`;
  $("gateway").textContent = `Gateway: ${result.gateway_url || "Unknown"}`;
}).catch(() => { $("status").textContent = "Could not check gateway status"; });
