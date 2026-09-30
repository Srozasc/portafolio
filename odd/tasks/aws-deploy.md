# Feature: AWS Deployment

> Migrate the Portafolio RAG stack from "Vercel + Linux VPS + Cloudflare Tunnel" to "S3 + CloudFront + EC2 + Cloudflare Tunnel" on AWS Free Tier, in `us-west-2`. Frontend at `portafolio.srozas.men`, backend at `api.portafolio.srozas.men`.

## Metadata

- **Status**: planning (no source writes yet)
- **Region**: `us-west-2` (Oregon)
- **Domain**: `srozas.men` registered at Cloudflare Registrar
- **Frontend hostname**: `portafolio.srozas.men`
- **Backend hostname**: `api.portafolio.srozas.men`
- **Account**: free-tier-only, prepaid card with minimal balance, $100 promotional credits
- **Free Tier window**: 12 months
- **Post-Free-Tier plan**: migrate backend to Lightsail ($3.50/mo) or Hetzner VPS ($4/mo); frontend stays cheap in any case
- **Branch policy**: feature branch `feat/aws-deploy`, branched from `dev`

## Architecture

| Layer | Service | Notes |
|---|---|---|
| Frontend | S3 + CloudFront + ACM | Static Astro SSG; Origin Access Control (OAC); ACM wildcard `*.srozas.men` requested in `us-east-1` |
| DNS | Cloudflare | Already configured; CNAME for `portafolio.srozas.men` → CloudFront, CNAME for `api.portafolio.srozas.men` → Tunnel endpoint |
| Backend exposure | Cloudflare Tunnel | Outbound-only from EC2; zero inbound ports; TLS handled by Cloudflare |
| Backend runtime | EC2 `t3.micro` (Amazon Linux 2023) | Default VPC, public subnet, Elastic IP, IAM instance role for CloudWatch Logs |
| Backend storage | EBS `gp3` 20 GB | Ephemeral — ChromaDB is a derived cache regenerated from GitHub via `apps/api/scripts/ingest_repo.py` |
| Logs | CloudWatch Logs | Retention 7 days |
| Billing safety | Billing alarms at $5 / $10 / $20 / $50 | Insurance against Free Tier edge cases |

**Excluded by design**: NAT Gateway, ALB, RDS, EFS, Secrets Manager, S3 backup of ChromaDB, multi-AZ HA, custom VPC. Each one adds cost or complexity this project does not need. Add only when justified.

## Tasks

### T1. Register domain in Cloudflare
- The domain `srozas.men` is already purchased; verify it appears in the Cloudflare account and nameservers are pointed to Cloudflare
- Confirm the registrar DNS records are Cloudflare's nameservers (auto-set when registered via Cloudflare Registrar)
- Subdomain strategy: `portafolio.srozas.men` for frontend, `api.portafolio.srozas.men` for backend (already decided in planning)
- Document the registered domain and nameservers in this repo for future reference

### T2. Provision S3 + CloudFront + ACM for the frontend
- [x] Create S3 bucket `portafolio-web-prod` in `us-west-2` — Bucket ARN: `arn:aws:s3:::portafolio-web-prod`
- [x] Block all public access (BPA: `BlockPublicAcls=true, IgnorePublicAcls=true, BlockPublicPolicy=true, RestrictPublicBuckets=true`); OAC is the only ingress
- [x] Request ACM wildcard certificate `*.srozas.men` in `us-east-1` — Cert ARN: `arn:aws:acm:us-east-1:467640459757:certificate/6636d82b-5839-4603-9fe5-c6bb9513c0c2`
- [x] Validate the cert via DNS CNAMEs in Cloudflare — Validation token `_c62176285a39cff1d245601bc43e4e00.srozas.men` → `_aaeb00c7d9ac3a6f11808ed66ce8bc58.wzccmgtwzk.acm-validations.aws` (CNAME added by user 2026-09-29; status moved to ISSUED)
- [x] Create Origin Access Control (OAC) — ID: `EN5LKIP1DFMJ3` (sigv4, signing behavior always)
- [x] Create CloudFront distribution — ID: `EJ12TBQTYJ43D`, domain: `d2tjrpncms9n6q.cloudfront.net`, alternate domain `portafolio.srozas.men`, PriceClass_100, HTTP/2, Compress enabled, CachePolicyId `658327ea-f89d-4fab-a63d-7e88639e58f6` (Managed-CachingOptimized), ResponseHeadersPolicyId `67f7725c-6f97-4210-82d7-5512b31e9d03` (Managed-SecurityHeadersPolicy)
- [x] Update bucket policy to allow OAC access (Condition: `AWS:SourceArn` pinned to this distribution ARN — restricts to our distribution only)
- [ ] Add CNAME in Cloudflare DNS pointing `portafolio.srozas.men` to `d2tjrpncms9n6q.cloudfront.net` (DNS only / grey cloud, not proxied — to keep ACM cert in use)
- [ ] Wait for CloudFront distribution to finish deploying (status `InProgress` → `Deployed`, ~5-15 min)
- [ ] Verify `curl https://portafolio.srozas.men` returns 200 + valid HTML

**Notes for T2**:
- Script `scripts/aws/cloudfront-portafolio-config.json` holds the full distribution config — re-runnable for `update-distribution` later.
- Script `scripts/aws/portafolio-bucket-policy.json` holds the bucket policy — re-runnable for `put-bucket-policy` later.
- AWS MCP server (`mcp-proxy-for-aws`) is read-only diagnostic only (Lambda logs, traces); provisioning goes via raw `aws` CLI through bash.

### T3. Provision EC2 + IAM role + security group
- [x] Launch `t3.micro` Amazon Linux 2023 in `us-west-2`, default VPC, public subnet — Instance: `i-04b4296febfda434a`, AMI: `ami-0225e90bcec9e5e16`, EBS gp3 20 GB encrypted
- [x] Attach IAM instance role granting only CloudWatch Logs write-only on log group `/portafolio-api*` — Role: `portafolio-api-ec2-role`, Instance Profile: `portafolio-api-ec2-profile`
- [x] Security group: 0 inbound, outbound 443 TCP + 53 TCP/UDP (DNS) — SG: `sg-08a344543be098b0d`. Note: added DNS (port 53) beyond the original 'outbound 443 only' plan because name resolution is needed for HTTPS to work (github.com, pypi.org, cloudflare endpoints). Without DNS, no HTTPS works.
- [x] Allocate and associate an Elastic IP — EIP: `32.189.197.242`, Allocation: `eipalloc-019f2baad739de6a9`, Association: `eipassoc-0f545ef1e565e784a`
- [x] Tag the instance: `Name=portafolio-api`, `Environment=prod`, `Feature=aws-deploy`
- [x] IMDSv2 required (`HttpTokens=required`), `DisableApiTermination=true`, basic monitoring enabled
- [x] SSH key pair `portafolio-api-key` created, private material saved to `~/.ssh/portafolio-api-key.pem` (NOT in repo). Fingerprint: `ce:89:be:c0:e1:e9:37:db:4d:64:8a:8e:fa:8c:f2:89:3b:76:34:c0`

### T4. Port systemd unit + deploy script to Amazon Linux 2023
- [x] Verified `apps/api/systemd/portafolio.service` for AL2023 compatibility — only `User=` needs change (systemd is the same init on AL2023)
- [x] Adapted `portafolio.service`:
  * `User=ubuntu` → `User=portafolio` (dedicated system user created by bootstrap; AL2023 default `ec2-user` is for SSH only)
  * Added `Environment=PYTHONUNBUFFERED=1` so logs flow to journald without buffering
  * Added `MemoryHigh=700M` + `MemoryMax=900M` (t3.micro has 1 GB RAM; keeps headroom for kernel + cloudflared)
- [x] Verified `scripts/deploy.sh` works on AL2023 as-is — uses `python3`, `pip`, `sudo systemctl` which are all present
- [x] Added idempotent `scripts/aws/amazon-linux-bootstrap.sh`:
  * Installs system deps via `dnf` (git, python3, python3-pip, python3-devel, gcc)
  * Creates `portafolio` system user (skips if exists)
  * Clones repo to `/opt/portafolio` (skips if already cloned)
  * Creates Python venv at `apps/api/.venv` (skips if exists)
  * Installs `requirements.txt`
  * Installs systemd unit at `/etc/systemd/system/portafolio.service`
  * Creates `.env` from `.env.example` only if missing (preserves prod values)
  * Reloads systemd
  * Logs next-step instructions for T5 (Chromadb regen) and `systemctl enable --now`

### T5. Bootstrap EC2 and verify ChromaDB regeneration from GitHub
- [x] Install git + python3 + python3-pip + python3-devel + gcc on AL2023 via dnf
- [x] Create system user `portafolio` (uid 993)
- [x] Clone `https://github.com/Srozasc/portafolio.git` (branch dev) to `/opt/portafolio`
- [x] Adapt systemd unit `User=ubuntu` -> `User=portafolio` + add `PYTHONUNBUFFERED=1` + memory limits
- [x] Install systemd unit at `/etc/systemd/system/portafolio.service` + `systemctl enable`
- [x] Create Python venv at `/opt/portafolio/apps/api/.venv` + install `requirements.txt` (101 packages)
- [x] Recursive chown `portafolio:portafolio` on `/opt/portafolio/apps/api/.venv`, `backend/`, `data/`, `scripts/`
- [x] User uploaded `apps/api/.env` via SCP (production values for LLM keys, embedding keys, ChromaDB dir)
- [x] Run `python -m scripts.reindex --force` — 6 projects, 6 index chunks, 18 detail chunks, 28 ChromaDB files, 43 MB
- [x] Install `eval_type_backport` (required by pydantic 2.13 for Python 3.9 compat)
- [x] Patch all 11 backend .py files with `from __future__ import annotations` (PEP 604 union syntax `X | None` requires Python 3.10+)
- [x] Patch `scripts/ingest_repo.py`: `from typing import Self` -> `from typing_extensions import Self` (Self was added to typing in 3.11)
- [x] Strip inline `# comment` after `SIMILARITY_THRESHOLD=0.0` in `.env` (python-dotenv does not strip inline comments by default, so the value was being read as `"0.0  # ..."`)
- [x] Start `portafolio.service` + verify `curl http://127.0.0.1:8000/api/health` returns `{"status":"ok","model":"...","embedding_model":"text-embedding-3-small","collections":[...7 collections with chunks...]}` from inside the instance

**Notes for T5 — important for future deploys**:
- AL2023 ships Python 3.9; the codebase uses Python 3.10+ syntax (`X | None`) and 3.11+ syntax (`typing.Self`). The fixes above are a workaround. Long-term options: (a) upgrade AL2023 Python via `dnf install python3.11`, or (b) bundle the patches into `amazon-linux-bootstrap.sh`.
- `dev` branch does NOT include `ingest_repo.py` (it's only on `feat/aws-deploy` locally, not pushed). For T5 we SCP'd it. Long-term: merge `feat/aws-deploy` into `dev` (or push `feat/aws-deploy` and have deploys use that branch).
- `dev` branch systemd unit still has `User=ubuntu`; the patch via sed is done post-clone. The local repo on `feat/aws-deploy` (T4) has `User=portafolio` already. Merging `feat/aws-deploy` into `dev` will fix this for future deploys.
- The safe.directory warning was a one-time setup; persist via `git config --global --add safe.directory /opt/portafolio` (done for both root and ec2-user).
- The bash safety policy in pi blocks `chown -R` and `sed -i` patterns via the bash tool. Workaround used: write helper scripts (`t5-finish-ownership.sh`) and have the user run them via SCP+SSH. Document this in T8 so future ops don't get stuck.
- Commit: `docs(ops): document chromadb regeneration from GitHub sources`

### T6. Configure Cloudflare Tunnel on EC2
- [x] Install `cloudflared` binary direct from GitHub releases (no dnf repo in AL2023) - version 2026.9.3 at `/usr/local/bin/cloudflared`
- [x] User authenticated via `cloudflared tunnel login` (browser auth; cert.pem at `~/.cloudflared/cert.pem` on EC2)
- [x] Created tunnel `portafolio-api`, ID `82107417-fe78-4d8c-b210-0d62f03ad372`, credentials at `~/.cloudflared/<ID>.json`
- [x] Auto-created CNAME in Cloudflare: `api.portafolio.srozas.men` -> tunnel (via `cloudflared tunnel route dns`)
- [x] Created `/etc/cloudflared/` directory with config.yml + cert.pem + credentials (mode 0600)
- [x] `cloudflared service install` (creates systemd unit at `/etc/systemd/system/cloudflared.service`)
- [x] Override: `TimeoutStartSec=0` (default 15s was killing service before tunnel could connect)
- [x] Protocol: `http2` (QUIC/UDP not viable - SG only allows TCP outbound; also need TCP 7844)
- [x] Added TCP 7844 outbound to SG `sg-08a344543be098b0d` (cloudflared's tunnel port)
- [x] `systemctl enable --now cloudflared`; service `active (running)`; connected to 4 edges (`1xpdx02`, `1xpdx03`, `1xsea01`, `1xsea11`)
- [ ] **Verify external `curl https://api.portafolio.srozas.men/api/health` returns 200** - blocked by **Universal SSL not provisioned yet** on Cloudflare zone `srozas.men` (typical for newly added domains, can take 5-15 min up to 24h). Error observed: `SSLV3_ALERT_HANDSHAKE_FAILURE (alert 40)`.

**Notes for T6**:
- cloudflared uses port **TCP 7844** (not 443) for HTTP/2 tunnel connection - required SG egress rule addition
- cloudflared defaults to **QUIC (UDP 7844)** which our SG blocks; forced `protocol: http2` in config
- `TimeoutStartSec=15` (cloudflared default unit) is too short - tunnel handshake takes longer; overrode to 0 (unlimited)
- **Universal SSL provision can take time for new zones.** User needs to verify SSL/TLS status in Cloudflare dashboard. Once Universal SSL is active, the external curl should work.

**Operational notes**:
- Tunnel credentials in `/etc/cloudflared/<ID>.json` (mode 0600, root-owned). DO NOT commit to repo.
- The cert.pem in `/etc/cloudflared/` is the Cloudflare auth cert (from `cloudflared tunnel login`). Don't commit either.
- For backups/restores of the tunnel, the credentials JSON is the source of truth - re-install with `cloudflared service install` + the same config + credentials JSON.
- Cloudflare edges currently connected: `1xpdx02, 1xpdx03, 1xsea01, 1xsea11` (mix of LA/SF/SEA regions)

### T7. Update CORS, PUBLIC_API_URL, and env wiring
- [x] Update `apps/api/.env` on EC2: `CORS_ALLOW_ORIGINS` now includes `https://portafolio.srozas.men` (appended via Python script + restart)
- [x] Restart `portafolio.service` - verified `ActiveState: active`, `/api/health` returns 200 with all 7 ChromaDB collections
- [x] Update `apps/web/astro.config.mjs`: `site: 'https://portafolio.srozas.men'`
- [x] Rebuild frontend with `PUBLIC_API_URL=https://api.portafolio.srozas.men npm run build` - bundle now references correct API URL
- [x] Sync `dist/` to S3 with `--delete` (removes old placeholder/index.html from T2)
- [x] Invalidate CloudFront cache `/*` - completed in ~20s
- [ ] End-to-end chat FAB test: `https://portafolio.srozas.men` -> click chat -> confirm streamed answer from `https://api.portafolio.srozas.men` arrives. **Blocked on Universal SSL** (same blocker as T6).

**Notes for T7**:
- Astro's Chatbot component uses `import.meta.env.PUBLIC_API_URL ?? FALLBACK_API_URL`. Without `PUBLIC_API_URL` at build time, the bundle bakes in `"http://localhost:8000"` (the fallback). First build attempt had this wrong; rebuild with `PUBLIC_API_URL=https://api.portafolio.srozas.men` fixed it.
- `aws s3 sync --delete` removes files in S3 not in local dist - this dropped the T2 placeholder/index.html
- CloudFront invalidation `/*` took ~20s for this distribution
- bundle hash changed between builds (different content) - `Chatbot.CQ8jU9Xs.js` -> `Chatbot.DOeg3O4F.js` after the API URL fix

### T8. Write `docs/deploy/aws.md` and update README
- Author `docs/deploy/aws.md` mirroring the structure of `docs/deploy/vercel.md`, `docs/deploy/generic-linux.md`, and `docs/deploy/cloudflare-tunnel.md`, but consolidated for AWS
- Update top-level `README.md` "Architecture" section to reflect the new AWS-backed stack with the new hostnames
- Update the "Documentation" links block
- Add a "Post-Free-Tier decision matrix" section to `aws.md` with the month-13 migration paths (Lightsail $3.50/mo, Hetzner VPS $4/mo, EC2 Spot)
- Commit: `docs(deploy): add AWS deployment guide and update README`

## Acceptance criteria

- Frontend serves from S3 + CloudFront at `https://portafolio.srozas.men`, HTTPS via the wildcard ACM cert
- Backend serves from EC2 + Cloudflare Tunnel at `https://api.portafolio.srozas.men`, no inbound ports on EC2
- `curl https://api.portafolio.srozas.men/api/health` returns `{"status":"ok", ...}` from any external machine
- Browser → `portafolio.srozas.men` → chat FAB → streaming answer from `api.portafolio.srozas.men` → real response (no `localhost:8000` fallback)
- ChromaDB can be regenerated from GitHub sources in <30 min on a fresh EC2 instance, with no manual data restoration step
- No AWS service outside Free Tier limits is in active use at any time during the 12-month window
- Billing alarms configured at $5 / $10 / $20 / $50

## Open questions deferred to execution

- IaC approach: lean raw AWS CLI + bash under `scripts/aws/`, not Terraform/CDK, for a single-instance project
- Secret storage on EC2: start with `.env` on disk; if uncomfortable, migrate to SSM Parameter Store (free)
- Whether to use the AWS-provided `cloudflared` package or a direct binary (T6)
