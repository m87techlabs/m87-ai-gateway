const statusDot = document.querySelector("#status-dot");
const gatewayStatus = document.querySelector("#gateway-status");
const refreshStatus = document.querySelector("#refresh-status");
const form = document.querySelector("#chat-form");
const sendButton = document.querySelector("#send-button");
const flowState = document.querySelector("#flow-state");
const resultStatus = document.querySelector("#result-status");
const emptyResult = document.querySelector("#empty-result");
const resultContent = document.querySelector("#result-content");
const answer = document.querySelector("#answer");
const requestId = document.querySelector("#request-id");
const resolvedModel = document.querySelector("#resolved-model");
const latency = document.querySelector("#latency");
const usage = document.querySelector("#usage");
const stages = ["browser", "relay", "gateway", "model"];

function updateStage(name, state) {
  document.querySelector(`#stage-${name}`).dataset.state = state;
}

function resetStages() {
  stages.forEach((stage) => updateStage(stage, "idle"));
}

async function checkStatus() {
  statusDot.className = "status-dot pending";
  gatewayStatus.textContent = "Checking";
  refreshStatus.disabled = true;
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    const data = await response.json();
    const reachable = data.gateway === "reachable";
    statusDot.className = `status-dot ${reachable ? "ready" : "error"}`;
    gatewayStatus.textContent = reachable
      ? `Reachable · ${data.latency_ms} ms`
      : "Unavailable";
  } catch {
    statusDot.className = "status-dot error";
    gatewayStatus.textContent = "Relay unavailable";
  } finally {
    refreshStatus.disabled = false;
  }
}

function showResult(data, succeeded) {
  emptyResult.hidden = true;
  resultContent.hidden = false;
  resultStatus.className = `pill ${succeeded ? "success" : "failure"}`;
  resultStatus.textContent = succeeded ? "Completed" : "Stopped";
  answer.className = `answer ${succeeded ? "" : "error-copy"}`;
  answer.textContent = succeeded
    ? data.content
    : `${data.error?.message || "The request failed"} (${data.error?.code || "unknown_error"})`;
  requestId.textContent = data.request_id || "Not issued";
  resolvedModel.textContent = data.model || "Not resolved";
  latency.textContent = Number.isFinite(data.latency_ms) ? `${data.latency_ms} ms` : "—";
  if (data.usage && Number.isFinite(data.usage.total_tokens)) {
    usage.textContent = `${data.usage.total_tokens} total`;
  } else {
    usage.textContent = "Unavailable";
  }
}

async function runFlow(event) {
  event.preventDefault();
  sendButton.disabled = true;
  sendButton.querySelector("span").textContent = "Running";
  flowState.textContent = "In progress";
  flowState.className = "pill active";
  resultStatus.textContent = "Waiting";
  resultStatus.className = "pill muted";
  resetStages();
  updateStage("browser", "complete");
  updateStage("relay", "active");

  const payload = {
    prompt: document.querySelector("#prompt").value,
    system_prompt: document.querySelector("#system-prompt").value || null,
    model: document.querySelector("#model").value,
    temperature: Number(document.querySelector("#temperature").value),
    max_tokens: Number(document.querySelector("#max-tokens").value),
  };

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    updateStage("relay", "complete");
    updateStage("gateway", data.request_id ? "complete" : "error");
    updateStage("model", response.ok ? "complete" : "error");
    showResult(data, response.ok && data.ok === true);
    flowState.textContent = response.ok ? "Completed" : "Stopped";
    flowState.className = `pill ${response.ok ? "success" : "failure"}`;
  } catch {
    updateStage("relay", "error");
    updateStage("gateway", "idle");
    updateStage("model", "idle");
    showResult(
      {
        error: { message: "The local relay could not be reached", code: "relay_unavailable" },
        request_id: null,
      },
      false,
    );
    flowState.textContent = "Stopped";
    flowState.className = "pill failure";
  } finally {
    sendButton.disabled = false;
    sendButton.querySelector("span").textContent = "Run flow";
  }
}

refreshStatus.addEventListener("click", checkStatus);
form.addEventListener("submit", runFlow);
form.addEventListener("keydown", (event) => {
  if (event.ctrlKey && event.key === "Enter") {
    form.requestSubmit();
  }
});

resetStages();
checkStatus();
