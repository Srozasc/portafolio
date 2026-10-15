# Portafolio RAG

Personal portfolio navigable by chatbot with RAG. Visitors ask about my stack (Python, AWS, etc.) and the bot returns conversational answers plus clickable project cards linking to pre-rendered detail pages.

**Live**: <https://portafolio.srozas.men>

## Architecture

- **Frontend**: Astro 4.x (SSG with islands) hosted on **S3 + CloudFront** with ACM wildcard cert `*.srozas.men`
- **Backend**: FastAPI (fork of HiRag15k) on **EC2 t3.micro** (Amazon Linux 2023) with ChromaDB
- **Backend ingress**: **nginx + Let's Encrypt** on the EC2 instance (no ALB, no public ports other than 443)
- **Bot**: Two-step RAG — list (master index) → detail (per-project collection)
- **i18n**: Bilingual ES/EN with switcher
- **Region**: `us-west-2` (ACM cert in `us-east-1`)

## Repo structure

```
apps/
  web/    # Astro frontend
  api/    # FastAPI backend (data/projects/ has the RAG sources as .md)
docs/
  plans/   # design + impl plan
  deploy/  # deploy guides (aws.md is the canonical one)
odd/
  tasks/   # ODD feature task plans + closure evidence
scripts/
  aws/     # raw AWS CLI helpers + bootstrap scripts
.github/
  workflows/
    ci.yml      # lint + test on PRs
    deploy.yml  # deploy on push to main
```

## Quickstart (local dev)

```bash
# Backend
cd apps/api
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/reindex.py
.venv/bin/python -m uvicorn backend.main:app --reload

# Frontend
cd apps/web
npm install
PUBLIC_API_URL=http://localhost:8000 npm run dev
```

> Note: local dev works best on Python 3.11+. Python 3.9 requires a couple of workarounds for the PEP 604 union syntax used in the codebase (see `docs/deploy/aws.md` for details).

## Deployment

CI/CD via GitHub Actions (`.github/workflows/`):
- `ci.yml`: runs on every PR. Backend lint (ruff) + tests (pytest), frontend install + typecheck (astro check).
- `deploy.yml`: runs on push to `main`. Builds frontend, syncs to S3, invalidates CloudFront, deploys backend to EC2 via SSM, creates a release tag.

Full deployment guide: [docs/deploy/aws.md](docs/deploy/aws.md) (covers the full Free Tier setup, all the gotchas, and the IAM/thumbprint/policy rabbit holes we hit).

## Development process

This project uses **ODD (Organic Driven Development)**. Each non-trivial change goes through:
1. A task file in `odd/tasks/` with the spec, sub-tasks, and closure evidence
2. A PR (with CI green) for review
3. Merge to `main` triggers the deploy

See `odd/tasks/` for examples of the format.

## License

TBD
