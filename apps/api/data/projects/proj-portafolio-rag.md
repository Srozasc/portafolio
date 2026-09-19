---
slug: proj-portafolio-rag
title_es: Portafolio navegable por chatbot con RAG
title_en: Chatbot-navigable portfolio with RAG
year: 2025
role_es: Tech Lead / Senior Fullstack Engineer
role_en: Tech Lead / Senior Fullstack Engineer
client: Side project — open source
tags:
  - python
  - fastapi
  - typescript
  - astro
  - react
  - rag
  - chromadb
  - sse
  - i18n
  - senior
  - fullstack
stack_es:
  - Python 3.11 + FastAPI
  - ChromaDB (persistido en disco)
  - OpenAI text-embedding-3-small
  - LLM OpenAI-compatible (MiniMax o local)
  - Pydantic + pydantic-settings
  - TypeScript + Astro 4 (SSG con islands)
  - React 18 + react-markdown (chatbot island)
  - Server-Sent Events (streaming HTTP)
  - pnpm 11 + Vite
  - pytest (backend), Astro build (frontend)
stack_en:
  - Python 3.11 + FastAPI
  - ChromaDB (on-disk persistence)
  - OpenAI text-embedding-3-small
  - OpenAI-compatible LLM (MiniMax or local)
  - Pydantic + pydantic-settings
  - TypeScript + Astro 4 (SSG with islands)
  - React 18 + react-markdown (chatbot island)
  - Server-Sent Events (HTTP streaming)
  - pnpm 11 + Vite
  - pytest (backend), Astro build (frontend)
summary_es: "Portafolio bilingüe ES/EN navegable por chatbot con RAG. El visitante pregunta por stack y recibe prosa conversacional más cards clickeables a páginas de detalle pre-renderizadas."
summary_en: "Bilingual ES/EN portfolio navigable by a RAG-powered chatbot. Visitors ask by stack and get conversational prose plus clickable cards linking to pre-rendered detail pages."
impact_es:
  - "Bilingüe ES/EN completo desde build time, sin duplicación de contenido en runtime"
  - "Bot con RAG de 2 pasos: master index (5 entries) → colección de detalle por proyecto"
  - "Backend: 201 tests pytest pasando (fork de HiRag15k, sin regresión sobre el baseline)"
  - "Frontend: build estático, 8 páginas HTML, bundle JS inicial < 50 kB gzipped"
  - "Chatbot island con SSE streaming, retry on error y render XSS-safe vía react-markdown"
  - "Markdown + YAML frontmatter como single source of truth (Astro lee desde el path del backend)"
impact_en:
  - "Full ES/EN bilingual at build time, no runtime content duplication"
  - "Two-step RAG bot: master index (5 entries) → per-project detail collection"
  - "Backend: 201 pytest passing (HiRag15k fork, no regression over the baseline)"
  - "Frontend: static build, 8 HTML pages, initial JS bundle < 50 kB gzipped"
  - "Chatbot island with SSE streaming, retry on error, XSS-safe rendering via react-markdown"
  - "Markdown + YAML frontmatter as the single source of truth (Astro reads from the backend path)"
links:
  repo: null
  demo: null
  case_study: null
---

## Contexto

Quería un portafolio que no fuera la lista plana de proyectos que ya tiene
cualquier dev: quería que el visitante (en la práctica, un recruiter técnico)
pudiera filtrar por stack con lenguaje natural — *“¿qué hiciste con Python y
AWS?”* — y recibir una respuesta conversacional con cards clickeables que
llevan a páginas de detalle pre-renderizadas. El sitio es bilingüe ES/EN con
switcher, y el contenido vive como Markdown + YAML frontmatter en un único
directorio compartido entre el backend y el frontend. Es side-project
open-source que diseño y mantengo yo: cubre el ciclo completo desde el modelo
de datos hasta el deploy, y lo pensé para mostrar trabajo senior real (no
un clon de tutorial).

## Decisiones técnicas

El stack es Astro 4 para el sitio (SSG con islands) más FastAPI para el bot
(fork de HiRag15k), conectados por SSE. Astro pre-renderiza las páginas de
detalle al build, así que el sitio es HTML estático servido por Vercel y solo
embebe JS para el chatbot. El bot consume FastAPI en streaming y la
`<Chatbot />` island se hidrata con `client:idle` para no bloquear el primer
pintado. La elección de Astro sobre Next.js fue deliberada: la parte estática
del sitio es 95% del trabajo y Astro la hace gratis, mientras que el chatbot
es un solo componente React que no necesita SSR.

El RAG es de dos pasos: una colección `projects_index` con un chunk por
proyecto (título + summary + tags como metadata filtrable), y una colección
de detalle por proyecto (`projects_proj-<slug>`) con el body dividido en
chunks. El router clasifica la pregunta en `LIST_PROJECTS`, `DETAIL_PROJECT`
o `GENERAL` con heurísticas (keywords de stack, slug mencionado en el
history) en vez de pedirle al LLM que clasifique — ahorra una llamada por
turno y mantiene el routing testeable. El LLM emite prosa en chunks
incrementales más, al final, un bloque JSON con los slugs que el frontend
parsea para renderizar las cards.

El backend reusa el wrapper de ChromaDB de HiRag15k sin reescribirlo: el
servicio de proyectos hace delete-then-upsert de las dos colecciones
relacionadas, lo que da idempotencia. El frontend consume Markdown vía
react-markdown (XSS-safe por diseño, sin `dangerouslySetInnerHTML`), persiste
un `session_id` UUID en `sessionStorage` por tab, y capa el history a 6
turnos para que el prompt no se infle con conversaciones largas. La i18n
usa archivos JSON estáticos por locale, consumidos tanto por las páginas
Astro como por el island del chatbot vía props.

## Lecciones aprendidas

La primera sorpresa fue el tamaño del bundle del chatbot: react-markdown +
remark + unified pesan ~38 kB gzipped, que es razonable para un island
aislado pero se siente caro si lo sumás a otros islands en el futuro.
`client:idle` ayuda mucho: la página es interactiva antes de que el chat
termine de hidratar. La segunda lección es de prompt engineering: pedirle al
LLM que emita un bloque JSON al final de la prosa (con regex post-validación
que descarta slugs inválidos) es más robusto que pedirle que genere
directamente el formato de las cards — el modelo alucina menos cuando la
salida estructurada es un apéndice de la prosa, no el vehículo principal.

La tercera lección es operacional: el bot degrada en silencio si el vector
store queda vacío o el endpoint de embeddings cambia. Aprendí a surfacear
esos errores como eventos SSE `error` en vez de tirar 500, y a mostrar un
botón de retry en el frontend en vez de un mensaje críptico. Por último,
documentar el contrato del endpoint (`ProjectsChatRequest` y los tipos de
eventos SSE) en `apps/api/backend/api/schemas.py` ahorró horas cuando
llegué a implementar el consumer en React: tener los tipos como fuente
única de verdad es lo que hizo que el `parseEvent` del chatbot fuera
trivial de escribir y de testear.
