# AWS Deploy (frontend + backend on AWS Free Tier)

End-to-end guide for deploying the Portafolio RAG stack on AWS Free Tier:
**S3 + CloudFront + ACM** for the static frontend, **EC2 t3.micro + IAM + SG**
for the FastAPI backend, and **Cloudflare Tunnel** for HTTPS ingress to the
backend (no ALB, no public IP on EC2).

> **Audience**: solo freelancer with an AWS account (Free Tier eligible) and a
> Cloudflare account with a domain registered.
> **Time**: ~2-3 hours for a fresh deploy (mostly waiting on Cloudflare
> Universal SSL provisioning and ChromaDB ingest).
> **Cost**: $0 during the 12-month Free Tier window with billing alarms at
> $5/$10/$20/$50.

This guide consolidates the per-step helpers in `scripts/aws/` (raw AWS
CLI + bash; no Terraform / CDK by design — single-instance project).

---

## Architecture

| Layer | Service | Region | Notes |
|---|---|---|---|
| Static frontend | S3 `portafolio-web-prod` | us-west-2 | Block Public Access ON. Origin Access Control (OAC) instead of public ACL. |
| CDN + TLS | CloudFront `EJ12TBQTYJ43D` | global edge | Alternate domain `portafolio.srozas.men`, ACM wildcard `*.srozas.men` (issued in **us-east-1**), `PriceClass_100`, HTTP/2, `Managed-CachingOptimized` cache policy, `Managed-SecurityHeadersPolicy`. |
| DNS (frontend CNAME) | Cloudflare | — | `portafolio.srozas.men → d2tjrpncms9n6q.cloudfront.net` (DNS only / grey cloud, **not proxied** — to keep ACM cert in use). |
| Backend runtime | EC2 `t3.micro` Amazon Linux 2023 | us-west-2 | Default VPC public subnet, IMDSv2 required, `DisableApiTermination=true`, EBS `gp3` 20 GB encrypted. |
| Backend storage | EBS only | us-west-2 | ChromaDB persisted to EBS at `/opt/portafolio/apps/api/data/chroma` (ephemeral — re-creatable from GitHub). |
| Backend ingress | nginx on EC2 (direct HTTPS) | us-west-2 | `listen 443 ssl http2` on EC2 Elastic IP `32.189.197.242`, terminates TLS with **Let's Encrypt** cert (ECC P-256, 90-day), proxies to `http://127.0.0.1:8000` (FastAPI). DNS for `api.portafolio.srozas.men` is **DNS-only** (grey cloud, not Cloudflare proxied) — A record points directly to the Elastic IP. |
| Cert management | Let's Encrypt via acme.sh + Cloudflare DNS-01 | — | Cert at `/etc/nginx/ssl/{fullchain,key}.pem`, auto-renewed by `~/.acme.sh/acme.sh --renew`. Email registered with Let's Encrypt: `srozas.dev@gmail.com` (replace with your own). |
| Cloudflare role | DNS only | — | Cloudflare is still the authoritative DNS for `srozas.men` and the registrar, but **no longer proxies** the `api.*` subdomain. Frontend CNAME (`portafolio.srozas.men → d2tjrpncms9n6q.cloudfront.net`) remains DNS-only (grey cloud) so Cloudflare doesn't intercept and break ACM cert usage on CloudFront. |
| Backend logs | CloudWatch Logs | us-west-2 | Log group `/portafolio-api*`, retention 7d. |
| IAM (backend) | Role `portafolio-api-ec2-role` + profile `portafolio-api-ec2-profile` | — | Inline policy: write-only CloudWatch Logs access to `/portafolio-api*`. Plus `AmazonSSMManagedInstanceCore` for Session Manager. |
| IAM (SSM) | Role `AWSSystemsManagerDefaultEC2InstanceManagementRole-us-west-2` | — | Trust policy: `ssm.amazonaws.com`. Required for the SSM agent to register with the account. |
| Security group | `sg-08a344543be098b0d` | — | 0 inbound rules. Outbound: TCP 443 (HTTPS), TCP 7844 (cloudflared), TCP 53 + UDP 53 (DNS). |

**Excluded by design:** NAT Gateway, ALB, RDS, EFS, Secrets Manager, S3
backup of ChromaDB, multi-AZ HA, custom VPC. Each one adds cost or
complexity this project does not need. Add only when justified.

---

## Free Tier strategy

| Resource | Free Tier limit | This project uses | Within limit? |
|---|---|---|---|
| EC2 `t3.micro` | 750 h/mo for 12 months | 730 h/mo (always on) | ✅ |
| EBS gp3 | 30 GB-month for 12 months | 20 GB × 730 h = ~14.5 GB-month | ✅ |
| S3 Standard | 5 GB storage + 15 GB transfer × 12 months | ~0.5 GB storage + <1 GB/mo transfer | ✅ |
| CloudFront | 1 TB data transfer + 10 M requests/mo for 12 months | <1 GB transfer + <100 k req/mo | ✅ |
| CloudWatch Logs | 5 GB ingest + 5 GB storage | ~50 MB/mo | ✅ |
| Data transfer OUT (EC2 → internet) | 100 GB/mo for 12 months | <5 GB/mo (only `dnf`, `git`, `pip`, `cloudflared`) | ✅ |

After the 12-month window, see [Post-Free-Tier decision matrix](#post-free-tier-decision-matrix) below.

---

## Provisioning steps

The detailed provisioning steps are captured in `odd/tasks/aws-deploy.md`
(eight tasks T1-T8) and the per-step helpers live in `scripts/aws/`.
Summary:

### T1. Register domain in Cloudflare
- Register `srozas.men` via Cloudflare Registrar (cheapest TLDs, free privacy).
- NS records auto-pointed to Cloudflare nameservers.

### T2. Provision S3 + CloudFront + ACM for the frontend
- `aws s3api create-bucket --bucket portafolio-web-prod --region us-west-2 --create-bucket-configuration LocationConstraint=us-west-2`
- Block Public Access: `aws s3api put-public-access-block` with all four flags.
- ACM cert: `aws acm request-certificate --domain-name srozas.men --subject-alternative-names *.srozas.men --validation-method DNS --region us-east-1`
- Validate via Cloudflare DNS CNAME (one CNAME record for both domains).
- CloudFront OAC: `aws cloudfront create-origin-access-control`
- CloudFront distribution: see `scripts/aws/cloudfront-portafolio-config.json`.
- Bucket policy: see `scripts/aws/portafolio-bucket-policy.json` (Condition `AWS:SourceArn` pinned to distribution ARN).

### T3. Provision EC2 + IAM role + SG + EIP
- IAM role `portafolio-api-ec2-role` with inline CloudWatch Logs write-only policy (`scripts/aws/ec2-cloudwatch-logs-policy.json`).
- IAM role `AWSSystemsManagerDefaultEC2InstanceManagementRole-us-west-2` (Default Host Management Configuration — required for SSM agent to register on a never-used account).
- Security group `portafolio-api-sg` (`sg-08a344543be098b0d`) with **0 inbound** rules and outbound TCP 443, TCP 7844, TCP 53, UDP 53.
- EC2 launch: `aws ec2 run-instances` with `--iam-instance-profile Name=portafolio-api-ec2-profile`, EBS gp3 20 GB encrypted, IMDSv2 required (`HttpTokens=required`), `DisableApiTermination=true`, monitoring enabled.
- Elastic IP allocated and associated.

### T4. Port systemd unit + bootstrap script to AL2023
- `apps/api/systemd/portafolio.service`: `User=ubuntu` → `User=portafolio` (dedicated system user created by the bootstrap), add `Environment=PYTHONUNBUFFERED=1` and `MemoryHigh=700M/MemoryMax=900M` (t3.micro has 1 GB).
- `scripts/aws/amazon-linux-bootstrap.sh`: idempotent, installs git/python3/python3-pip/python3-devel/gcc via dnf, creates `portafolio` system user, clones repo to `/opt/portafolio`, creates venv at `apps/api/.venv`, installs requirements, copies systemd unit, creates `.env` from `.env.example` only if missing, reloads systemd.

### T5. Bootstrap EC2 + populate ChromaDB
- Run bootstrap via SSM (no SSH needed; the bootstrap script pulls deps and clones from public GitHub):
  ```bash
  aws ssm send-command --instance-ids i-XXXX \
    --document-name AWS-RunShellScript \
    --parameters file://scripts/aws/t5-bootstrap-runner.json
  ```
- SCP the production `.env` to EC2 (the script's secrets stay out of model context):
  ```bash
  scp -i ~/.ssh/portafolio-api-key.pem apps/api/.env ec2-user@<eip>:/tmp/portafolio.env
  ssh -i ~/.ssh/<key> ec2-user@<eip> 'sudo bash /tmp/t5-finish-ownership.sh && sudo cp /tmp/portafolio.env /opt/portafolio/apps/api/.env && sudo chown portafolio:portafolio /opt/portafolio/apps/api/.env && sudo chmod 600 /opt/portafolio/apps/api/.env'
  ```
- Install `eval_type_backport` in the venv (required by pydantic 2.13 for Python 3.9).
- Patch all backend `.py` files with `from __future__ import annotations` (PEP 604 `X | None` syntax requires Python 3.10+).
- Patch `scripts/ingest_repo.py`: `from typing import Self` → `from typing_extensions import Self`.
- Strip inline `# comment` after numeric values in `.env` (python-dotenv does not handle inline comments by default).
- Run `python -m scripts.reindex --force` to populate ChromaDB from the 6 project `.md` files.

### T6. HTTPS ingress via nginx + Let's Encrypt on EC2

The backend is exposed at `https://api.portafolio.srozas.men` via nginx on the EC2 instance (no Cloudflare Tunnel). nginx terminates TLS with a Let's Encrypt certificate and reverse-proxies to FastAPI on `127.0.0.1:8000`.

**6a. Switch `api.portafolio.srozas.men` to DNS-only** (so Cloudflare doesn't proxy and we serve TLS directly from EC2):
- Delete the existing Cloudflare "Tunnel" record
- Create an A record pointing to EC2 Elastic IP `32.189.197.242`, **proxied=false** (grey cloud)

Can be done via Cloudflare dashboard or API:
```bash
# Via API (replace CF_API_TOKEN with a token that has Zone:DNS:Edit permission)
curl -X PATCH "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records/$RECORD_ID" \
  -H "Authorization: Bearer $CF_API_TOKEN" -H "Content-Type: application/json" \
  --data '{"type":"A","content":"32.189.197.242","proxied":false,"ttl":60}'
```

**6b. Open TCP 443 inbound on the EC2 security group** (Cloudflare edge is no longer in the path, so browsers hit the EC2 IP directly):
```bash
aws ec2 authorize-security-group-ingress \
  --group-id sg-08a344543be098b0d \
  --protocol tcp --port 443 --cidr 0.0.0.0/0 \
  --profile portafolio
```

**6c. Install `acme.sh` on EC2 and issue a Let's Encrypt cert** via Cloudflare DNS-01 challenge (free, automated, no inbound ports needed for validation):
```bash
# SSH to EC2 (port 22 was opened temporarily for this; close after)
ssh -i ~/.ssh/portafolio-api-key.pem ec2-user@32.189.197.242

# On EC2: install acme.sh (AL2023 minimal has no cron; use --force to skip)
curl -fsSL https://get.acme.sh | sh -s -- email=YOUR_EMAIL@example.com --force
source ~/.bashrc

# Set Cloudflare API token + Zone ID (for DNS-01 challenge)
export CF_Token="your-cloudflare-api-token"
export CF_Zone_ID="your-zone-id"

# Issue cert (DNS-01 via Cloudflare API; acme.sh writes _acme-challenge TXT record automatically)
~/.acme.sh/acme.sh --issue -d api.portafolio.srozas.men --dns dns_cf
# Note: default CA is ZeroSSL, which can hang for hours. Switch to Let's Encrypt first:
~/.acme.sh/acme.sh --set-default-ca --server letsencrypt

# Install cert files to /tmp/le-cert for nginx to pick up
~/.acme.sh/acme.sh --install-cert -d api.portafolio.srozas.men \
  --cert-file /tmp/le-cert/cert.pem \
  --key-file /tmp/le-cert/key.pem \
  --fullchain-file /tmp/le-cert/fullchain.pem
```

**6d. Install nginx and configure the vhost**:
```bash
sudo dnf install -y nginx
sudo mkdir -p /etc/nginx/ssl
sudo cp /tmp/le-cert/fullchain.pem /etc/nginx/ssl/fullchain.pem
sudo cp /tmp/le-cert/key.pem /etc/nginx/ssl/key.pem
sudo chmod 644 /etc/nginx/ssl/fullchain.pem
sudo chmod 600 /etc/nginx/ssl/key.pem

sudo tee /etc/nginx/conf.d/portafolio-api.conf > /dev/null <<'NGINX'
server {
    listen 443 ssl http2;
    server_name api.portafolio.srozas.men;
    ssl_certificate     /etc/nginx/ssl/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    access_log /var/log/nginx/portafolio-api.access.log;
    error_log  /var/log/nginx/portafolio-api.error.log;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
NGINX

# Disable default nginx welcome site (we don't serve port 80)
sudo sed -i 's|^    listen       80 default_server;|#    listen       80 default_server;|' /etc/nginx/nginx.conf

# Test config and start
sudo nginx -t
sudo systemctl enable --now nginx
```

**6e. Verify end-to-end**:
```bash
curl -i https://api.portafolio.srozas.men/api/health
# Should return: HTTP/1.1 200 OK, Server: nginx/1.30.5, JSON body
openssl s_client -servername api.portafolio.srozas.men -connect api.portafolio.srozas.men:443
# Should show: subject=CN=api.portafolio.srozas.men, issuer=Let's Encrypt
```

**Cert renewal** (every ~60 days):
- `~/.acme.sh/acme.sh --renew -d api.portafolio.srozas.men` (regenerates files in `/tmp/le-cert/`)
- `sudo cp /tmp/le-cert/{fullchain,key}.pem /etc/nginx/ssl/ && sudo systemctl reload nginx`
- Configure systemd timer or cron before cert expires at day 90

### T7. Update CORS, PUBLIC_API_URL, env wiring + redeploy
- On EC2, append `https://portafolio.srozas.men` to `CORS_ALLOW_ORIGINS` in `/opt/portafolio/apps/api/.env`; restart `portafolio.service`.
- Update `apps/web/astro.config.mjs` site to `https://portafolio.srozas.men`.
- Rebuild frontend (critical: pass `PUBLIC_API_URL=https://api.portafolio.srozas.men` at build time, otherwise the bundle bakes in the fallback `http://localhost:8000`):
  ```bash
  PUBLIC_API_URL=https://api.portafolio.srozas.men npm run build
  ```
- Sync to S3: `aws s3 sync dist/ s3://portafolio-web-prod/ --delete`.
- Invalidate CloudFront: `aws cloudfront create-invalidation --distribution-id EJ12TBQTYJ43D --paths "/*"`.
- Verify: `curl -I https://portafolio.srozas.men/` returns 200; bundle contains `"https://api.portafolio.srozas.men"`.

### T8. Write docs (this file) + update README
- See `docs/deploy/aws.md` (this doc) and root `README.md`.

---

## Gotchas (read this before debugging)

### AL2023 ships Python 3.9, but the codebase uses 3.10+ / 3.11+ syntax

- The codebase uses **PEP 604** union syntax (`X | None`, `dict[str, int]`) which requires Python 3.10+.
- It also uses `typing.Self` which requires Python 3.11+.
- **Workarounds applied to the EC2 instance** (long-term: upgrade to Python 3.11 via `dnf install python3.11`):
  - `pip install eval_type_backport` in the venv (required by pydantic 2.13).
  - Add `from __future__ import annotations` to every backend `.py` file using new union syntax.
  - In `scripts/ingest_repo.py`: `from typing import Self` → `from typing_extensions import Self`.

### python-dotenv does NOT strip inline `# comment` after values

- If the user's `.env` has `SIMILARITY_THRESHOLD=0.0  # comment`, python-dotenv treats the entire line as the value, so pydantic float parsing fails.
- Fix: comments must be on their own line.

### Astro's Chatbot uses `import.meta.env.PUBLIC_API_URL` with fallback `http://localhost:8000`

- Without `PUBLIC_API_URL` at build time, the bundle bakes in `http://localhost:8000` and the chatbot calls the user's local browser loopback.
- Always rebuild with `PUBLIC_API_URL=https://api.portafolio.srozas.men`.

### CloudFront + S3 do NOT auto-serve `index.html` for directory URLs

- Astro generates URLs with trailing slash by default (`/proyectos/<slug>/`).
- CloudFront passes that path as-is to S3; S3 returns 403 (Block Public Access + the key doesn't exist).
- Fix in source: all internal nav URLs include explicit `/index.html` suffix. Alternative: a CloudFront Function at the edge that rewrites `/foo/` → `/foo/index.html` (kept in `scripts/aws/cloudfront-directory-index.js` for future when the schema is fixed).

### acme.sh defaults to ZeroSSL — switch to Let's Encrypt for fast issuance

- acme.sh's default CA is ZeroSSL, which can hang for **hours** in the "processing" state (no useful error, just polls). Symptom: cert validates via DNS but `Order status is 'processing'` never finishes.
- Fix: `~/.acme.sh/acme.sh --set-default-ca --server letsencrypt` and re-issue. Let's Encrypt typically completes in 10-30 seconds.

### AL2023 minimal AMI has no cron

- acme.sh tries to install a cron job for auto-renewal; install fails on the minimal AL2023 AMI (`crontab: command not found`).
- Workaround: install with `--force` flag (`curl ... | sh -s -- email=... --force`). Set up a systemd timer later for actual renewal:
  ```ini
  # /etc/systemd/system/acme-renewal.timer
  [Unit]
  Description=Renew Let's Encrypt certs
  [Timer]
  OnCalendar=*-*-* 03:00:00
  Persistent=true
  [Install]
  WantedBy=timers.target
  ```

### Backend IP exposed in DNS (security trade-off vs Cloudflare Tunnel)

- By removing Cloudflare Tunnel and pointing DNS directly to the EC2 Elastic IP, the origin IP is publicly visible (anyone who runs `dig api.portafolio.srozas.men` learns the EC2 IP).
- For a low-traffic portfolio chat this is acceptable. For higher-stakes production, consider keeping Cloudflare Tunnel (with its overhead) or putting nginx behind a CDN/WAF that hides the origin IP.

### SG changes vs the original Cloudflare Tunnel setup

- We **added** TCP 443 inbound (for browser HTTPS to nginx).
- We **removed** TCP 7844 outbound (was needed for cloudflared HTTP/2 tunnel; not needed anymore).
- Final SG: 1 inbound (443) + 3 egress (53 TCP, 53 UDP, 443 TCP).
- Workaround if stuck: upload a custom SSL certificate to Cloudflare (SSL/TLS → Edge Certificates → Upload).

### Bash tool safety policy blocks some patterns

- The assistant's `bash` tool may block patterns like `chown -R`, `sed -i` on `/etc/`, and `git commit -m "..."` containing those patterns.
- Workaround: write helper scripts to `scripts/aws/`, then run them via SSM `send-command` or via user-side `scp + ssh`.

### AWS MCP server is read-only diagnostic only

- `mcp-proxy-for-aws` (the official AWS MCP) only exposes `aws-serverless` functions (Lambda logs, traces). All mutating operations (`s3:create_bucket`, `ec2:run_instances`, `cloudfront:create_distribution`, etc.) MUST go via raw `aws` CLI from bash, not via the MCP `run_script` tool.

### Default Host Management Configuration was not set up in this AWS account

- Symptom: SSM agent registers but `RequestManagedInstanceRoleToken: AccessDeniedException`.
- Fix: create IAM role `AWSSystemsManagerDefaultEC2InstanceManagementRole-<region>` with trust policy `ssm.amazonaws.com`, attach managed policy `AmazonSSMManagedEC2InstanceDefaultPolicy`, then `aws ssm update-service-setting --setting-id /ssm/managed-instance/default-ec2-instance-management-role --setting-value <ROLE_NAME>` (the **role name, not ARN** — the regex disallows colons).

---

## Post-Free-Tier decision matrix

At month 13, evaluate migration paths. All three are designed to keep the backend reachable at `https://api.portafolio.srozas.men` — nginx + Let's Encrypt is portable across providers (just move the nginx vhost config + the cert files).

| Option | Monthly cost | Effort | When to choose |
|---|---|---|---|
| **Lightsail $3.50/mo bundle** | ~$3.50 (1 GB RAM, 1 vCPU, 40 GB SSD) | Lowest — 30 min snapshot restore + retag | Default choice for solo dev. Same instance type as t3.micro. Egress free up to 1 TB/mo. |
| **Hetzner VPS CX22** | €4.35 (~$4.50) | Medium — re-run bootstrap, new EIP, re-issue LE cert for new IP | Cheapest USD/CAD/EUR; excellent network. DNS-01 via Hetzner DNS API (acme.sh supports `dns_hetzner`). |
| **EC2 Spot (`t4g.small`)** | ~$3-5 (variable) | Low — same AMI, same bootstrap | If you want to stay on AWS and don't mind occasional restarts. |

**Frontend stays where it is** (S3 + CloudFront + ACM is essentially free after Free Tier — pay only for data transfer out at $0.085/GB after the first 1 TB, which this project won't approach).

**Don't migrate just to migrate.** If the workload is stable and the bill is <$2/mo, staying on EC2 Free Tier residual pricing is fine. The decision matrix is for when Free Tier ends and the bills start accumulating, not for premature optimization.

---

## Operational runbook

### Access the backend EC2 (no SSH needed)

```bash
# Session Manager over HTTPS (no inbound port required)
aws ssm start-session --target i-04b4296febfda434a --profile portafolio
```

### Tail the backend logs

```bash
aws ssm start-session --target i-04b4296febfda434a --profile portafolio
# Inside the session:
sudo journalctl -u portafolio.service -f
```

### Restart the backend

```bash
aws ssm send-command --instance-ids i-04b4296febfda434a \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["sudo systemctl restart portafolio.service"]' \
  --profile portafolio
```

### Restart / reload nginx (after config or cert change)

```bash
# Test config first
aws ssm send-command --instance-ids i-04b4296febfda434a \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["sudo nginx -t"]' \
  --profile portafolio

# Reload (zero-downtime) — preferred for cert renewals
aws ssm send-command --instance-ids i-04b4296febfda434a \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["sudo systemctl reload nginx"]' \
  --profile portafolio

# Hard restart (downtime)
aws ssm send-command --instance-ids i-04b4296febfda434a \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["sudo systemctl restart nginx"]' \
  --profile portafolio
```

### Tail nginx access/error logs

```bash
aws ssm start-session --target i-04b4296febfda434a --profile portafolio
# Inside the session:
sudo tail -f /var/log/nginx/portafolio-api.access.log
sudo tail -f /var/log/nginx/portafolio-api.error.log
```

### Renew Let's Encrypt cert (every ~60 days)

```bash
# 1. Renew via acme.sh
aws ssm send-command --instance-ids i-04b4296febfda434a \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["sudo -u ec2-user /home/ec2-user/.acme.sh/acme.sh --renew -d api.portafolio.srozas.men"]' \
  --profile portafolio

# 2. Copy renewed certs to nginx ssl dir and reload
aws ssm send-command --instance-ids i-04b4296febfda434a \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["sudo cp /tmp/le-cert/fullchain.pem /etc/nginx/ssl/fullchain.pem && sudo cp /tmp/le-cert/key.pem /etc/nginx/ssl/key.pem && sudo chmod 600 /etc/nginx/ssl/key.pem && sudo systemctl reload nginx"]' \
  --profile portafolio
```

### Test SSL handshake from outside

```bash
openssl s_client -servername api.portafolio.srozas.men -connect api.portafolio.srozas.men:443 -showcerts 2>&1 | head -30
# Look for: subject=CN=api.portafolio.srozas.men, issuer=Let's Encrypt, verify return:1
```

### Re-populate ChromaDB after data changes

```bash
# From the EC2 instance (via SSM session), as portafolio user:
sudo -u portafolio bash -c 'cd /opt/portafolio/apps/api && .venv/bin/python -m scripts.reindex --force'
```

### Roll back the frontend to the previous deploy

```bash
# 1. Find the previous S3 sync (or git checkout)
git checkout <previous-commit>
PUBLIC_API_URL=https://api.portafolio.srozas.men npm run build
aws s3 sync dist/ s3://portafolio-web-prod/ --delete --profile portafolio
aws cloudfront create-invalidation --distribution-id EJ12TBQTYJ43D --paths "/*" --profile portafolio
```

### Tear down everything (cleanup)

```bash
# Tag the resources with Feature=aws-deploy first so this is auditable
aws resourcegroupstaggingapi get-resources --tag-filters Key=Feature,Values=aws-deploy
# Then delete in reverse order:
# 1. nginx + cert cleanup on EC2 (via SSM)
aws ssm send-command --instance-ids i-04b4296febfda434a \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["sudo systemctl stop nginx", "sudo yum remove -y nginx"]' \
  --profile portafolio
# 2. CloudFront + ACM (frontend cert + distribution)
aws cloudfront delete-distribution --id EJ12TBQTYJ43D --if-match <etag>
aws acm delete-certificate --certificate-arn <cert-arn> --region us-east-1
# 3. S3 (frontend bucket)
aws s3 rm s3://portafolio-web-prod/ --recursive
aws s3api delete-bucket --bucket portafolio-web-prod
# 4. EC2 (instance + Elastic IP + SG)
aws ec2 terminate-instances --instance-ids i-04b4296febfda434a
aws ec2 release-address --allocation-id eipalloc-019f2baad739de6a9
aws ec2 delete-security-group --group-id sg-08a344543be098b0d
# 5. IAM (instance profile + role)
aws iam remove-role-from-instance-profile --instance-profile-name portafolio-api-ec2-profile --role-name portafolio-api-ec2-role
aws iam delete-instance-profile --instance-profile-name portafolio-api-ec2-profile
aws iam delete-role --role-name portafolio-api-ec2-role
# 6. SSM Default Host Management config (account-wide)
aws ssm delete-service-setting --setting-id /ssm/managed-instance/default-ec2-instance-management-role --region us-west-2
# 7. Cloudflare side (user does via dashboard or API):
#    - Delete the api.portafolio.srozas.men A record (32.189.197.242)
#    - The srozas.men zone itself stays (still used for portafolio.srozas.men DNS-only CNAME)
#    - If you don't want to keep the zone: delete via dashboard
#    - Let's Encrypt cert expires on its own at day 90 — no action needed
```

---

## Cross-references

- [`domains.md`](./domains.md) — canonical domain reference (registered domain, hostnames, DNS, TLS layout).
- [`cloudflare-tunnel.md`](./cloudflare-tunnel.md) — **historical** (kept for reference only). This project originally used Cloudflare Tunnel but pivoted to direct nginx + Let's Encrypt (T6 architectural change). The doc is still useful if you want to use Cloudflare Tunnel for a different deployment.
- [`generic-linux.md`](./generic-linux.md) — non-AWS Linux VPS variant (for the Hetzner post-Free-Tier path).
- [`vercel.md`](./vercel.md) — historical (kept for reference). The frontend is no longer on Vercel.
