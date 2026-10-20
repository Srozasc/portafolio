/**
 * Vitest setup — loads jest-dom matchers (`toBeInTheDocument`, etc.) for React
 * Testing Library assertions.
 *
 * Use the `/vitest` entrypoint of @testing-library/jest-dom rather than the
 * default one so the matcher registration targets vitest's expect, not jest's.
 */
import '@testing-library/jest-dom/vitest';
