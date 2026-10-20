import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import Scene3D from '../src/components/Scene3D';

/**
 * Scene3D smoke tests.
 *
 * We deliberately test ONLY the prop-driven shape (empty-state branch). We do
 * NOT mount a real `<Canvas>` because jsdom has no WebGL backing — importing
 * it would either crash or assertWebGL-context APIs that don't exist. The
 * non-empty branch is covered manually via `pnpm dev` → /biblioteca-3d.
 */

// RTL v16 no longer auto-detects vitest for cleanup — register it explicitly
// so each test starts from a fresh DOM. Without this, the second test in the
// suite sees the first test's <Scene3D> rendered markup still attached.
afterEach(() => {
  cleanup();
});

describe('Scene3D', () => {
  it('renders the empty-state block when projects is empty', () => {
    render(<Scene3D locale="es" projects={[]} />);
    expect(screen.getByTestId('scene3d-empty')).toBeInTheDocument();
    expect(screen.getByText(/no projects yet/i)).toBeInTheDocument();
  });

  it('renders the empty-state link pointing at /proyectos/index.html', () => {
    render(<Scene3D locale="es" projects={[]} />);
    const link = screen.getByRole('link', { name: /browse all projects/i });
    expect(link).toHaveAttribute('href', '/proyectos/index.html');
  });
});
