/**
 * Scene3D.tsx — minimal Three.js scene for the Biblioteca 3D page.
 *
 * Phase 5.5d scope: a single dedicated route mounting a small interactive
 * scene built from Astro's Content Collection of projects. The component is
 * a pure presentation leaf:
 *   - NO data fetches at runtime (props come from the Astro page at build time).
 *   - NO persistence (no localStorage / sessionStorage / cookie / IndexedDB).
 *   - NO Chatbot import (the FAB arrives globally via Base.astro).
 *   - NO children (leaf component).
 *
 * Hard constraints from the slice brief:
 *   - Three.js / R3F / drei MUST only load on this route. The Astro page
 *     mounts us with `client:only="react"` so the libraries never enter the
 *     shared chunk graph for /, /proyectos/, /sobre-mi/, /en/*.
 *   - Empty `projects` -> graceful fallback block, never an empty <Canvas/>.
 *
 * Drei Text loads a default font lazily on first mount (network fetch via the
 * troika-three-text renderer). That's an asset fetch, not a project-data
 * fetch, and is independent of the Content Collection; it's outside the
 * "no runtime project fetches" rule.
 */
import { Canvas, type ThreeEvent } from '@react-three/fiber';
import { OrbitControls, Text, Float, Stars } from '@react-three/drei';
import { useCallback, type CSSProperties } from 'react';

export interface Scene3DProject {
  slug: string;
  title_es: string;
  title_en: string;
  year: number;
  tags: ReadonlyArray<string>;
}

export interface Scene3DProps {
  locale: 'es' | 'en';
  projects: ReadonlyArray<Scene3DProject>;
}

// Muted, low-saturation palette derived deterministically from the first tag.
// Five swatches — hash modulo five keeps the palette stable across renders
// without inventing colors at runtime.
const MUTED_COLORS = ['#8c6b5a', '#5a8c6b', '#5a6b8c', '#8c5a8c', '#8c8c5a'];

function tagColor(tag: string): string {
  let hash = 5381;
  for (let i = 0; i < tag.length; i++) {
    hash = ((hash << 5) + hash + tag.charCodeAt(i)) | 0;
  }
  return MUTED_COLORS[Math.abs(hash) % MUTED_COLORS.length];
}

function projectHref(locale: 'es' | 'en', slug: string): string {
  return locale === 'en'
    ? `/en/proyectos/${slug}/index.html`
    : `/proyectos/${slug}/index.html`;
}

interface BookCardProps {
  project: Scene3DProject;
  locale: 'es' | 'en';
  angle: number;
}

function BookCard({ project, locale, angle }: BookCardProps) {
  const radius = 4;
  const x = radius * Math.sin(angle);
  const z = -radius * Math.cos(angle);
  const color = tagColor(project.tags[0] ?? '');
  const title = locale === 'en' ? project.title_en : project.title_es;
  const href = projectHref(locale, project.slug);

  const handleClick = useCallback(
    (e: ThreeEvent<MouseEvent>) => {
      e.stopPropagation();
      if (typeof window !== 'undefined') {
        window.location.assign(href);
      }
    },
    [href],
  );

  return (
    <Float speed={1.4} rotationIntensity={0.18} floatIntensity={0.35}>
      <group position={[x, 0, z]} rotation={[0, angle, 0]}>
        <mesh onClick={handleClick}>
          <boxGeometry args={[1.2, 1.7, 0.2]} />
          <meshStandardMaterial color={color} roughness={0.75} metalness={0.05} />
        </mesh>
        <Text
          position={[0, 0.95, 0.11]}
          fontSize={0.18}
          color="#f5f5f5"
          anchorX="center"
          anchorY="middle"
          maxWidth={1.1}
          textAlign="center"
          outlineWidth={0.005}
          outlineColor="#1a1a1a"
        >
          {title}
        </Text>
        <Text
          position={[0, -0.95, 0.11]}
          fontSize={0.12}
          color="#cfcfcf"
          anchorX="center"
          anchorY="middle"
        >
          {String(project.year)}
        </Text>
      </group>
    </Float>
  );
}

export default function Scene3D({ locale, projects }: Scene3DProps) {
  const emptyStyle: CSSProperties = {
    padding: '2rem',
    textAlign: 'center',
    border: '1px dashed var(--border)',
    borderRadius: '0.5rem',
    color: 'var(--fg-muted)',
  };

  if (projects.length === 0) {
    return (
      <div data-testid="scene3d-empty" style={emptyStyle}>
        <p>No projects yet.</p>
        <p>
          <a href="/proyectos/index.html">Browse all projects</a>
        </p>
      </div>
    );
  }

  // Spread projects across ~120 degrees so the arc reads naturally on screen.
  const arcSpread = Math.PI * (2 / 3);
  const arcStart = -arcSpread / 2;
  const arcStep = arcSpread / Math.max(projects.length - 1, 1);

  return (
    <div
      data-testid="scene3d-canvas"
      style={{ width: '100%', height: '70vh', minHeight: '480px' }}
    >
      <Canvas
        camera={{ position: [0, 1.4, 7], fov: 45 }}
        gl={{ antialias: true, alpha: true }}
        dpr={[1, 2]}
      >
        <color attach="background" args={['#0f172a']} />
        <ambientLight intensity={0.55} />
        <directionalLight position={[3, 6, 3]} intensity={1.1} />
        <Stars radius={50} depth={30} count={1500} factor={3} fade speed={0.5} />

        {projects.map((project, i) => (
          <BookCard
            key={project.slug}
            project={project}
            locale={locale}
            angle={arcStart + arcStep * i}
          />
        ))}

        <OrbitControls
          enablePan={false}
          minDistance={4.5}
          maxDistance={11}
          target={[0, 0, 0]}
        />
      </Canvas>
    </div>
  );
}
