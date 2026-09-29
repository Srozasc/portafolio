# Domains

Canonical reference for the domains and hostnames used by this project, the services they point to, and the DNS / TLS layout.

## Registered domain

| Domain | Registrar | Purpose |
|---|---|---|
| `srozas.men` | Cloudflare Registrar | Apex domain. Reserved for personal use (landing page, blog, about — future). |

The portfolio infrastructure lives on subdomains so the apex stays clean for personal content.

## Active subdomains

| Hostname | Service | URL pattern | Notes |
|---|---|---|---|
| `portafolio.srozas.men` | Frontend | `https://portafolio.srozas.men` | Astro SSG on S3 + CloudFront. HTTPS via ACM wildcard cert. |
| `api.portafolio.srozas.men` | Backend | `https://api.portafolio.srozas.men` | FastAPI + ChromaDB on EC2, exposed via Cloudflare Tunnel. TLS at Cloudflare edge. |

## DNS layout (managed in Cloudflare)

| Host | Type | Target | Proxy |
|---|---|---|---|
| `portafolio.srozas.men` | CNAME | CloudFront distribution endpoint (`dxxxxxxxxxxxxx.cloudfront.net`) | Proxied (orange cloud) |
| `api.portafolio.srozas.men` | CNAME | Cloudflare Tunnel endpoint (`<UUID>.cfargotunnel.com`) | DNS only (grey cloud) |

The frontend proxies through Cloudflare for caching and DDoS protection. The backend stays DNS-only because the Tunnel already provides secure ingress — adding Cloudflare's proxy would add a hop without benefit.

## TLS

| Hostname | Cert source | Region |
|---|---|---|
| `portafolio.srozas.men` | ACM wildcard `*.srozas.men` | `us-east-1` (required for CloudFront) |
| `api.portafolio.srozas.men` | Cloudflare edge cert | N/A (managed by Cloudflare) |

## Historical placeholders

- `portafolio.example.com` was the placeholder in `apps/web/astro.config.mjs` during the design phase. Replaced by the real hostnames above once the AWS deployment plan was approved.
