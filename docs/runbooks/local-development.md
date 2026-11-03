# Local development

For contributors changing the gateway. To only run it, use [Docker](container-deployment.md).

## Set up

You need Python 3.11+, and Node 22 for the console.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev,sdk-tests]'
npm ci --prefix console
npm run build --prefix console
```

Built console files go to `src/m87_gateway/control/static/`, which Git ignores. Without them, `/admin`
shows how to build them, and the API works normally.

## Run

```bash
scripts/dev-start.sh     # Starts in the background and prints the console URL and admin key
scripts/dev-status.sh
scripts/dev-stop.sh      # Stops gracefully and keeps data
```

The gateway tries port 8087, then 8187, 8287 and so on; `--port` selects an exact one. Data lives in
your user data folder, separately from any Docker volume, so the two have different keys and logs.
Restart after changing Python.

To work on the console with instant reload, keep the gateway on 8087 and run:

```bash
npm run dev --prefix console
```

Then open the URL it prints, under `/admin/`.

## Check

```bash
.venv/bin/ruff check src tests scripts examples
.venv/bin/ruff format --check src tests scripts examples
.venv/bin/pytest -q
npm test --prefix console
python scripts/check_docs.py
docker compose config --quiet
```

Tests use temporary stores and never touch a running gateway. To check the image itself:

```bash
docker build -t m87-ai-gateway:check .
python scripts/smoke_container.py m87-ai-gateway:check
```

A console change also needs a look in a real browser, because jsdom tests cannot catch layout or
content-security-policy problems.

## Sample app

[The chat sample](../../examples/chat_app/README.md) calls your gateway as an app would. Its isolated
scenario suite runs the HTTP flow and failure recovery with no running gateway:

```bash
.venv/bin/python -m examples.chat_app.scenarios
```

## Add a feature

Add switches and settings to the list in `src/m87_gateway/control/features.py`, and they appear in
**Features** automatically. Keep docs and tests with the change, and see
[contributing](../../CONTRIBUTING.md).

## Clean up

`scripts/dev-stop.sh` stops the gateway. Local data stays until you delete its folder.
