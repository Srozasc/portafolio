# Chat widget — rediseño visual bento (funcionalidad intacta)

## Contexto

El widget de chat actual (`apps/web/src/components/Chatbot.tsx` + `Chatbot.css`) está implementado como FAB azul + panel deslizante con look funcional pero genérico (radius 4-10px, hover sutil, sin personalidad).

Exploramos tres direcciones visuales experimentales en `experiments/`:
- `chat-editorial.html` (revista, descartado — muy editorial para un widget)
- `chat-dev-console.html` (IDE dark, descartado — overwhelma a reclutadores)
- `chat-bento-floating.html` (bento moderno, **elegido**)

El usuario aprobó el bento floating y pidió adaptarlo a la app real **sin modificar las funcionalidades existentes** (FAB, panel lateral, welcome view, filtered cards, retry, persistence, SSE handling, project_slug detection, View Transitions persistence).

**Decisiones de marca confirmadas con el usuario:**
- Mantener `--accent: #2563eb` (azul actual del sitio — no se migra a indigo)
- Incluir el modal de tutorial full-screen con persistencia en localStorage
- Tipografía: mantener `--font-sans` del sitio (no se agrega Space Grotesk en esta iteración)

## Alcance

**Cambia:**
- `apps/web/src/components/Chatbot.css` — rewrite visual manteniendo todos los classNames
- `apps/web/src/components/Chatbot.tsx` — agregar JSX + state + handlers para el modal de tutorial (estrictamente aditivo, lógica intacta)
- `apps/web/src/i18n/es.json` — agregar bloque `tutorial.*`
- `apps/web/src/i18n/en.json` — agregar bloque `tutorial.*`
- `apps/web/src/layouts/Base.astro` — agregar nuevas props `strings` para el tutorial

**No cambia:**
- `apps/web/src/styles/global.css` (no se toca el design system)
- Lógica de `Chatbot.tsx` (FAB, panel, welcome view, SSE, persistence, View Transitions)
- `astro.config.mjs`
- `apps/web/src/components/ProjectCard.astro`

## Tasks

- [ ] **Task 1** — Rewrite `Chatbot.css` con lenguaje visual bento (azul actual, classNames existentes, radius 16-24px, hover lift, FAB con pulse, panel slide-in cubic-bezier, project cards con border-radius generoso). Mantener todos los classNames que usa `.tsx`.
- [ ] **Task 2** — Agregar tutorial modal a `Chatbot.tsx`: JSX con backdrop + panel centrado, state `tutorialOpen` + `tutorialNoShow`, effect que lee localStorage en mount, handlers que persisten y cierran. Botón "Empezar a chatear" cierra el modal Y abre el panel del chat. No se cierra con backdrop ni ESC (intencional).
- [ ] **Task 3** — Agregar bloque `tutorial` con keys (`badge`, `title`, `sub`, `step1Title`, `step1Desc`, `step2Title`, `step2Desc`, `step3Title`, `step3Desc`, `noShow`, `startChat`) a `es.json` y `en.json`.
- [ ] **Task 4** — Pasar las nuevas strings del tutorial desde `Base.astro` al componente `<Chatbot>` (extender el prop `strings` sin tocar las existentes).
- [ ] **Task 5** — Verificar: `pnpm install` si hace falta, `pnpm build` para chequear tipos y SSR, levantar `pnpm dev` y validar comportamiento del widget + tutorial.

## Convenciones

- Cada task cierra con un work-unit commit en feature branch
- Mensajes de commit en Conventional Commits (español, scope `apps/web` cuando aplique)
- Sin cambios fuera del scope declarado
- Si una task crece más de lo planificado, dividir antes de commitear