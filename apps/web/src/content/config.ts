import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

// Single source of truth for project content lives at apps/api/data/projects/.
// The FastAPI backend indexes the same files for the chatbot, and Astro
// reads them at build time via the Content Layer API.
//
// Path note: `base` is resolved relative to the Astro project root
// (apps/web/), so `../api/data/projects/` lands at apps/api/data/projects/
// in the monorepo. Do not use `./apps/api/data/projects/`.
const projects = defineCollection({
  loader: glob({ pattern: '**/*.md', base: '../api/data/projects/' }),
  schema: z.object({
    slug: z.string().regex(/^proj-[a-z0-9-]+$/, {
      message:
        'slug must match /^proj-[a-z0-9-]+$/ (lowercase, hyphenated, starts with proj-)',
    }),
    title_es: z.string().min(3),
    title_en: z.string().min(3),
    year: z.number().int().min(2000).max(2100),
    role_es: z.string(),
    role_en: z.string(),
    client: z.string().nullable().optional(),
    tags: z.array(z.string()).min(1),
    stack_es: z.array(z.string()).min(1),
    stack_en: z.array(z.string()).min(1),
    summary_es: z.string().min(20),
    summary_en: z.string().min(20),
    impact_es: z.array(z.string()).nullable().optional(),
    impact_en: z.array(z.string()).nullable().optional(),
    links: z
      .object({
        repo: z.string().url().nullable().optional(),
        demo: z.string().url().nullable().optional(),
        case_study: z.string().nullable().optional(),
      })
      .optional(),
  }),
});

export const collections = { projects };
