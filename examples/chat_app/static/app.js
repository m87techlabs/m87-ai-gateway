"use strict";
const $ = (id) => document.getElementById(id);
let history = [];
let busy = false;
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
  for (const id of ["input-tokens", "output-tokens", "total-tokens", "latency", "response-model", "request-id"]) $(id).textContent = "—";
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
  $("send").disabled = $("clear").disabled = $("prompt").disabled = true;
  $("send").textContent = "Waiting for model…";
  resetDetails();
  const pending = bubble("user", content);
  try {
    const response = await fetch("/api/chat", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({messages})});
    const result = await response.json();
    $("request-id").textContent = result.request_id || "Unavailable";
    if (!response.ok) throw new Error(result.error || "Request failed. Check the gateway logs.");
    history = [...messages, {role: "assistant", content: result.content}];
    bubble("assistant", result.content);
    $("prompt").value = "";
    $("response-model").textContent = result.model;
    $("input-tokens").textContent = result.usage.prompt_tokens ?? "Unknown";
    $("output-tokens").textContent = result.usage.completion_tokens ?? "Unknown";
    $("total-tokens").textContent = result.usage.total_tokens ?? "Unknown";
    $("latency").textContent = `${result.latency_ms} ms`;
  } catch (error) {
    pending.remove();
    $("error").textContent = error.message || "Cannot reach the sample application.";
    $("error").hidden = false;
  } finally {
    busy = false;
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
