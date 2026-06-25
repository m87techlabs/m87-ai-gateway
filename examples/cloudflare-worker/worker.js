export default {
  async fetch(request, env) {
    const response = await fetch(`${env.M87_GATEWAY_URL}/v1/chat/completions`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${env.M87_GATEWAY_API_KEY}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        model: "auto",
        messages: [{ role: "user", content: "Hello from Cloudflare Worker" }]
      })
    });

    return new Response(await response.text(), {
      headers: { "Content-Type": "application/json" }
    });
  }
};
