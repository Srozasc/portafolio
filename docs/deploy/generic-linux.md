# Generic Linux Deploy (Ubuntu 22.04+ / Debian)

End-to-end guide for running the Portafolio RAG backend on a single Ubuntu
22.04+ (or Debian) VPS. The recommended exposure path is **Cloudflare
Tunnel** — see [`cloudflare-tunnel.md`](./cloudflare-tunnel.md). Nginx and
certbot are **not** required when you use a Tunnel, and this guide assumes
that path.

> **Audience**: solo freelancer with one VPS, no DevOps team.
> **Time**: ~20–30 min for a fresh host.

---

## 1. Prerequisites

Install the runtime basics:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip build-essential
```

- `git` — pull the repo.
- `python3-venv` — create the Python virtualenv.
- `build-essential` — needed by some wheels (cryptography, etc.).
- `nginx` — **NOT required** when you expose the backend via a Cloudflare
  Tunnel. Skip installing nginx entirely. Only consider it if you have a
  specific reason to terminate TLS on the VPS itself (the project doesn't).

If you plan to keep port 22 open and expose only the API through Cloudflare,
no further packages are needed on the VPS.

## 2. Clone the repository

```bash
sudo mkdir -p /opt/portafolio
sudo chown "$USER":"$USER" /opt/portafolio
git clone https://github.com/<your-username>/portafolio.git /opt/portafolio
cd /opt/portafolio
git checkout dev
```

> The deploy script (`scripts/deploy.sh`) expects `/opt/portafolio`. If you
> use a different path, also update `WorkingDirectory` and `ExecStart` in
> the systemd unit (see step 5).

## 3. Configure environment

```bash
cd /opt/portafolio/apps/api
cp .env.example .env
$EDITOR .env
```

Fill in at minimum:

- `LLM_BASE_URL` — your chat completion endpoint (e.g. `https://api.MiniMax.io/v1`).
- `LLM_API_KEY` — your API key.
- `CHAT_MODEL` — model name (e.g. `MiniMax-M2.7-highspeed`).
- `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL` — same shape
  for embeddings (defaults to OpenAI-compatible; switch to local if you
  run LM Studio / Ollama).

The defaults in `.env.example` are good local-dev defaults; **production
needs real keys**.

`CORS_ALLOW_ORIGINS` already covers `localhost:4321` for local Astro
preview, and the backend enables a regex that allows every `*.vercel.app`
preview automatically (Phase 6). For a custom production frontend domain,
append it to `CORS_ALLOW_ORIGINS` in this file.

## 4. Set up the Python virtualenv

```bash
cd /opt/portafolio/apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

> **Heads up about dependencies**: the project uses `chromadb`, `openai`,
> `tiktoken`, and a few native wheels. `build-essential` is required for
> any that don't ship a prebuilt wheel for your Python version.

## 5. Initial vector-store indexing

The first run needs a populated ChromaDB. Run the reindex CLI from inside
`apps/api`:

```bash
cd /opt/portafolio/apps/api
.venv/bin/python scripts/reindex.py --force
```

- `--force` rebuilds both the master index and every per-project collection
  from scratch (use it on first run and after schema changes).
- Without `--force`, the script skips projects whose collection is already
  populated. Safe for routine updates, but useless on an empty store.

Expected output: one line per project, ending with a non-zero `errors=0`
summary. Exit code `0` means the index is ready.

## 6. Install the systemd service

Copy the unit file shipped with the repo and enable it:

```bash
sudo cp /opt/portafolio/apps/api/systemd/portafolio.service \
        /etc/systemd/system/portafolio.service

sudo systemctl daemon-reload
sudo systemctl enable --now portafolio.service
```

What this does:

- `daemon-reload` picks up the new unit file.
- `enable --now` activates the service at boot AND starts it right now.
- The unit binds to `127.0.0.1:8000` on purpose — the backend should never
  be exposed directly. Cloudflare Tunnel will proxy external traffic to
  that loopback address.

If your repo lives somewhere other than `/opt/portafolio`, edit
`WorkingDirectory`, `EnvironmentFile`, and `ExecStart` in the unit before
copying it.

## 7. Verify

```bash
sudo systemctl status portafolio.service
```

You should see `active (running)` and the process owned by `ubuntu`. Then:

```bash
curl http://127.0.0.1:8000/api/health
```

Expected response (HTTP 200):

```json
{"status":"ok","chat_model":"...","embedding_model":"..."}
```

If `/api/health` does not respond:

- `sudo journalctl -u portafolio.service -n 100 --no-pager` — look for
  import errors or missing env vars.
- Confirm `apps/api/.env` exists and is readable by the `ubuntu` user
  (mode `0640` or `0600`, owned by `ubuntu`).
- Confirm ChromaDB was indexed (step 5) — the lifespan startup can hang
  if the persist directory is corrupted.

## 8. Log inspection

```bash
sudo journalctl -u portafolio.service -f
```

`StandardOutput=journal` + `StandardError=journal` route every uvicorn
log line into systemd's journal, tagged with `SyslogIdentifier=portafolio-api`.

Useful flags:

- `-n 200` — last 200 lines.
- `--since "1 hour ago"` — recent window.
- `-p err` — only errors and above.
- `--no-pager` — don't page through (handy for piping).

## 9. Updating deployments

The repo ships `scripts/deploy.sh` which automates the full update cycle
on the server. From the repo root on the VPS:

```bash
cd /opt/portafolio
bash scripts/deploy.sh
```

What it does, in order:

1. `git pull --ff-only` — fetch and fast-forward `dev`.
2. Create or reuse `.venv`, then `pip install -r requirements.txt`.
3. Run `python scripts/reindex.py --force` to refresh ChromaDB.
4. `sudo systemctl restart portafolio.service` if the service is active.

If `systemctl` isn't available (e.g., container without PID 1 systemd),
the script prints a notice and skips the restart — start uvicorn manually
in that case.

## 10. Next steps

- Expose the backend publicly: follow [`cloudflare-tunnel.md`](./cloudflare-tunnel.md).
- Deploy the frontend: follow [`vercel.md`](./vercel.md).
- Rotate `LLM_API_KEY` periodically and after any leak.
