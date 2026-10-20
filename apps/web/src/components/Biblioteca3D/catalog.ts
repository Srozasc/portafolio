/**
 * catalog.ts — derive a `ProjectCatalogEntry[]` from real `ProjectEntry[]`
 * records read off the Astro Content Collection.
 *
 * Phase 5.5e (see odd/tasks/biblioteca-3d.md, T12 + L15). The HTML prototype
 * ships a hard-coded 7-entry PROJECTS_CATALOG; this file replaces it with
 * a deterministic transformer that maps N real projects into the same shape,
 * keeping the Three.js scene in `main.ts` untouched.
 *
 * Design choices captured in L15:
 *   - N ∈ [1, 7] projects: single shelf, slot-index spread across 8 slots.
 *   - 7 < N ≤ 14: two shelves, slot-index 0..7.
 *   - N > 14: warn on console.warn and use proportional shelfIndex/slotIndex.
 *   - Colors cycle through a 6-tone leather palette matching the prototype's
 *     binding aesthetics (terracotta, forest green, midnight navy, walnut,
 *     obsidian slate, burgundy crimson).
 */

import type { ProjectEntry, ProjectCatalogEntry } from './types';

/**
 * Leather binding palette matching the prototype (hex integers, 0xRRGGBB).
 * Cycling index ensures deterministic ordering by source array index.
 */
const LEATHER_PALETTE: readonly number[] = [
  0x8c2d19, // deep terracotta
  0x1b3b36, // forest green
  0x222a45, // midnight navy
  0x4a3424, // warm walnut
  0x1e272e, // obsidian slate
  0x5a1827, // burgundy crimson
];

const MAX_SHELF_SLOTS = 8;

/** "aws" -> "AWS", "api-gateway" -> "Api Gateway", "python" -> "Python". */
function titleCase(input: string): string {
  return input
    .split(/[-_\s]+/)
    .map((word) =>
      word === word.toUpperCase() && word.length > 1
        ? word // preserve "AWS", "API", etc.
        : word.charAt(0).toUpperCase() + word.slice(1).toLowerCase(),
    )
    .join(' ');
}

/**
 * Derive a short spineTitle from the first stack item, capped at three words,
 * uppercased. "Python 3.11 + FastAPI" -> "PYTHON 3.11".
 */
function deriveSpineTitle(stackFirst: string): string {
  const cleaned = stackFirst.replace(/[+&]/g, ' ').replace(/\s+/g, ' ').trim();
  const words = cleaned.split(' ').filter((w) => w.length > 0).slice(0, 3);
  return words.join(' ').toUpperCase();
}

/** First sentence of the summary. Splits on the first `. ` or full stop. */
function firstSentence(text: string): string {
  const idx = text.search(/\.\s/);
  if (idx === -1) return text;
  return text.slice(0, idx + 1);
}

/**
 * Allocate shelfIndex + slotIndex for `count` projects following the
 * prototype's slot layout (slotIndex ∈ 0..7, evenly distributed).
 */
function allocateSlots(count: number): { shelfIndex: number; slotIndex: number }[] {
  if (count <= 1) {
    return [{ shelfIndex: 0, slotIndex: 3 }];
  }

  if (count <= MAX_SHELF_SLOTS) {
    // Single shelf, spread evenly across MAX_SHELF_SLOTS possible positions.
    const lastIndex = MAX_SHELF_SLOTS; // 7 in the prototype
    return Array.from({ length: count }, (_, i) => ({
      shelfIndex: 0,
      slotIndex: Math.round((i * lastIndex) / Math.max(count - 1, 1)),
    }));
  }

  if (count <= 14) {
    const first = Math.min(count, 7);
    const firstRow = Array.from({ length: first }, (_, i) => ({
      shelfIndex: 0,
      slotIndex: Math.round((i * MAX_SHELF_SLOTS) / Math.max(first - 1, 1)),
    }));
    const secondCount = count - first;
    const secondRow = Array.from({ length: secondCount }, (_, i) => ({
      shelfIndex: 1,
      slotIndex: Math.round((i * MAX_SHELF_SLOTS) / Math.max(secondCount - 1, 1)),
    }));
    return [...firstRow, ...secondRow];
  }

  // count > 14: degrade to floor(i/7) shelves, slot = i % 7.
  console.warn(
    `[biblioteca-3d] too many projects (${count}) for the 3D library; ` +
      `expect shelf and slot collisions. Consider splitting into categories.`,
  );
  return Array.from({ length: count }, (_, i) => ({
    shelfIndex: Math.floor(i / MAX_SHELF_SLOTS),
    slotIndex: i % MAX_SHELF_SLOTS,
  }));
}

/**
 * Transform a list of Content Collection projects into the catalog shape
 * consumed by the Three.js scene in main.ts.
 */
export function buildCatalog(projects: readonly ProjectEntry[]): ProjectCatalogEntry[] {
  const slots = allocateSlots(projects.length);

  return projects.map((project, i) => {
    const firstTag = project.tags[0] ?? '';
    const firstStack = project.stack_es[0] ?? project.title_es;

    return {
      id: project.slug,
      title: project.title_es,
      category: titleCase(firstTag),
      spineTitle: deriveSpineTitle(firstStack),
      subtitle: firstSentence(project.summary_es),
      description: project.summary_es,
      stack: project.stack_es,
      color: LEATHER_PALETTE[i % LEATHER_PALETTE.length],
      goldAccent: true,
      shelfIndex: slots[i].shelfIndex,
      slotIndex: slots[i].slotIndex,
      link: project.links?.repo ?? 'https://github.com/Srozasc',
    };
  });
}
