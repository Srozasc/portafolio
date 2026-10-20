import { defineConfig } from 'vitest/config';

/**
 * Vitest config for `apps/web`.
 *
 * - environment: jsdom — keeps a browser-shaped global object for any
 *   component tests that touch `document` or `window` directly.
 * - globals: false — every test imports `describe`, `it`, `expect` explicitly
 *   to keep the contract visible.
 * - setupFiles — pull in @testing-library/jest-dom's matcher extensions via
 *   the vitest entrypoint.
 * - passWithNoTests: true — `apps/web/test/` is intentionally empty after the
 *   R3F `Scene3D.tsx` removal in 5dbf330-followup (T15). The replacement is
 *   the standalone Three.js scene at apps/web/src/components/Biblioteca3D/,
 *   which is mounted via CDN scripts and requires a real WebGL context that
 *   jsdom cannot provide. Manual smoke-testing against the prototype lives
 *   in the ODD doc T7 (verify route against experiments/chat-3d-library.html).
 *   Without this flag vitest exits 1 on an empty `include` glob.
 */
export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: ['./vitest.setup.ts'],
    include: ['test/**/*.{test,spec}.{ts,tsx}'],
    passWithNoTests: true,
  },
});
