# Guided setup

From a running gateway to your first request, in about five minutes. Start the gateway first, as
described in [run with Docker](container-deployment.md).

## Prerequisites

- A model server such as Ollama, or an account with a provider.
- The operator key, which you get with the command on the [Docker page](container-deployment.md#start).

## Steps

1. Open **http://localhost:8087** and sign in. You stay signed in for 12 hours on that browser.
2. In **Providers**, choose a connection and select **Configure**. Enter its endpoint, and a key if it
   needs one. Provider keys are encrypted and never returned.
3. Select **Test connection**. It lists models from inside the container, without saving anything or
   sending a completion. Then select **Save**.
4. Under **Default model**, choose the model that `auto` should use. Upstream names such as
   `qwen3:14b` also resolve through this model's provider.
5. In **Applications**, select **Create application**, name it and choose its allowed models. Copy the
   key, which is shown once, along with setup snippets for your app.
6. In **Playground**, paste the key and send a request. Select **Open in Logs** to see it.
7. Point your app at the gateway. See [connect your app](../connect-your-app.md).

## Check that it worked

- **Overview** shows your request, and updates by itself.
- **Logs** shows the request's model, tokens, status and latency.
- To read inputs and outputs in Logs, turn on **Input and output capture** in **Features**. It applies
  to every application and stores text unencrypted, so check your privacy needs first.

## Troubleshooting

| You see | Do this |
| --- | --- |
| **Test connection** fails | `localhost` means the container. Use `http://host.docker.internal:11434` for a model server on your machine, and see [reach your model server](container-deployment.md#reach-your-model-server) |
| The default model will not save | Enable the connection first |
| `403 model_not_allowed` | Add the model to the application's allowed models |
| `401 invalid_api_key` | Use the application key, not the operator key. Keys are shown once, so create a new one in the application's **Keys** tab |
| `502` with `HTTP 404` in the message | The provider does not have that model. See [provider troubleshooting](provider-troubleshooting.md) |
| A large local model times out | Raise the connection's timeout in **Providers** |

## Shut down

`docker compose stop` keeps your data. See [everyday commands](container-deployment.md#everyday-commands).
