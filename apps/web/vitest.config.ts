import { defineConfig } from 'vitest/config';

/**
 * Vitest config for `apps/web`.
 *
 * - environment: jsdom — Three.js import paths validate under a browser-shaped
 *   global object. Scene3D.tsx avoids mounting `<Canvas>` when projects is
 *   empty so the empty-state test path never touches a real WebGL context.
 * - globals: false — every test imports `describe`, `it`, `expect` explicitly
 *   to keep the contract visible.
 * - setupFiles — pull in @testing-library/jest-dom's matcher extensions via
 *   the vitest entrypoint.
 */
export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: ['./vitest.setup.ts'],
    include: ['test/**/*.{test,spec}.{ts,tsx}'],
  },
});
