/**
 * types.ts — shared TypeScript types for the Biblioteca 3D standalone scene.
 *
 * Phase 5.5e (see odd/tasks/biblioteca-3d.md, T12). The Astro Content
 * Collection at apps/api/data/projects/ is the source of truth; we project
 * a wide `ProjectEntry` shape here and `catalog.ts` narrows it to the
 * `ProjectCatalogEntry` shape that the Three.js scene consumes.
 *
 * Mirrors apps/web/src/content/config.ts schema. Field names match the
 * `astro:content` projection used by apps/web/src/pages/biblioteca-3d.astro
 * (T13) for the `projectsForLibrary` array.
 */

export interface ProjectLinks {
  repo: string | null | undefined;
  demo: string | null | undefined;
  case_study: string | null | undefined;
}

/**
 * Wide projection of a project from the Content Collection. Includes every
 * field the standalone scene might render (title in both locales, summary,
 * stack in both locales, tags, role, links).
 */
export interface ProjectEntry {
  slug: string;
  title_es: string;
  title_en: string;
  summary_es: string;
  summary_en: string;
  year: number;
  role_es: string;
  role_en: string;
  client: string | null | undefined;
  tags: string[];
  stack_es: string[];
  stack_en: string[];
  impact_es: string[] | null | undefined;
  impact_en: string[] | null | undefined;
  links?: ProjectLinks;
}

/**
 * Narrow shape consumed by the Three.js scene (catalog.ts → main.ts).
 * Matches the PROJECTS_CATALOG shape the prototype used, except each
 * field is derived deterministically from a `ProjectEntry` via
 * `buildCatalog()` (see catalog.ts).
 */
export interface ProjectCatalogEntry {
  id: string;
  title: string;
  category: string;
  spineTitle: string;
  subtitle: string;
  description: string;
  stack: string[];
  /** Hex color as a Three.js-friendly integer (0xRRGGBB). */
  color: number;
  goldAccent: boolean;
  shelfIndex: number;
  slotIndex: number;
  link: string;
}
