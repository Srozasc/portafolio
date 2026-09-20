# Vercel Deploy (frontend)

The static Astro frontend in `apps/web/` deploys to Vercel. The backend
sits on a VPS behind a Cloudflare Tunnel — see
[`cloudflare-tunnel.md`](./cloudflare-tunnel.md) — and the frontend
talks to it through `PUBLIC_API_URL`.

> **Audience**: solo freelancer with a GitHub account and a Vercel
> account (free tier is enough for this project).

---

## 1. Connect the repo

1. Sign in to [vercel.com](https://vercel.com).
2. Click **Add New → Project**.
3. Import the `portafolio` GitHub repository.
4. Vercel auto-detects the project name from the repo. Leave the
   **Project Name** as-is (it becomes `<name>.vercel.app` for previews).

> Vercel will ask for permissions on first import — accept them for the
> repo (or just the `apps/web/` subdirectory if you prefer).

## 2. Project settings

Open the project's **Settings → General** and confirm:

| Setting | Value |
| --- | --- |
| **Root Directory** | `apps/web` |
| **Framework Preset** | `Other` |
| **Build Command** | `pnpm build` |
| **Output Directory** | `dist` |
| **Install Command** | `pnpm install` |

> `apps/web/vercel.json` in the repo pins the same values
> (`buildCommand`, `outputDirectory`, `installCommand`, `framework: null`).
> Vercel reads it automatically when present, but the dashboard values
> win if they disagree — keep them consistent.

**Node version**: Vercel auto-detects. If the build ever complains
about Node, pin it via the `engines` field in `apps/web/package.json`
or a `.nvmrc` in `apps/web/`.

## 3. Environment variable: `PUBLIC_API_URL`

The chatbot floating action button (FAB) reads
`import.meta.env.PUBLIC_API_URL` to know where to send chat requests
(see `apps/web/src/components/Chatbot.tsx`). Without this variable the
client falls back to `http://localhost:8000`, which is unreachable from
production.

In **Settings → Environment Variables**, add:

- **Name**: `PUBLIC_API_URL`
- **Value**: your Cloudflare Tunnel URL, e.g.
  `https://api.yourdomain.com` (from
  [`cloudflare-tunnel.md`](./cloudflare-tunnel.md) step 5).
- **Environments**: check **Production**, **Preview**, and
  **Development**.

The `PUBLIC_` prefix in Astro is required — only `PUBLIC_*` env vars are
exposed to client-side code. Anything without that prefix stays
server-side and won't reach the chatbot.

## 4. CORS

The backend (Phase 6 update) does two things automatically:

- **Vercel preview deployments** — every `*.vercel.app` hostname is
  allowed via a CORS regex, so PR previews can hit the backend without
  per-deploy config.
- **Local Astro preview** — `http://localhost:4321` and
  `http://127.0.0.1:4321` are listed in `CORS_ALLOW_ORIGINS` by default.

For a **production custom domain** (e.g. `yourdomain.com`), append it
to `CORS_ALLOW_ORIGINS` in `apps/api/.env` on the VPS and run
`bash scripts/deploy.sh`. The backend reads the env var on every
request, so no restart of `cloudflared` is needed — only the FastAPI
service reload.

## 5. Deploy

Hit **Deploy** in the Vercel dashboard for the first build, or just
push to the configured branch — by default Vercel deploys every push
to `main` as a Production deploy and every push to other branches as a
Preview deploy.

The repo's `dev` branch is the work branch for this project; if you
want `dev` to produce preview builds, configure that under
**Settings → Git → Production Branch** (or per-branch deploy
overrides).

## 6. Verify

Once the deploy finishes:

1. Open the Vercel-provided URL (`https://<name>.vercel.app` or your
   custom domain).
2. Confirm the landing page renders, the i18n switcher works, and the
   project pages load.
3. Open the chatbot FAB. Ask a question. The request should reach
   `https://api.yourdomain.com/api/chat/stream` and stream a real
   answer back.

## 7. Troubleshooting

### Chatbot FAB shows a network error

The most common cause is a missing or wrong `PUBLIC_API_URL`.

1. Vercel dashboard → **Settings → Environment Variables** —
   confirm `PUBLIC_API_URL` is set for the environment you're
   testing (Production / Preview / Development).
2. Re-deploy after changing env vars — Vercel does not rebuild
   automatically when env vars change.
3. From any browser or shell, hit the backend directly:
   `curl https://api.yourdomain.com/api/health` — confirm you get a
   JSON 200 response. If you don't, the issue is in the Cloudflare
   Tunnel, not Vercel.
4. Open the browser dev tools → **Network** tab → inspect the failing
   chat request. A CORS rejection surfaces as a request with no
   response payload and a console error like
   `Access to fetch ... has been blocked by CORS policy`. Fix it by
   adding the requesting origin to `CORS_ALLOW_ORIGINS`.

### Build fails: "could not detect package manager"

The repo uses `pnpm` via the workspace. Vercel needs to know that.

- Confirm `apps/web/pnpm-lock.yaml` is committed.
- Confirm `pnpm install` is set as the install command.
- If Vercel still tries `npm`, force it via `apps/web/vercel.json`
  (`"installCommand": "pnpm install"` is already set) and re-deploy.

### Build fails: missing dependencies or types

`pnpm astro check` in `apps/web/` should pass locally first
(see project README). If it fails only on Vercel, the cause is almost
always a missing `pnpm install` step or a Node version mismatch.

### Preview build can't reach the backend

Same regex-based CORS allowance covers all `*.vercel.app` hostnames
automatically. If a custom preview hostname is in use (e.g. a custom
preview domain), add it to `CORS_ALLOW_ORIGINS`.

## 8. Rollback

Vercel keeps every deploy. From the **Deployments** tab, click any
previous successful deploy → **Promote to Production** to roll back
instantly. No build is required.
