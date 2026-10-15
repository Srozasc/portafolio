# Cloudflare Tunnel (recommended exposure path)

Expose the local FastAPI backend (`127.0.0.1:8000`) to the public internet
through Cloudflare Tunnel — **no open ports on the VPS, no nginx, no
certbot, free SSL, free DDoS protection.**

This is the project's recommended exposure path. The companion guide
[`generic-linux.md`](./generic-linux.md) covers the VPS setup that this
guide assumes already exists.

---

## Why Cloudflare Tunnel (vs. open ports + nginx + certbot)

| Concern | Open ports + nginx + certbot | Cloudflare Tunnel |
| --- | --- | --- |
| Inbound ports | 80 + 443 open to the world | **Zero** inbound ports |
| TLS certificate | Let's Encrypt via certbot, auto-renew cron | **Handled by Cloudflare**, always valid |
| Renewals / cron | Required, breaks silently | Not needed |
| DDoS protection | You provision it | **Included** at the edge |
| nginx config drift | Yes, you maintain it | None |
| Cloudflare account | Optional | **Required** |
| Outbound-only | No | **Yes** (one outbound to `quic`/`443`) |

For a single-VPS solo-freelancer profile, the operational win is decisive:
the only thing you have to keep alive on the VPS is `cloudflared` plus
the FastAPI process. There is no certificate, no renewal hook, no nginx
reload, and no firewall dance.

> **Trade-off**: Cloudflare sits in front of every request, which is
> usually a feature (CDN cache, analytics) but is a real architectural
> choice. If you ever need to bypass Cloudflare (e.g., a corporate
> client that blocks it), you'll need a fallback exposure path. For this
> portfolio project, the trade-off is firmly worth it.

---

## 1. Prerequisites

- A domain added to Cloudflare (free tier is fine). This guide uses
  `yourdomain.com` as a placeholder.
- The VPS already has the backend running on `127.0.0.1:8000` and
  reachable from the same host (see [`generic-linux.md`](./generic-linux.md)).
- DNS for the domain managed by Cloudflare (orange-clouded or grey-clouded
  records both work; the Tunnel injects its own DNS once configured).

## 2. Install `cloudflared`

Pick **one** of the two install paths below.

### Option A — Official package (recommended)

```bash
# Debian / Ubuntu (amd64)
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
  | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] \
https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main" \
  | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt update
sudo apt install -y cloudflared
```

RPM-based distros (Fedora / RHEL / Amazon Linux) use the same key plus
a `cloudflared.repo` file — see the upstream docs for the exact block.

### Option B — Direct binary download

If you can't add the repo (locked-down hosts, no sudo for apt):

```bash
curl -fsSL -o /tmp/cloudflared \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
sudo install -m 0755 /tmp/cloudflared /usr/local/bin/cloudflared
cloudflared --version
```

Verify the install:

```bash
cloudflared --version
```

## 3. Authenticate the host

```bash
cloudflared tunnel login
```

This opens a browser window via a one-shot URL. Sign in to Cloudflare,
pick the zone (`yourdomain.com`), and approve. The browser shows a
success page; the CLI writes a `cert.pem` to `~/.cloudflared/`.

> **Headless servers**: copy the URL the command prints, paste it into a
> local browser, complete the flow, then re-`ssh` into the server. The
> cert is bound to the cert.pem file path, not the originating IP.

## 4. Create the tunnel

```bash
cloudflared tunnel create portafolio-api
```

Output is two important pieces:

```text
Tunnel credentials written to /home/ubuntu/.cloudflared/<UUID>.json
Created tunnel portafolio-api with id <UUID>
```

Note the UUID — you'll need it in the config file below. The
credentials JSON file is what lets `cloudflared` prove its identity to
Cloudflare; **never commit it** (it's already in `.gitignore`).

## 5. Add the DNS route

Pick a public hostname for the backend (this guide uses
`api.yourdomain.com`). Either let `cloudflared` create the DNS record for
you:

```bash
cloudflared tunnel route dns portafolio-api api.yourdomain.com
```

…or create a `CNAME` record manually in the Cloudflare dashboard
pointing `api.yourdomain.com` → `<UUID>.cfargotunnel.com`.

> The zone must already be added to your Cloudflare account before
> either route command works.

## 6. Configure `cloudflared`

Create `~/.cloudflared/config.yml`:

```yaml
tunnel: portafolio-api
credentials-file: /home/ubuntu/.cloudflared/<UUID>.json

ingress:
  - hostname: api.yourdomain.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

What this does:

- `tunnel` — the human-readable tunnel name.
- `credentials-file` — absolute path to the JSON created in step 4.
- `ingress` — routes each hostname to a backing service. The trailing
  `http_status:404` rule is **required**: every ingress table needs a
  catch-all so Cloudflare knows what to do for unmatched hostnames.

If you serve multiple tunnels on the same host, each config file lives
in its own directory and points at its own credentials JSON. One
`tunnel run` per config.

## 7. Run `cloudflared` as a service

`cloudflared` ships its own systemd unit generator:

```bash
sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

What `service install` does:

- Drops a `cloudflared.service` unit at `/etc/systemd/system/`.
- Copies your user's `~/.cloudflared/config.yml` and credentials into
  `/etc/cloudflared/` (the unit runs as root by default; tighten the
  unit if you prefer a dedicated user).
- Starts and enables the service.

Check status:

```bash
sudo systemctl status cloudflared
sudo journalctl -u cloudflared -f
```

You should see a `connection established` log line within a few seconds,
followed by periodic `connection` heartbeats.

## 8. Verify end-to-end

From any machine **outside** the VPS:

```bash
curl https://api.yourdomain.com/api/health
```

Expected response (HTTP 200):

```json
{"status":"ok","chat_model":"...","embedding_model":"..."}
```

If it doesn't respond:

- `sudo journalctl -u cloudflared -n 200 --no-pager` — look for
  `credentials-file not found`, `tunnel not found`, or DNS errors.
- `cloudflared tunnel info portafolio-api` — confirms the tunnel is
  registered with Cloudflare.
- `cloudflared tunnel list` — lists every tunnel on the account.
- Confirm `127.0.0.1:8000` on the VPS still answers locally — the Tunnel
  only forwards what the backend is serving.

## 9. Updating the backend

The backend behind the Tunnel can be restarted at any time. `cloudflared`
will reconnect automatically (it retries with backoff and surfaces
errors to the journal).

```bash
sudo systemctl restart portafolio.service
```

The Tunnel is unaffected — DNS, TLS, and credential rotation are all
Cloudflare's responsibility.

## 10. When NOT to use a Tunnel

- You need raw TCP/UDP forwarding (Cloudflare Tunnel is HTTP-centric
  for this use case; other protocols need a different setup).
- Your client base cannot reach Cloudflare's edge (rare corporate
  networks, certain countries).
- You are serving purely internal traffic between VPCs — use a VPC
  private link or WireGuard instead.

For this portfolio project, none of those apply.
