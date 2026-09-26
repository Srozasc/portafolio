# Chat tutorial — corregir copy del modal para reflejar el flujo real

## Contexto

El modal de tutorial del chat (`apps/web/src/components/Chatbot.tsx`, líneas ~1050-1200) muestra actualmente 3 steps que describen el flujo conversacional del bot:

1. "Abrí el chat" — "Tocá el botón azul abajo a la derecha…"
2. "Preguntá lo que quieras" — "Por stack (`python`, `aws`)…"
3. "Recibí prosa + reseñas" — "El editor devuelve una respuesta y, si hay match, una lista de proyectos…"

Pero el flujo real (implementado en el mismo archivo) es **tag-picker-first**:

1. Abrís el chat → aparece un welcome view con tags clickeables
2. Elegís uno o más stacks → el editor filtra los proyectos
3. (Opcional) Escribís una pregunta libre al bot para más detalle

El modal está mintiendo sobre el primer paso (dice "abrí el chat", cuando en realidad la primera acción del usuario es elegir tags). Hay que actualizar el copy para que el modal refleje el flujo verdadero.

## Alcance

**Cambia:**
- `apps/web/src/i18n/es.json` — bloque `home.tutorial`: 6 strings (`step1_title`, `step1_desc`, `step2_title`, `step2_desc`, `step3_title`, `step3_desc`)
- `apps/web/src/i18n/en.json` — bloque `home.tutorial`: 6 strings equivalentes
- `apps/web/src/components/Chatbot.tsx` — fallbacks hardcodeados de `tutorialCopy.step{1,2,3}Title` y `.step{1,2,3}Desc` (~líneas 1080-1110)

**No cambia:**
- Estructura JSX del modal (`chatbot-tutorial__steps` con 3 `<li>`)
- CSS del modal
- Estado `tutorialOpen` / `tutorialNoShow` / persistencia en localStorage
- El preview decorativo (sigue siendo `aria-hidden="true"`, sigue mostrando un ejemplo)
- El componente `WelcomeView` ni el flujo del tag picker

## Copy aprobado

### ES
| Key | Valor |
|---|---|
| `step1_title` | "Elegí tus áreas de interés" |
| `step1_desc` | "Cuando abras el chat, elegí una o más etiquetas con stacks (`python`, `aws`, `data`…). El editor filtra el portafolio por lo que te interesa." |
| `step2_title` | "Mirá los proyectos filtrados" |
| `step2_desc` | "El editor te muestra solo los proyectos que matchean con tus etiquetas. Hacé click en cualquiera para ver el detalle completo." |
| `step3_title` | "Preguntale al bot (opcional)" |
| `step3_desc` | "Si querés más contexto sobre un proyecto puntual, escribí tu pregunta abajo en el chat." |

### EN
| Key | Valor |
|---|---|
| `step1_title` | "Pick your areas of interest" |
| `step1_desc` | "When you open the chat, pick one or more tags with stacks (`python`, `aws`, `data`…). The editor filters the portfolio by what you care about." |
| `step2_title` | "See the filtered projects" |
| `step2_desc` | "The editor shows only the projects that match your tags. Click any to see the full detail." |
| `step3_title` | "Ask the bot (optional)" |
| `step3_desc` | "If you want more context on a specific project, type your question below in the chat." |

## Tasks

- [ ] **Task 1** — Actualizar bloque `home.tutorial` en `apps/web/src/i18n/es.json` y `apps/web/src/i18n/en.json` con los 12 strings aprobados.
- [ ] **Task 2** — Actualizar fallbacks hardcodeados en `apps/web/src/components/Chatbot.tsx` (`tutorialCopy` literal, ~líneas 1080-1110) para que coincidan con el nuevo copy.
- [ ] **Task 3** — Verificar: hard refresh en `localhost:4321/`, abrir DevTools y confirmar que el modal muestra los nuevos textos (`.chatbot-tutorial__stepTitle` y `.chatbot-tutorial__stepDesc`). Limpiar el archivo basura `nul` (untracked, dejado por `2>nul` en Windows). Commit work-unit.

## Convenciones

- Conventional commits en español, scope `tutorial` o `apps/web`
- Sin `Co-Authored-By`
- Mensaje atómico: refleja UNA unidad de cambio (corrección de copy)
- Si una task crece más de lo planificado, dividir antes de commitear