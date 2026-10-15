# Portafolio RAG

Professional portfolio navigable by chatbot with RAG. Visitors ask by stack (Python, AWS, etc.) and the bot returns conversational answers plus clickable project cards linking to pre-rendered detail pages.

## Status

✅ **Live in production**: [https://portafolio.srozas.men](https://portafolio.srozas.men) — backend reachable at `https://api.portafolio.srozas.men` via Cloudflare Tunnel.

## Architecture

- **Frontend**: Astro 4.x (SSG with islands) hosted on **S3 + CloudFront** with ACM wildcard cert `*.srozas.men`
- **Backend**: FastAPI (fork of [HiRag15k](https://example.com/HiRag15k)) on **EC2 `t3.micro`** (Amazon Linux 2023) with ChromaDB
- **Backend ingress**: **Cloudflare Tunnel** (no public inbound ports on EC2, no ALB)
- **Bot**: Two-step RAG — list (master index) → detail (per-project collection)
- **i18n**: Bilingual ES/EN with switcher
- **Region**: `us-west-2` (ACM cert in `us-east-1`)

See [`docs/deploy/aws.md`](docs/deploy/aws.md) for the full AWS deployment guide.

## Repo structure

```text
apps/
├── web/    # Astro frontend
└── api/    # FastAPI backend (fork of HiRag15k)
scripts/
├── aws/    # Raw AWS CLI helpers + JSON SSM params (no Terraform/CDK)
├── deploy.sh
└── *.py    # CLI tools (add_project, reindex, ingest_repo)
docs/
├── deploy/ # Deploy guides (aws.md, cloudflare-tunnel.md, etc.)
└── plans/  # Design + impl plan
odd/
└── tasks/  # Feature task plans
```

## Documentation

- [Design doc](docs/plans/2026-09-17-portafolio-rag-design.md)
- [Implementation plan](docs/plans/2026-09-17-portafolio-rag-impl-plan.md)
- **[AWS deploy guide](docs/deploy/aws.md)** — full setup with all gotchas
- [Cloudflare Tunnel guide](docs/deploy/cloudflare-tunnel.md)
- [Domains reference](docs/deploy/domains.md) — canonical DNS + TLS layout

## Quickstart (local dev)

```bash
# Backend
cd apps/api
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/reindex.py
.venv/bin/python -m uvicorn backend.main:app --reload

# Frontend
cd apps/web
npm install
PUBLIC_API_URL=http://localhost:8000 npm run build
```

## License

TBD
