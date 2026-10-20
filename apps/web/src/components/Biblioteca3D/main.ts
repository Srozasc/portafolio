// @ts-nocheck
// The body of this module below the guard is the prototype's `<script>` body
// copied verbatim from experiments/chat-3d-library.html. It is plain ES2018
// browser JavaScript (Three.js r128 / OrbitControls / Tween.js are loaded from
// CDN as globals, not npm imports). `astro check` runs with
// astro/tsconfigs/strict, so type-checking ~1850 lines of un-annotated
// prototype JavaScript would emit hundreds of noImplicitAny diagnostics about
// code this slice deliberately does not rewrite. The TS-aware parts of the
// module (the JSON-tag read + buildCatalog() projection) are type-safe on
// their own; see catalog.ts and types.ts for those contracts.

/**
 * main.ts — Biblioteca 3D scene entry point. Three.js r128, OrbitControls
 * and Tween.js are loaded from CDN as `<script is:inline src=...>` blocks
 * BEFORE this module runs (see Biblioteca3DStandalone.astro). This file
 * declares them as globals rather than importing them.
 *
 * Phase 5.5e / T12.
 */

import { buildCatalog } from './catalog';
import type { ProjectEntry } from './types';

declare const THREE: any;
declare const TWEEN: any;

// 1. Read projects injected by the Astro component as a JSON tag.
const projectsTag = document.getElementById('biblioteca3d-projects');
const RAW: ProjectEntry[] = projectsTag
  ? JSON.parse(projectsTag.textContent || '[]')
  : [];

// 2. Derive the catalog via the deterministic buildCatalog() helper
//    (replaces the prototype's hardcoded array literal).
const PROJECTS_CATALOG = buildCatalog(RAW);

// 3. Once-per-page guard. Multiple instances or HMR will be no-ops.
if ((window as any).__BIBLIOTECA3D_INITIALIZED__) {
  // already initialized; do nothing on repeat module evaluation
} else {
  (window as any).__BIBLIOTECA3D_INITIALIZED__ = true;

  // ----- VERBATIM START -----
          /* =====================================================================
             Application Logic & Three.js 3D Library Implementation
             ===================================================================== */

          // Sound Synthesizer via Web Audio API (procedural audio without assets)
          const AudioFX = {
            ctx: null,
            init() {
              if (!this.ctx) {
                const AudioContext = window.AudioContext || window.webkitAudioContext;
                if (AudioContext) this.ctx = new AudioContext();
              }
            },
            playWhoosh() {
              try {
                this.init();
                if (!this.ctx) return;
                const osc = this.ctx.createOscillator();
                const gain = this.ctx.createGain();
                const filter = this.ctx.createBiquadFilter();

                osc.type = 'sine';
                osc.frequency.setValueAtTime(140, this.ctx.currentTime);
                osc.frequency.exponentialRampToValueAtTime(320, this.ctx.currentTime + 0.35);

                filter.type = 'lowpass';
                filter.frequency.setValueAtTime(400, this.ctx.currentTime);
                filter.frequency.exponentialRampToValueAtTime(1200, this.ctx.currentTime + 0.35);

                gain.gain.setValueAtTime(0.001, this.ctx.currentTime);
                gain.gain.linearRampToValueAtTime(0.12, this.ctx.currentTime + 0.1);
                gain.gain.exponentialRampToValueAtTime(0.001, this.ctx.currentTime + 0.45);

                osc.connect(filter);
                filter.connect(gain);
                gain.connect(this.ctx.destination);

                osc.start();
                osc.stop(this.ctx.currentTime + 0.45);
              } catch (e) {}
            },
            playSlide() {
              try {
                this.init();
                if (!this.ctx) return;
                const osc = this.ctx.createOscillator();
                const gain = this.ctx.createGain();
                osc.type = 'triangle';
                osc.frequency.setValueAtTime(260, this.ctx.currentTime);
                osc.frequency.exponentialRampToValueAtTime(180, this.ctx.currentTime + 0.25);
                gain.gain.setValueAtTime(0.08, this.ctx.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.001, this.ctx.currentTime + 0.25);
                osc.connect(gain);
                gain.connect(this.ctx.destination);
                osc.start();
                osc.stop(this.ctx.currentTime + 0.25);
              } catch (e) {}
            }
          };


          /* =====================================================================
             3D Environment Setup (Three.js)
             ===================================================================== */
          const canvas = document.getElementById('webgl-viewport');
          const scene = new THREE.Scene();
          scene.fog = new THREE.FogExp2(0xece6da, 0.012);

          const camera = new THREE.PerspectiveCamera(46, window.innerWidth / window.innerHeight, 0.1, 100);
          const initialCameraPos = new THREE.Vector3(0, 2.1, 6.2);
          const initialLookAt = new THREE.Vector3(0, 1.8, 0);
          camera.position.copy(initialCameraPos);

          const renderer = new THREE.WebGLRenderer({
            canvas,
            antialias: true,
            alpha: false,
            powerPreference: 'high-performance'
          });
          renderer.setSize(window.innerWidth, window.innerHeight);
          renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
          renderer.shadowMap.enabled = true;
          renderer.shadowMap.type = THREE.PCFSoftShadowMap;
          renderer.toneMapping = THREE.ACESFilmicToneMapping;
          renderer.toneMappingExposure = 1.05;

          const controls = new THREE.OrbitControls(camera, renderer.domElement);
          controls.enableDamping = true;
          controls.dampingFactor = 0.06;
          controls.enablePan = false; // Strictly prevent panning camera through walls
          controls.minDistance = 2.2;
          controls.maxDistance = 5.8; // Prevent zooming out into walls or void
          controls.minPolarAngle = Math.PI / 3.6; // Keep comfortable eye level (don't clip into ceiling)
          controls.maxPolarAngle = Math.PI / 2 - 0.08; // Don't penetrate parquet floor
          controls.minAzimuthAngle = -Math.PI / 2.4; // Bound rotation so camera stays facing the library
          controls.maxAzimuthAngle = Math.PI / 2.4;
          controls.target.copy(initialLookAt);

          /* =====================================================================
             Lighting Rig (Day & Night State Management + GTA City Neon)
             ===================================================================== */
          const LightingState = {
            isNight: false,
            // Lights references
            hemiLight: null,
            sunLight: null,
            moonLight: null,
            deskLampLight: null,
            deskLampLightLeft: null,
            lampBulbMaterials: [],
            lampShadeMaterials: [],
            candleLight1: null,
            candleLight2: null,
            candleLight3: null,
            cityNeonPinkLight: null,
            cityNeonCyanLight: null,
            cityNeonMaterials: [],
            cityWindowMaterials: [],
            cityBeacons: [],
            skyMeshDay: null,
            skyMeshNight: null,
            
            init() {
              // Hemisphere ambient fill
              this.hemiLight = new THREE.HemisphereLight(0xfff6e8, 0xd4c2a5, 0.85);
              this.hemiLight.position.set(0, 10, 0);
              scene.add(this.hemiLight);

              // Day Sun Beam (Directional)
              this.sunLight = new THREE.DirectionalLight(0xfffaed, 1.55);
              this.sunLight.position.set(-6, 8, 4);
              this.sunLight.castShadow = true;
              this.sunLight.shadow.mapSize.width = 2048;
              this.sunLight.shadow.mapSize.height = 2048;
              this.sunLight.shadow.camera.near = 0.5;
              this.sunLight.shadow.camera.far = 25;
              this.sunLight.shadow.camera.left = -6;
              this.sunLight.shadow.camera.right = 6;
              this.sunLight.shadow.camera.top = 6;
              this.sunLight.shadow.camera.bottom = -4;
              this.sunLight.shadow.bias = -0.0005;
              scene.add(this.sunLight);

              // Night Moonlight (Directional)
              this.moonLight = new THREE.DirectionalLight(0x6080b0, 0.0);
              this.moonLight.position.set(5, 7, 3);
              this.moonLight.castShadow = true;
              this.moonLight.shadow.bias = -0.0005;
              scene.add(this.moonLight);

              // Right Banker's Desk Lamp Warm Light
              this.deskLampLight = new THREE.PointLight(0xffa24c, 0.35, 5.5, 2);
              this.deskLampLight.position.set(1.35, 1.48, 1.66);
              this.deskLampLight.castShadow = true;
              this.deskLampLight.shadow.mapSize.width = 512;
              this.deskLampLight.shadow.mapSize.height = 512;
              this.deskLampLight.shadow.bias = -0.002;
              scene.add(this.deskLampLight);

              // Left Banker's Desk Lamp Warm Light (Previously missing mesh lamp)
              this.deskLampLightLeft = new THREE.PointLight(0xffa24c, 0.35, 5.5, 2);
              this.deskLampLightLeft.position.set(-1.35, 1.48, 1.66);
              this.deskLampLightLeft.castShadow = true;
              this.deskLampLightLeft.shadow.mapSize.width = 512;
              this.deskLampLightLeft.shadow.mapSize.height = 512;
              this.deskLampLightLeft.shadow.bias = -0.002;
              scene.add(this.deskLampLightLeft);

              // Keep candleLight3 reference synced to left lamp for compatibility
              this.candleLight3 = this.deskLampLightLeft;

              // Candles (Wall sconces)
              this.candleLight1 = new THREE.PointLight(0xff8833, 0.1, 4.5, 2);
              this.candleLight1.position.set(-2.8, 2.5, -0.4);
              scene.add(this.candleLight1);

              this.candleLight2 = new THREE.PointLight(0xff8833, 0.1, 4.5, 2);
              this.candleLight2.position.set(2.8, 2.5, -0.4);
              scene.add(this.candleLight2);

              // GTA Style City Neon Spill Lights (Cast colored glow into room through window)
              this.cityNeonPinkLight = new THREE.PointLight(0xff007f, 0.0, 16, 1.8);
              this.cityNeonPinkLight.position.set(-8.4, 4.2, 2.6);
              scene.add(this.cityNeonPinkLight);

              this.cityNeonCyanLight = new THREE.PointLight(0x00f0ff, 0.0, 14, 1.8);
              this.cityNeonCyanLight.position.set(-8.4, 5.4, 0.4);
              scene.add(this.cityNeonCyanLight);

              this.applyTheme(false, 0);
            },

            applyTheme(toNight, duration = 1200) {
              this.isNight = toNight;
              const targetExposure = toNight ? 1.3 : 1.05;
              const fogColor = toNight ? new THREE.Color(0x0a0c14) : new THREE.Color(0xece6da);
              const fogDensity = toNight ? 0.032 : 0.026;

              // Animate Fog & Scene background
              new TWEEN.Tween(scene.fog.color)
                .to(fogColor, duration)
                .easing(TWEEN.Easing.Quadratic.Out)
                .start();

              new TWEEN.Tween(scene.fog)
                .to({ density: fogDensity }, duration)
                .easing(TWEEN.Easing.Quadratic.Out)
                .start();

              // Animate Renderer Tone Mapping
              new TWEEN.Tween(renderer)
                .to({ toneMappingExposure: targetExposure }, duration)
                .easing(TWEEN.Easing.Quadratic.Out)
                .start();

              // Animate Daylight
              new TWEEN.Tween(this.sunLight)
                .to({ intensity: toNight ? 0.02 : 1.55 }, duration)
                .start();

              new TWEEN.Tween(this.hemiLight)
                .to({ intensity: toNight ? 0.15 : 0.85 }, duration)
                .start();

              // Animate Night Lamps
              new TWEEN.Tween(this.moonLight)
                .to({ intensity: toNight ? 0.45 : 0.0 }, duration)
                .start();

              new TWEEN.Tween(this.deskLampLight)
                .to({ intensity: toNight ? 2.5 : 0.35 }, duration)
                .start();

              new TWEEN.Tween(this.deskLampLightLeft)
                .to({ intensity: toNight ? 2.5 : 0.35 }, duration)
                .start();

              // Animate Banker's Lamps Glass & Bulb Glow
              this.lampBulbMaterials.forEach(bMat => {
                new TWEEN.Tween(bMat)
                  .to({ emissiveIntensity: toNight ? 2.2 : 0.6 }, duration)
                  .start();
              });

              this.lampShadeMaterials.forEach(sMat => {
                new TWEEN.Tween(sMat)
                  .to({ emissiveIntensity: toNight ? 0.75 : 0.08 }, duration)
                  .start();
              });

              new TWEEN.Tween(this.candleLight1)
                .to({ intensity: toNight ? 1.6 : 0.15 }, duration)
                .start();

              new TWEEN.Tween(this.candleLight2)
                .to({ intensity: toNight ? 1.6 : 0.15 }, duration)
                .start();

              // Animate GTA City Neon Illumination
              if (this.cityNeonPinkLight) {
                new TWEEN.Tween(this.cityNeonPinkLight)
                  .to({ intensity: toNight ? 2.2 : 0.0 }, duration)
                  .start();
              }

              if (this.cityNeonCyanLight) {
                new TWEEN.Tween(this.cityNeonCyanLight)
                  .to({ intensity: toNight ? 1.8 : 0.0 }, duration)
                  .start();
              }

              this.cityNeonMaterials.forEach(mat => {
                new TWEEN.Tween(mat)
                  .to({ emissiveIntensity: toNight ? 3.2 : 0.05 }, duration)
                  .start();
              });

              this.cityWindowMaterials.forEach(mat => {
                new TWEEN.Tween(mat)
                  .to({ emissiveIntensity: toNight ? 2.0 : 0.02 }, duration)
                  .start();
              });

              if (this.skyMeshDay && this.skyMeshNight) {
                new TWEEN.Tween(this.skyMeshDay.material)
                  .to({ opacity: toNight ? 0.0 : 1.0 }, duration)
                  .start();
                new TWEEN.Tween(this.skyMeshNight.material)
                  .to({ opacity: toNight ? 1.0 : 0.0 }, duration)
                  .start();
              }
            },

            updateFlicker(time) {
              if (!this.isNight) return;
              // Natural candle & lamp filaments subtle oscillation
              const flicker1 = Math.sin(time * 11) * 0.14 + Math.sin(time * 23) * 0.08;
              const flicker2 = Math.cos(time * 13) * 0.12 + Math.sin(time * 19) * 0.07;
              this.candleLight1.intensity = 1.6 + flicker1;
              this.candleLight2.intensity = 1.6 + flicker2;

              const lampFlickerR = Math.sin(time * 14) * 0.06;
              const lampFlickerL = Math.cos(time * 16) * 0.06;
              this.deskLampLight.intensity = 2.5 + lampFlickerR;
              this.deskLampLightLeft.intensity = 2.5 + lampFlickerL;

              // Skyscraper aircraft warning beacons rhythm
              const beaconBlink = Math.sin(time * 5.0) > 0.15 ? 3.0 : 0.05;
              this.cityBeacons.forEach(b => {
                b.material.emissiveIntensity = beaconBlink;
              });

              // Subtle electric neon buzz variation
              if (this.cityNeonPinkLight) {
                this.cityNeonPinkLight.intensity = 2.2 + (Math.sin(time * 16) * 0.12);
              }
            }
          };

          LightingState.init();

          /* =====================================================================
             Procedural Textures Generation (Canvas based, zero external assets)
             ===================================================================== */
          function createWoodTexture(isDark = false) {
            const c = document.createElement('canvas');
            c.width = 512;
            c.height = 512;
            const ctx = c.getContext('2d');

            const baseColor = isDark ? '#2e1d13' : '#73482d';
            const stripeColor = isDark ? '#22140c' : '#5a3721';

            ctx.fillStyle = baseColor;
            ctx.fillRect(0, 0, 512, 512);

            // Draw subtle grain
            for (let i = 0; i < 500; i++) {
              ctx.fillStyle = stripeColor;
              ctx.globalAlpha = 0.08 + Math.random() * 0.12;
              const y = Math.random() * 512;
              const h = 1 + Math.random() * 4;
              ctx.fillRect(0, y, 512, h);
            }
            ctx.globalAlpha = 1.0;

            const texture = new THREE.CanvasTexture(c);
            texture.wrapS = THREE.RepeatWrapping;
            texture.wrapT = THREE.RepeatWrapping;
            return texture;
          }

          function createFloorParquetTexture() {
            const c = document.createElement('canvas');
            c.width = 1024;
            c.height = 1024;
            const ctx = c.getContext('2d');

            ctx.fillStyle = '#41291b';
            ctx.fillRect(0, 0, 1024, 1024);

            // Herringbone pattern
            const tileSize = 64;
            for (let x = 0; x < 1024; x += tileSize) {
              for (let y = 0; y < 1024; y += tileSize) {
                const shade = ((x + y) % (tileSize * 2) === 0) ? '#4a3020' : '#392316';
                ctx.fillStyle = shade;
                ctx.fillRect(x + 2, y + 2, tileSize - 4, tileSize - 4);

                // Wood lines inside plank
                ctx.fillStyle = '#2b190f';
                ctx.globalAlpha = 0.18;
                ctx.fillRect(x + 4, y + 10, tileSize - 8, 3);
                ctx.fillRect(x + 4, y + 32, tileSize - 8, 3);
                ctx.globalAlpha = 1.0;
              }
            }

            const texture = new THREE.CanvasTexture(c);
            texture.wrapS = THREE.RepeatWrapping;
            texture.wrapT = THREE.RepeatWrapping;
            texture.repeat.set(4, 4);
            return texture;
          }

          /* GTA City Skyline & Neon Procedural Texture Generators */
          function createSkyTexture(isNight = false) {
            const c = document.createElement('canvas');
            c.width = 1024;
            c.height = 1024;
            const ctx = c.getContext('2d');

            const grad = ctx.createLinearGradient(0, 0, 0, 1024);
            if (!isNight) {
              // Crisp modern daylight sky with soft horizon haze
              grad.addColorStop(0, '#2269a8');
              grad.addColorStop(0.35, '#569ed3');
              grad.addColorStop(0.72, '#9eccf0');
              grad.addColorStop(1, '#deecf7');
              ctx.fillStyle = grad;
              ctx.fillRect(0, 0, 1024, 1024);

              // Sun disc and atmospheric dispersion
              const sunGlow = ctx.createRadialGradient(280, 220, 10, 280, 220, 360);
              sunGlow.addColorStop(0, 'rgba(255, 255, 245, 0.75)');
              sunGlow.addColorStop(0.4, 'rgba(255, 245, 210, 0.25)');
              sunGlow.addColorStop(1, 'rgba(255, 255, 255, 0)');
              ctx.fillStyle = sunGlow;
              ctx.fillRect(0, 0, 1024, 600);
            } else {
              // GTA Vice City / Cyberpunk Sunset & Midnight Neon Sky
              grad.addColorStop(0, '#090214');
              grad.addColorStop(0.28, '#1e0533');
              grad.addColorStop(0.6, '#560e4f');
              grad.addColorStop(0.82, '#991557');
              grad.addColorStop(0.95, '#e03a45');
              grad.addColorStop(1, '#ff6e26');
              ctx.fillStyle = grad;
              ctx.fillRect(0, 0, 1024, 1024);

              // Glowing city horizon ambient neon wash
              const neonHaze = ctx.createLinearGradient(0, 700, 0, 1024);
              neonHaze.addColorStop(0, 'rgba(255, 0, 128, 0)');
              neonHaze.addColorStop(0.5, 'rgba(255, 0, 128, 0.45)');
              neonHaze.addColorStop(1, 'rgba(0, 240, 255, 0.35)');
              ctx.fillStyle = neonHaze;
              ctx.fillRect(0, 700, 1024, 324);

              // Upper atmosphere starry dots
              ctx.fillStyle = '#ffffff';
              for (let i = 0; i < 110; i++) {
                const sx = Math.random() * 1024;
                const sy = Math.random() * 480;
                const sr = 0.5 + Math.random() * 1.5;
                ctx.globalAlpha = 0.25 + Math.random() * 0.75;
                ctx.beginPath();
                ctx.arc(sx, sy, sr, 0, Math.PI * 2);
                ctx.fill();
              }
              ctx.globalAlpha = 1.0;
            }

            return new THREE.CanvasTexture(c);
          }

          function createSkyscraperWindowTexture() {
            const c = document.createElement('canvas');
            c.width = 256;
            c.height = 512;
            const ctx = c.getContext('2d');

            // Modern dark facade background
            ctx.fillStyle = '#11151f';
            ctx.fillRect(0, 0, 256, 512);

            const cols = 8;
            const rows = 32;
            const cellW = 256 / cols;
            const cellH = 512 / rows;

            for (let x = 0; x < cols; x++) {
              for (let y = 0; y < rows; y++) {
                const rand = Math.random();
                if (rand > 0.45) {
                  ctx.fillStyle = rand > 0.75 ? '#2d3b4d' : '#1e2836';
                } else {
                  ctx.fillStyle = '#131922';
                }
                ctx.fillRect(x * cellW + 2, y * cellH + 2, cellW - 4, cellH - 4);
              }
            }

            const tex = new THREE.CanvasTexture(c);
            tex.wrapS = THREE.RepeatWrapping;
            tex.wrapT = THREE.RepeatWrapping;
            return tex;
          }

          function createSkyscraperEmissiveTexture() {
            const c = document.createElement('canvas');
            c.width = 256;
            c.height = 512;
            const ctx = c.getContext('2d');

            ctx.fillStyle = '#000000';
            ctx.fillRect(0, 0, 256, 512);

            const cols = 8;
            const rows = 32;
            const cellW = 256 / cols;
            const cellH = 512 / rows;

            // GTA Vibrant lit office window palette
            const colors = ['#ffe875', '#fff6c7', '#00f0ff', '#ff007f', '#ffffff'];

            for (let x = 0; x < cols; x++) {
              for (let y = 0; y < rows; y++) {
                if (Math.random() < 0.65) {
                  ctx.fillStyle = colors[Math.floor(Math.random() * colors.length)];
                  ctx.fillRect(x * cellW + 2, y * cellH + 2, cellW - 4, cellH - 4);
                }
              }
            }

            const tex = new THREE.CanvasTexture(c);
            tex.wrapS = THREE.RepeatWrapping;
            tex.wrapT = THREE.RepeatWrapping;
            return tex;
          }

          function createNeonBillboardCanvas(text, mainHex, accentHex) {
            const c = document.createElement('canvas');
            c.width = 512;
            c.height = 128;
            const ctx = c.getContext('2d');

            ctx.fillStyle = '#0a0c14';
            ctx.fillRect(0, 0, 512, 128);

            // Neon outline frame
            ctx.strokeStyle = mainHex;
            ctx.lineWidth = 6;
            ctx.strokeRect(10, 10, 492, 108);

            // Neon glowing typography
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.font = '900 48px "Cinzel", "Arial Black", sans-serif';
            ctx.fillStyle = '#ffffff';
            ctx.shadowColor = mainHex;
            ctx.shadowBlur = 18;
            ctx.fillText(text, 256, 62);

            // Accent underline
            ctx.fillStyle = accentHex;
            ctx.fillRect(80, 98, 352, 6);

            return new THREE.CanvasTexture(c);
          }

          // Spine Label Generator for Interactive Books
          function createBookSpineCanvas(title, spineColorHex, goldEmboss = true) {
            const c = document.createElement('canvas');
            c.width = 128;
            c.height = 512;
            const ctx = c.getContext('2d');

            // Leather background
            ctx.fillStyle = spineColorHex;
            ctx.fillRect(0, 0, 128, 512);

            // Spine edge shading
            const grad = ctx.createLinearGradient(0, 0, 128, 0);
            grad.addColorStop(0, 'rgba(0,0,0,0.5)');
            grad.addColorStop(0.2, 'rgba(0,0,0,0.05)');
            grad.addColorStop(0.8, 'rgba(255,255,255,0.08)');
            grad.addColorStop(1, 'rgba(0,0,0,0.55)');
            ctx.fillStyle = grad;
            ctx.fillRect(0, 0, 128, 512);

            // Gold ribs / borders
            const accent = goldEmboss ? '#e8c374' : '#d2d2d2';
            ctx.strokeStyle = accent;
            ctx.lineWidth = 4;

            // Decorative top and bottom stamps
            ctx.strokeRect(14, 20, 100, 24);
            ctx.strokeRect(14, 468, 100, 24);

            // Raised binding ribs
            [100, 200, 320, 420].forEach(y => {
              ctx.fillStyle = 'rgba(0,0,0,0.35)';
              ctx.fillRect(10, y, 108, 6);
              ctx.fillStyle = accent;
              ctx.fillRect(10, y - 2, 108, 3);
            });

            // Spine Title (Rotated vertical text)
            ctx.save();
            ctx.translate(64, 260);
            ctx.rotate(-Math.PI / 2);
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.font = 'bold 22px "Cinzel", serif';
            ctx.fillStyle = accent;
            ctx.shadowColor = 'rgba(0,0,0,0.6)';
            ctx.shadowBlur = 4;
            ctx.fillText(title, 0, 0);
            ctx.restore();

            return new THREE.CanvasTexture(c);
          }

          /* =====================================================================
             3D Architectural Mesh Builders
             ===================================================================== */
          const woodTexture = createWoodTexture();
          const darkWoodTexture = createWoodTexture(true);
          const floorTexture = createFloorParquetTexture();

          // Material definitions
          const woodMat = new THREE.MeshStandardMaterial({
            map: woodTexture,
            roughness: 0.65,
            metalness: 0.08
          });

          const darkWoodMat = new THREE.MeshStandardMaterial({
            map: darkWoodTexture,
            roughness: 0.55,
            metalness: 0.1
          });

          const floorMat = new THREE.MeshStandardMaterial({
            map: floorTexture,
            roughness: 0.38,
            metalness: 0.12
          });

          const brassMat = new THREE.MeshStandardMaterial({
            color: 0xd4af37,
            roughness: 0.3,
            metalness: 0.85
          });

          const greenGlassMat = new THREE.MeshStandardMaterial({
            color: 0x145a32,
            roughness: 0.15,
            metalness: 0.2,
            transparent: true,
            opacity: 0.88
          });

          const paperPagesMat = new THREE.MeshStandardMaterial({
            color: 0xf5eedb,
            roughness: 0.9,
            metalness: 0.02
          });

          // 1. Grand Enclosed Room Construction
          const roomGroup = new THREE.Group();

          // Floor (Spanning the room footprint: x: -8 to 8, z: -3.4 to 7)
          const floorGeo = new THREE.PlaneGeometry(16, 10.8);
          const floorMesh = new THREE.Mesh(floorGeo, floorMat);
          floorMesh.position.set(0, 0, 1.8);
          floorMesh.rotation.x = -Math.PI / 2;
          floorMesh.receiveShadow = true;
          roomGroup.add(floorMesh);

          // Wall Material
          const wallMat = new THREE.MeshStandardMaterial({
            color: 0xd9cebe,
            roughness: 0.85,
            metalness: 0.05
          });

          // Ceiling (Plaster paneling)
          const ceilingMat = new THREE.MeshStandardMaterial({
            color: 0xede4d8,
            roughness: 0.9,
            metalness: 0.02
          });
          const ceilingMesh = new THREE.Mesh(new THREE.PlaneGeometry(16, 10.8), ceilingMat);
          ceilingMesh.position.set(0, 8.5, 1.8);
          ceilingMesh.rotation.x = Math.PI / 2;
          roomGroup.add(ceilingMesh);

          // Back Wall (z = -3.2)
          const backWall = new THREE.Mesh(new THREE.BoxGeometry(16, 9, 0.6), wallMat);
          backWall.position.set(0, 4.25, -3.2);
          backWall.receiveShadow = true;
          roomGroup.add(backWall);

          // Front Wall (z = 6.8) - Encloses room so camera cannot see void behind it
          const frontWall = new THREE.Mesh(new THREE.BoxGeometry(16, 9, 0.6), wallMat);
          frontWall.position.set(0, 4.25, 6.8);
          frontWall.receiveShadow = true;
          roomGroup.add(frontWall);

          // Front Classical Archway / Double Door Molding
          const archFrame = new THREE.Mesh(new THREE.BoxGeometry(3.6, 5.2, 0.7), darkWoodMat);
          archFrame.position.set(0, 2.6, 6.6);
          roomGroup.add(archFrame);

          // Left Wall - Architectural Wall with Grand Panoramic Window Aperture
          // Back pillar (z: -3.2 to -0.8)
          const leftWallBack = new THREE.Mesh(new THREE.BoxGeometry(0.6, 9, 2.4), wallMat);
          leftWallBack.position.set(-7.8, 4.25, -2.0);
          leftWallBack.receiveShadow = true;
          roomGroup.add(leftWallBack);

          // Front pillar (z: 4.4 to 6.8)
          const leftWallFront = new THREE.Mesh(new THREE.BoxGeometry(0.6, 9, 2.4), wallMat);
          leftWallFront.position.set(-7.8, 4.25, 5.6);
          leftWallFront.receiveShadow = true;
          roomGroup.add(leftWallFront);

          // Bottom windowsill (y: 0 to 1.2, z: -0.8 to 4.4)
          const leftWallSill = new THREE.Mesh(new THREE.BoxGeometry(0.6, 1.2, 5.2), wallMat);
          leftWallSill.position.set(-7.8, 0.6, 1.8);
          leftWallSill.receiveShadow = true;
          roomGroup.add(leftWallSill);

          // Top arch header (y: 6.6 to 8.8, z: -0.8 to 4.4)
          const leftWallHeader = new THREE.Mesh(new THREE.BoxGeometry(0.6, 2.2, 5.2), wallMat);
          leftWallHeader.position.set(-7.8, 7.4, 1.8);
          leftWallHeader.receiveShadow = true;
          roomGroup.add(leftWallHeader);

          // Right Wall (x = 7.8, z: -3.2 to 6.8)
          const rightWall = new THREE.Mesh(new THREE.BoxGeometry(0.6, 9, 10.6), wallMat);
          rightWall.position.set(7.8, 4.25, 1.8);
          rightWall.receiveShadow = true;
          roomGroup.add(rightWall);

          // Wainscoting / Boiserie Baseboards (Rich wood trim around all walls)
          const boiserieBack = new THREE.Mesh(new THREE.BoxGeometry(16, 1.2, 0.15), darkWoodMat);
          boiserieBack.position.set(0, 0.6, -2.85);
          roomGroup.add(boiserieBack);

          const boiserieLeftBack = new THREE.Mesh(new THREE.BoxGeometry(0.15, 1.2, 2.4), darkWoodMat);
          boiserieLeftBack.position.set(-7.45, 0.6, -2.0);
          roomGroup.add(boiserieLeftBack);

          const boiserieLeftFront = new THREE.Mesh(new THREE.BoxGeometry(0.15, 1.2, 2.4), darkWoodMat);
          boiserieLeftFront.position.set(-7.45, 0.6, 5.6);
          roomGroup.add(boiserieLeftFront);

          const boiserieLeftSill = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.1, 5.2), darkWoodMat);
          boiserieLeftSill.position.set(-7.45, 1.2, 1.8);
          roomGroup.add(boiserieLeftSill);

          const boiserieRight = new THREE.Mesh(new THREE.BoxGeometry(0.15, 1.2, 10.4), darkWoodMat);
          boiserieRight.position.set(7.45, 0.6, 1.8);
          roomGroup.add(boiserieRight);

          const boiserieFront = new THREE.Mesh(new THREE.BoxGeometry(16, 1.2, 0.15), darkWoodMat);
          boiserieFront.position.set(0, 0.6, 6.45);
          roomGroup.add(boiserieFront);

          // Grand Panoramic Library Window (Frame + Mullions + Architectural Glass)
          const windowGroup = new THREE.Group();
          windowGroup.position.set(-7.75, 3.9, 1.8);

          // Window Casing Frame (Outer border)
          const frameMat = darkWoodMat;
          const winW = 5.2;
          const winH = 5.4;
          const frameThick = 0.14;

          const topBar = new THREE.Mesh(new THREE.BoxGeometry(frameThick * 2, frameThick, winW), frameMat);
          topBar.position.set(0, winH / 2, 0);
          windowGroup.add(topBar);

          const btmBar = new THREE.Mesh(new THREE.BoxGeometry(frameThick * 2, frameThick, winW), frameMat);
          btmBar.position.set(0, -winH / 2, 0);
          windowGroup.add(btmBar);

          const lSide = new THREE.Mesh(new THREE.BoxGeometry(frameThick * 2, winH, frameThick), frameMat);
          lSide.position.set(0, 0, -winW / 2);
          windowGroup.add(lSide);

          const rSide = new THREE.Mesh(new THREE.BoxGeometry(frameThick * 2, winH, frameThick), frameMat);
          rSide.position.set(0, 0, winW / 2);
          windowGroup.add(rSide);

          // 3 Vertical Mullions (Creating 4 vertical glass bays)
          [-winW / 4, 0, winW / 4].forEach(z => {
            const vMullion = new THREE.Mesh(new THREE.BoxGeometry(frameThick * 1.5, winH, 0.08), frameMat);
            vMullion.position.set(0, 0, z);
            windowGroup.add(vMullion);
          });

          // 2 Horizontal Transoms (Creating 3 vertical tiers)
          [-winH / 6, winH / 4].forEach(y => {
            const hTransom = new THREE.Mesh(new THREE.BoxGeometry(frameThick * 1.5, 0.08, winW), frameMat);
            hTransom.position.set(0, y, 0);
            windowGroup.add(hTransom);
          });

          // Transparent Architectural Glass Pane
          const glassMat = new THREE.MeshStandardMaterial({
            color: 0xd6eaff,
            roughness: 0.04,
            metalness: 0.12,
            transparent: true,
            opacity: 0.18,
            side: THREE.DoubleSide
          });
          const glassMesh = new THREE.Mesh(new THREE.PlaneGeometry(winH, winW), glassMat);
          glassMesh.rotation.y = Math.PI / 2;
          windowGroup.add(glassMesh);

          roomGroup.add(windowGroup);

          // Ceiling Beams spanning the room
          [-2, 0.4, 2.8, 5.2].forEach(z => {
            const beam = new THREE.Mesh(new THREE.BoxGeometry(16, 0.35, 0.4), darkWoodMat);
            beam.position.set(0, 8.35, z);
            beam.castShadow = true;
            roomGroup.add(beam);
          });

          scene.add(roomGroup);

          /* =====================================================================
             Modern Skyscraper Cityscape with GTA Style Neon Illumination
             ===================================================================== */
          function createSkyscraperCity() {
            const cityGroup = new THREE.Group();

            // 1. Panoramic Sky Backdrop (Day & GTA Neon Night Crossfade)
            const skyGeo = new THREE.PlaneGeometry(80, 60);

            const skyMatDay = new THREE.MeshBasicMaterial({
              map: createSkyTexture(false),
              transparent: true,
              opacity: 1.0,
              side: THREE.DoubleSide
            });
            const skyMeshDay = new THREE.Mesh(skyGeo, skyMatDay);
            skyMeshDay.position.set(-72, 16, 1.8);
            skyMeshDay.rotation.y = Math.PI / 2;
            cityGroup.add(skyMeshDay);
            LightingState.skyMeshDay = skyMeshDay;

            const skyMatNight = new THREE.MeshBasicMaterial({
              map: createSkyTexture(true),
              transparent: true,
              opacity: 0.0,
              side: THREE.DoubleSide
            });
            const skyMeshNight = new THREE.Mesh(skyGeo, skyMatNight);
            skyMeshNight.position.set(-71.8, 16, 1.8);
            skyMeshNight.rotation.y = Math.PI / 2;
            cityGroup.add(skyMeshNight);
            LightingState.skyMeshNight = skyMeshNight;

            // 2. Skyscraper Materials & Neon Palette
            const windowTex = createSkyscraperWindowTexture();
            const emissiveTex = createSkyscraperEmissiveTexture();

            const towerBuildingMat = new THREE.MeshStandardMaterial({
              map: windowTex,
              emissiveMap: emissiveTex,
              emissive: 0xffffff,
              emissiveIntensity: 0.02,
              roughness: 0.35,
              metalness: 0.45
            });
            LightingState.cityWindowMaterials.push(towerBuildingMat);

            // GTA Vibrant Neon Materials
            const neonColors = [
              { name: 'pink', hex: 0xff007f },
              { name: 'cyan', hex: 0x00f0ff },
              { name: 'purple', hex: 0x9d00ff },
              { name: 'lime', hex: 0x39ff14 },
              { name: 'gold', hex: 0xffaa00 }
            ];

            const neonMatMap = {};
            neonColors.forEach(item => {
              const nMat = new THREE.MeshStandardMaterial({
                color: item.hex,
                emissive: item.hex,
                emissiveIntensity: 0.05,
                roughness: 0.2,
                metalness: 0.1
              });
              neonMatMap[item.name] = nMat;
              LightingState.cityNeonMaterials.push(nMat);
            });

            // Aircraft Beacon Material (Blinking Red)
            const beaconMat = new THREE.MeshStandardMaterial({
              color: 0xff1122,
              emissive: 0xff1122,
              emissiveIntensity: 0.05,
              roughness: 0.1
            });
            LightingState.cityNeonMaterials.push(beaconMat);

            // 3. Cluster of Modern High-Rise Towers & Skyscrapers (pushed back for panoramic view)
            const buildingConfigs = [
              // Front foreground skyline (closest, framing window view)
              { x: -28, z: -1.0, w: 4.0, d: 4.5, h: 24, neon: 'pink', sign: 'VICE CITY' },
              { x: -30, z: 3.5,  w: 4.6, d: 4.0, h: 30, neon: 'cyan', sign: 'CYBER' },
              { x: -32, z: -4.5, w: 4.4, d: 4.4, h: 20, neon: 'lime' },
              { x: -31, z: 7.5,  w: 4.2, d: 4.2, h: 27, neon: 'purple', sign: 'NEON' },
              { x: -35, z: 1.2,  w: 5.4, d: 5.0, h: 38, neon: 'pink', hasSpire: true },
              { x: -36, z: -2.5, w: 4.2, d: 4.2, h: 32, neon: 'gold', sign: 'TITAN' },
              { x: -33, z: 5.5,  w: 4.8, d: 4.2, h: 23, neon: 'cyan' },

              // Second layer (mid-depth)
              { x: -38, z: -7.0, w: 5.5, d: 5.0, h: 28, neon: 'purple' },
              { x: -40, z: 9.5,  w: 5.8, d: 5.4, h: 34, neon: 'pink', hasSpire: true },
              { x: -42, z: 3.8,  w: 5.2, d: 5.2, h: 42, neon: 'cyan', hasSpire: true },
              { x: -41, z: -3.5, w: 4.8, d: 4.8, h: 36, neon: 'lime' },
              { x: -44, z: 0.0,  w: 6.0, d: 6.0, h: 48, neon: 'pink', hasSpire: true, sign: 'SYNTH 2027' },
              { x: -42, z: -9.0, w: 5.2, d: 4.6, h: 26, neon: 'gold' },
              { x: -45, z: 6.5,  w: 5.4, d: 4.8, h: 30, neon: 'cyan' },

              // Background density skyline (deepest layer)
              { x: -48, z: -6.0, w: 6.0, d: 6.0, h: 38, neon: 'purple' },
              { x: -50, z: 2.5,  w: 7.0, d: 6.0, h: 44, neon: 'pink' },
              { x: -52, z: 8.0,  w: 6.5, d: 5.5, h: 36, neon: 'cyan' },
              { x: -53, z: -11.0, w: 6.0, d: 6.0, h: 28, neon: 'lime' },
              { x: -53, z: 12.0, w: 6.5, d: 6.5, h: 32, neon: 'gold' },
              { x: -55, z: -2.0, w: 6.0, d: 6.0, h: 52, neon: 'cyan', hasSpire: true }
            ];

            buildingConfigs.forEach(b => {
              const towerGroup = new THREE.Group();
              towerGroup.position.set(b.x, b.h / 2 - 2, b.z);

              // Main Tower Shaft
              const mainTower = new THREE.Mesh(new THREE.BoxGeometry(b.w, b.h, b.d), towerBuildingMat);
              mainTower.castShadow = true;
              mainTower.receiveShadow = true;
              towerGroup.add(mainTower);

              // Rooftop Penthouse Setback
              const setbackH = 2.4;
              const setbackW = b.w * 0.72;
              const setbackD = b.d * 0.72;
              const setbackMesh = new THREE.Mesh(
                new THREE.BoxGeometry(setbackW, setbackH, setbackD),
                towerBuildingMat
              );
              setbackMesh.position.set(0, (b.h / 2) + (setbackH / 2), 0);
              towerGroup.add(setbackMesh);

              // GTA Style Glowing Neon Rooftop Perimeter Trim
              const nMat = neonMatMap[b.neon] || neonMatMap['pink'];
              const neonTrimW = setbackW + 0.15;
              const neonTrimD = setbackD + 0.15;
              const neonTrimThickness = 0.16;

              // Rooftop Glowing Frame
              const roofNeon = new THREE.Mesh(
                new THREE.BoxGeometry(neonTrimW, neonTrimThickness, neonTrimD),
                nMat
              );
              roofNeon.position.set(0, (b.h / 2) + setbackH + (neonTrimThickness / 2), 0);
              towerGroup.add(roofNeon);

              // Vertical Neon Corner Ribbons (GTA Vice City Aesthetic)
              const vBarH = b.h * 0.55;
              const vBar = new THREE.Mesh(
                new THREE.BoxGeometry(0.12, vBarH, 0.12),
                nMat
              );
              vBar.position.set(b.w / 2 + 0.05, (b.h / 4), b.d / 2 + 0.05);
              towerGroup.add(vBar);

              // Antenna Spire with Blinking Aviation Beacon
              if (b.hasSpire) {
                const spireH = 5.2;
                const spire = new THREE.Mesh(
                  new THREE.CylinderGeometry(0.04, 0.15, spireH, 6),
                  darkWoodMat
                );
                spire.position.set(0, (b.h / 2) + setbackH + (spireH / 2), 0);
                towerGroup.add(spire);

                const beacon = new THREE.Mesh(
                  new THREE.SphereGeometry(0.22, 8, 8),
                  beaconMat
                );
                beacon.position.set(0, (b.h / 2) + setbackH + spireH, 0);
                towerGroup.add(beacon);
                LightingState.cityBeacons.push(beacon);
              }

              // Glowing Neon Billboard Sign on Tower Facade
              if (b.sign) {
                const signTex = createNeonBillboardCanvas(b.sign, '#' + nMat.color.getHexString(), '#ffffff');
                const signMat = new THREE.MeshStandardMaterial({
                  map: signTex,
                  emissiveMap: signTex,
                  emissive: nMat.color,
                  emissiveIntensity: 0.05,
                  roughness: 0.1
                });
                LightingState.cityNeonMaterials.push(signMat);

                const signMesh = new THREE.Mesh(
                  new THREE.BoxGeometry(0.1, 1.8, 4.4),
                  signMat
                );
                // Face the sign toward library window (+X direction)
                signMesh.position.set(b.w / 2 + 0.08, (b.h / 2) - 3.2, 0);
                towerGroup.add(signMesh);
              }

              cityGroup.add(towerGroup);
            });

            // City Ground Plane (Dark asphalt with wet specular reflection)
            const cityGround = new THREE.Mesh(
              new THREE.PlaneGeometry(100, 80),
              new THREE.MeshStandardMaterial({ color: 0x0a0c10, roughness: 0.4, metalness: 0.3 })
            );
            cityGround.position.set(-40, -2, 1.8);
            cityGround.rotation.x = -Math.PI / 2;
            cityGroup.add(cityGround);

            scene.add(cityGroup);
          }

          createSkyscraperCity();

          // 2. Central Majestic Bookshelves
          function createBookshelf(x, z, rotY = 0) {
            const shelfGroup = new THREE.Group();
            shelfGroup.position.set(x, 0, z);
            shelfGroup.rotation.y = rotY;

            const shelfWidth = 5.2;
            const shelfHeight = 5.6;
            const shelfDepth = 0.75;
            const numTiers = 4;

            // Outer frame
            const frameGeoL = new THREE.BoxGeometry(0.12, shelfHeight, shelfDepth);
            const leftCol = new THREE.Mesh(frameGeoL, darkWoodMat);
            leftCol.position.set(-shelfWidth / 2, shelfHeight / 2, 0);
            leftCol.castShadow = true;
            leftCol.receiveShadow = true;
            shelfGroup.add(leftCol);

            const rightCol = new THREE.Mesh(frameGeoL, darkWoodMat);
            rightCol.position.set(shelfWidth / 2, shelfHeight / 2, 0);
            rightCol.castShadow = true;
            rightCol.receiveShadow = true;
            shelfGroup.add(rightCol);

            // Backboard
            const backMesh = new THREE.Mesh(new THREE.BoxGeometry(shelfWidth, shelfHeight, 0.08), woodMat);
            backMesh.position.set(0, shelfHeight / 2, -shelfDepth / 2 + 0.04);
            backMesh.receiveShadow = true;
            shelfGroup.add(backMesh);

            // Shelves levels
            const shelfPositionsY = [];
            const tierHeight = shelfHeight / (numTiers + 1);
            for (let i = 0; i <= numTiers + 1; i++) {
              const y = i * tierHeight;
              const plank = new THREE.Mesh(new THREE.BoxGeometry(shelfWidth, 0.08, shelfDepth), darkWoodMat);
              plank.position.set(0, y, 0);
              plank.castShadow = true;
              plank.receiveShadow = true;
              shelfGroup.add(plank);
              if (i > 0 && i <= numTiers) shelfPositionsY.push(y);
            }

            // Crown Cornice Molding on top
            const crown = new THREE.Mesh(new THREE.BoxGeometry(shelfWidth + 0.3, 0.25, shelfDepth + 0.2), darkWoodMat);
            crown.position.set(0, shelfHeight + 0.12, 0);
            crown.castShadow = true;
            shelfGroup.add(crown);

            scene.add(shelfGroup);
            return { group: shelfGroup, shelfY: shelfPositionsY };
          }

          const mainShelf = createBookshelf(0, -2.4, 0);

          // 3. Banker's Reading Desk in Forefront
          const deskGroup = new THREE.Group();
          deskGroup.position.set(0, 0, 1.6);

          const deskTop = new THREE.Mesh(new THREE.BoxGeometry(3.6, 0.12, 1.8), darkWoodMat);
          deskTop.position.set(0, 1.05, 0);
          deskTop.castShadow = true;
          deskTop.receiveShadow = true;
          deskGroup.add(deskTop);

          // Desk Legs
          [[-1.6, -0.7], [1.6, -0.7], [-1.6, 0.7], [1.6, 0.7]].forEach(([lx, lz]) => {
            const leg = new THREE.Mesh(new THREE.BoxGeometry(0.12, 1.05, 0.12), darkWoodMat);
            leg.position.set(lx, 1.05 / 2, lz);
            leg.castShadow = true;
            deskGroup.add(leg);
          });

          // Classical Emeralite / Banker's Lamp Builder
          function createBankersLamp(x, z, rotY = 0) {
            const lampGroup = new THREE.Group();
            lampGroup.position.set(x, 1.11, z); // Table top is at y = 1.05 + 0.12/2 = 1.11
            lampGroup.rotation.y = rotY;

            // 1. Ornate Stepped Heavy Brass Base
            const feltBottom = new THREE.Mesh(
              new THREE.CylinderGeometry(0.14, 0.14, 0.006, 24),
              new THREE.MeshStandardMaterial({ color: 0x1a2618, roughness: 0.9 })
            );
            feltBottom.position.y = 0.003;
            lampGroup.add(feltBottom);

            const baseTier1 = new THREE.Mesh(
              new THREE.CylinderGeometry(0.13, 0.14, 0.016, 24),
              brassMat
            );
            baseTier1.position.y = 0.014;
            baseTier1.castShadow = true;
            lampGroup.add(baseTier1);

            const baseTier2 = new THREE.Mesh(
              new THREE.CylinderGeometry(0.10, 0.118, 0.016, 24),
              brassMat
            );
            baseTier2.position.y = 0.030;
            baseTier2.castShadow = true;
            lampGroup.add(baseTier2);

            const baseCollar = new THREE.Mesh(
              new THREE.CylinderGeometry(0.04, 0.08, 0.024, 20),
              brassMat
            );
            baseCollar.position.y = 0.050;
            lampGroup.add(baseCollar);

            const baseBead = new THREE.Mesh(
              new THREE.TorusGeometry(0.042, 0.01, 10, 24),
              brassMat
            );
            baseBead.rotation.x = Math.PI / 2;
            baseBead.position.y = 0.062;
            lampGroup.add(baseBead);

            // 2. Fluted Brass Mast & Knuckle
            const lowerStem = new THREE.Mesh(
              new THREE.CylinderGeometry(0.018, 0.02, 0.16, 16),
              brassMat
            );
            lowerStem.position.y = 0.142;
            lowerStem.castShadow = true;
            lampGroup.add(lowerStem);

            const midKnuckle = new THREE.Mesh(
              new THREE.SphereGeometry(0.026, 16, 12),
              brassMat
            );
            midKnuckle.position.y = 0.222;
            lampGroup.add(midKnuckle);

            // Graceful Arched Gooseneck / Curved Brass Neck
            const neckCurve = new THREE.CatmullRomCurve3([
              new THREE.Vector3(0, 0.222, 0),
              new THREE.Vector3(0, 0.31, -0.015),
              new THREE.Vector3(0, 0.37, 0.02),
              new THREE.Vector3(0, 0.395, 0.05)
            ]);
            const neckGeo = new THREE.TubeGeometry(neckCurve, 16, 0.013, 12, false);
            const neckMesh = new THREE.Mesh(neckGeo, brassMat);
            neckMesh.castShadow = true;
            lampGroup.add(neckMesh);

            // Horizontal Swivel Crossbar supporting the shade
            const crossbar = new THREE.Mesh(
              new THREE.CylinderGeometry(0.01, 0.01, 0.36, 16),
              brassMat
            );
            crossbar.rotation.z = Math.PI / 2;
            crossbar.position.set(0, 0.395, 0.05);
            crossbar.castShadow = true;
            lampGroup.add(crossbar);

            // Acorn Finial End-caps & side mounting brackets
            [-0.185, 0.185].forEach(sideX => {
              const acorn = new THREE.Mesh(
                new THREE.SphereGeometry(0.018, 12, 10),
                brassMat
              );
              acorn.position.set(sideX, 0.395, 0.05);
              lampGroup.add(acorn);

              const bracket = new THREE.Mesh(
                new THREE.CylinderGeometry(0.008, 0.008, 0.038, 10),
                brassMat
              );
              bracket.position.set(sideX > 0 ? 0.17 : -0.17, 0.38, 0.05);
              lampGroup.add(bracket);

              const thumbScrew = new THREE.Mesh(
                new THREE.CylinderGeometry(0.015, 0.015, 0.012, 12),
                brassMat
              );
              thumbScrew.rotation.z = Math.PI / 2;
              thumbScrew.position.set(sideX > 0 ? 0.182 : -0.182, 0.375, 0.05);
              lampGroup.add(thumbScrew);
            });

            // 3. Swiveling Shade Assembly (tilted forward gracefully toward the desk)
            const shadePivot = new THREE.Group();
            shadePivot.position.set(0, 0.375, 0.05);
            shadePivot.rotation.x = 0.18; // ~10° forward tilt to showcase inner glow

            // Outer Iconic Emerald Green Glass Half-Cylinder
            const shadeMat = new THREE.MeshStandardMaterial({
              color: 0x0e582b,
              roughness: 0.15,
              metalness: 0.12,
              transparent: true,
              opacity: 0.93,
              emissive: 0x145a2b,
              emissiveIntensity: LightingState.isNight ? 0.75 : 0.08,
              side: THREE.DoubleSide
            });
            LightingState.lampShadeMaterials.push(shadeMat);

            // Half-cylinder arched canopy (radius ~0.076, length 0.33)
            const outerShadeGeo = new THREE.CylinderGeometry(0.075, 0.082, 0.33, 28, 1, false, 0, Math.PI);
            const outerShade = new THREE.Mesh(outerShadeGeo, shadeMat);
            outerShade.rotation.z = Math.PI / 2;
            outerShade.castShadow = true;
            shadePivot.add(outerShade);

            // Inner Opal/Milk-White Reflective Glass Casing (Emeralite cased glass)
            const innerShadeGeo = new THREE.CylinderGeometry(0.071, 0.078, 0.324, 24, 1, false, 0, Math.PI);
            const innerShadeMat = new THREE.MeshStandardMaterial({
              color: 0xfffaed,
              roughness: 0.28,
              metalness: 0.04,
              side: THREE.DoubleSide
            });
            const innerShade = new THREE.Mesh(innerShadeGeo, innerShadeMat);
            innerShade.rotation.z = Math.PI / 2;
            shadePivot.add(innerShade);

            // Fine Brass Rim Trim along the bottom edges of the shade
            [-0.079, 0.079].forEach(rz => {
              const rim = new THREE.Mesh(
                new THREE.BoxGeometry(0.334, 0.007, 0.007),
                brassMat
              );
              rim.position.set(0, 0, rz);
              shadePivot.add(rim);
            });

            // 4. Brass Bulb Socket & Filament Bulb inside
            const socket = new THREE.Mesh(
              new THREE.CylinderGeometry(0.018, 0.018, 0.05, 12),
              brassMat
            );
            socket.rotation.z = Math.PI / 2;
            socket.position.set(0, 0.03, 0);
            shadePivot.add(socket);

            // Glowing Incandescent Bulb
            const bulbMat = new THREE.MeshStandardMaterial({
              color: 0xfffae6,
              roughness: 0.2,
              metalness: 0.05,
              emissive: 0xffaa44,
              emissiveIntensity: LightingState.isNight ? 2.2 : 0.6
            });
            LightingState.lampBulbMaterials.push(bulbMat);

            const bulb = new THREE.Mesh(
              new THREE.SphereGeometry(0.032, 16, 12),
              bulbMat
            );
            bulb.scale.set(1.4, 0.8, 0.8);
            bulb.position.set(0, 0.015, 0);
            shadePivot.add(bulb);

            // 5. Vintage Beaded Brass Pull-Chain Switch
            const chain = new THREE.Mesh(
              new THREE.CylinderGeometry(0.0018, 0.0018, 0.11, 6),
              brassMat
            );
            chain.position.set(0.04, -0.05, 0);
            shadePivot.add(chain);

            const chainFob = new THREE.Mesh(
              new THREE.SphereGeometry(0.007, 10, 8),
              brassMat
            );
            chainFob.position.set(0.04, -0.11, 0);
            shadePivot.add(chainFob);

            lampGroup.add(shadePivot);
            return lampGroup;
          }

          // Spawn Symmetrical Classic Banker's Lamps on Left and Right of Desk
          const lampRight = createBankersLamp(1.35, 0.0, -0.04);
          deskGroup.add(lampRight);

          const lampLeft = createBankersLamp(-1.35, 0.0, 0.04);
          deskGroup.add(lampLeft);

          // Open Book Prop on Desk
          const propBookMat = new THREE.MeshStandardMaterial({ color: 0x541818, roughness: 0.7 });
          const deskBook = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.05, 0.38), propBookMat);
          deskBook.position.set(-0.8, 1.09, 0.1);
          deskBook.rotation.y = 0.25;
          deskBook.castShadow = true;
          deskGroup.add(deskBook);

          scene.add(deskGroup);

          /* =====================================================================
             Interactive 3D Books Generation & Placement
             ===================================================================== */
          const interactiveBooks = [];
          const interactiveMeshes = [];
          let activeFloatingBook = null;

          // Fill Shelves with Both Decorative and Interactive Project Books
          const shelfYLevels = mainShelf.shelfY; // Array of Y coordinates of shelves
          const shelfWidth = 4.8;

          // Build Project Interactive Books
          PROJECTS_CATALOG.forEach((proj, idx) => {
            const bookWidth = 0.11;
            const bookHeight = 0.65;
            const bookDepth = 0.44;

            // Book Spine Texture
            const hexColor = '#' + proj.color.toString(16).padStart(6, '0');
            const spineTexture = createBookSpineCanvas(proj.spineTitle, hexColor, proj.goldAccent);

            const coverMat = new THREE.MeshStandardMaterial({
              color: proj.color,
              roughness: 0.55,
              metalness: 0.15
            });

            const spineMat = new THREE.MeshStandardMaterial({
              map: spineTexture,
              roughness: 0.55,
              metalness: 0.15
            });

            // Box Materials: [right, left, top, bottom, front, back]
            // In Three.js: 0=x+, 1=x-, 2=y+, 3=y-, 4=z+, 5=z-
            // Facing out into the room (+Z is spine):
            const materials = [
              coverMat,       // x+
              coverMat,       // x-
              paperPagesMat,  // y+
              paperPagesMat,  // y-
              spineMat,       // z+ (Spine facing front)
              paperPagesMat   // z- (Pages inside)
            ];

            const bookGeo = new THREE.BoxGeometry(bookWidth, bookHeight, bookDepth);
            const bookMesh = new THREE.Mesh(bookGeo, materials);
            bookMesh.castShadow = true;
            bookMesh.receiveShadow = true;

            // Shelf Placement
            const targetShelfY = shelfYLevels[proj.shelfIndex || 0];
            const slotX = -1.8 + (proj.slotIndex * 0.45);
            const basePos = new THREE.Vector3(slotX, targetShelfY + (bookHeight / 2) + 0.04, -2.4 + (bookDepth / 2) - 0.1);
            const baseRot = new THREE.Euler(0, 0, (Math.random() - 0.5) * 0.02);

            bookMesh.position.copy(basePos);
            bookMesh.rotation.copy(baseRot);

            // Metadata on mesh
            const bookData = {
              mesh: bookMesh,
              project: proj,
              shelfPos: basePos.clone(),
              shelfRot: baseRot.clone(),
              isFloating: false
            };

            bookMesh.userData = bookData;
            interactiveBooks.push(bookData);
            interactiveMeshes.push(bookMesh);
            scene.add(bookMesh);
          });

          // Add Filler / Decorative Books on shelves to make library dense and rich
          const fillerColors = [0x2c3e50, 0x8b4513, 0x553018, 0x1f3a3d, 0x4a1525, 0x3d3d3d, 0x785128];
          for (let shelfIdx = 0; shelfIdx < shelfYLevels.length; shelfIdx++) {
            const y = shelfYLevels[shelfIdx];
            let currX = -2.2;
            while (currX < 2.2) {
              // Skip slot if close to interactive project book
              const nearInteractive = interactiveBooks.some(b => 
                Math.abs(b.shelfPos.x - currX) < 0.22 && Math.abs(b.shelfPos.y - (y + 0.3)) < 0.25
              );

              const bWidth = 0.06 + Math.random() * 0.06;
              const bHeight = 0.55 + Math.random() * 0.16;
              const bDepth = 0.38 + Math.random() * 0.06;

              if (!nearInteractive) {
                const col = fillerColors[Math.floor(Math.random() * fillerColors.length)];
                const fillMat = new THREE.MeshStandardMaterial({ color: col, roughness: 0.65 });
                const fillBook = new THREE.Mesh(
                  new THREE.BoxGeometry(bWidth, bHeight, bDepth),
                  [fillMat, fillMat, paperPagesMat, paperPagesMat, fillMat, paperPagesMat]
                );
                fillBook.position.set(currX, y + (bHeight / 2) + 0.04, -2.4 + (bDepth / 2) - 0.1);
                fillBook.rotation.z = (Math.random() - 0.5) * 0.04;
                fillBook.castShadow = true;
                scene.add(fillBook);
              }

              currX += bWidth + 0.02;
            }
          }

          /* =====================================================================
             Floating Book Animation Mechanics (Extraction & Return)
             ===================================================================== */
          const sheetEl = document.getElementById('project-sheet');

          window.setMobileSheetTab = function(tab) {
            const isMobile = window.innerWidth <= 860;
            const tabChat = document.getElementById('tab-chat');
            const tabSheet = document.getElementById('tab-sheet');

            if (tab === 'sheet') {
              if (!activeFloatingBook) {
                addBotResponse('Actualmente no hay ningún tomo extraído en la mesa. Tocá cualquier libro en el estante o elegí un tema en el chat para inspeccionarlo.');
                return;
              }
              document.body.classList.add('mobile-tab-sheet');
              if (tabSheet) tabSheet.classList.add('active');
              if (tabChat) tabChat.classList.remove('active');
            } else {
              document.body.classList.remove('mobile-tab-sheet');
              if (tabChat) tabChat.classList.add('active');
              if (tabSheet) tabSheet.classList.remove('active');
            }
          };

          function extractBook(bookData) {
            if (activeFloatingBook === bookData) return;
            if (activeFloatingBook) returnBook(activeFloatingBook);

            activeFloatingBook = bookData;
            bookData.isFloating = true;

            AudioFX.playSlide();

            // Temporarily constrain OrbitControls
            controls.autoRotate = false;

            // Compute target position in front of camera
            // On desktop: offset left to leave room for sheet. On mobile: center & raise to top 50%
            const forwardVec = new THREE.Vector3();
            camera.getWorldDirection(forwardVec);

            const isMobile = window.innerWidth <= 860;
            const forwardDist = isMobile ? 1.55 : 1.8;
            const targetPos = new THREE.Vector3()
              .copy(camera.position)
              .addScaledVector(forwardVec, forwardDist)
              .add(isMobile ? new THREE.Vector3(0, 0.28, 0) : new THREE.Vector3(-0.35, -0.05, 0));

            // Target orientation: book faces camera, tilted slightly in 3D perspective
            const targetRot = new THREE.Euler(
              camera.rotation.x + (isMobile ? 0.08 : 0.15),
              camera.rotation.y + (isMobile ? 0.22 : 0.35),
              camera.rotation.z - (isMobile ? 0.06 : 0.12)
            );

            // Animation Step 1: Slide out of shelf
            const pullOutPos = bookData.shelfPos.clone().add(new THREE.Vector3(0, 0.05, 0.65));

            new TWEEN.Tween(bookData.mesh.position)
              .to(pullOutPos, 350)
              .easing(TWEEN.Easing.Cubic.Out)
              .onComplete(() => {
                AudioFX.playWhoosh();
                // Step 2: Float up and glide to screen
                new TWEEN.Tween(bookData.mesh.position)
                  .to(targetPos, 850)
                  .easing(TWEEN.Easing.Back.Out)
                  .start();

                new TWEEN.Tween(bookData.mesh.rotation)
                  .to({ x: targetRot.x, y: targetRot.y, z: targetRot.z }, 850)
                  .easing(TWEEN.Easing.Back.Out)
                  .onComplete(() => {
                    // Open inspection card
                    displayProjectSheet(bookData.project);
                  })
                  .start();
              })
              .start();
          }

          function returnBook(bookData) {
            if (!bookData || !bookData.isFloating) return;

            hideProjectSheet();
            AudioFX.playSlide();

            const mesh = bookData.mesh;
            const pullOutPos = bookData.shelfPos.clone().add(new THREE.Vector3(0, 0.08, 0.65));

            // Step 1: Fly back near shelf
            new TWEEN.Tween(mesh.position)
              .to(pullOutPos, 700)
              .easing(TWEEN.Easing.Quadratic.InOut)
              .start();

            new TWEEN.Tween(mesh.rotation)
              .to({
                x: bookData.shelfRot.x,
                y: bookData.shelfRot.y,
                z: bookData.shelfRot.z
              }, 700)
              .easing(TWEEN.Easing.Quadratic.InOut)
              .onComplete(() => {
                // Step 2: Slide snug into shelf slot
                new TWEEN.Tween(mesh.position)
                  .to(bookData.shelfPos, 350)
                  .easing(TWEEN.Easing.Cubic.Out)
                  .onComplete(() => {
                    bookData.isFloating = false;
                    if (activeFloatingBook === bookData) activeFloatingBook = null;
                  })
                  .start();
              })
              .start();
          }

          function displayProjectSheet(proj) {
            document.getElementById('sheet-category').textContent = proj.category;
            document.getElementById('sheet-title').textContent = proj.title;
            document.getElementById('sheet-subtitle').textContent = proj.subtitle;
            document.getElementById('sheet-description').textContent = proj.description;
            
            const stackContainer = document.getElementById('sheet-stack');
            stackContainer.innerHTML = '';
            proj.stack.forEach(tech => {
              const tag = document.createElement('span');
              tag.className = 'stack-tag';
              tag.textContent = tech;
              stackContainer.appendChild(tag);
            });

            document.getElementById('sheet-action-link').href = proj.link;
            sheetEl.classList.add('active');

            const dot = document.getElementById('tab-dot');
            if (dot) dot.classList.add('active');

            if (window.innerWidth <= 860) {
              setMobileSheetTab('sheet');
            }
          }

          function hideProjectSheet() {
            sheetEl.classList.remove('active');

            const dot = document.getElementById('tab-dot');
            if (dot) dot.classList.remove('active');

            if (window.innerWidth <= 860) {
              setMobileSheetTab('chat');
            }
          }

          document.getElementById('sheet-return-btn').addEventListener('click', () => {
            if (activeFloatingBook) returnBook(activeFloatingBook);
          });

          /* =====================================================================
             Raycasting & Mouse Interaction (Click & Hover on Books)
             ===================================================================== */
          const raycaster = new THREE.Raycaster();
          const mouse = new THREE.Vector2();
          let hoveredBook = null;

          window.addEventListener('pointermove', (e) => {
            mouse.x = (e.clientX / window.innerWidth) * 2 - 1;
            mouse.y = -(e.clientY / window.innerHeight) * 2 + 1;

            raycaster.setFromCamera(mouse, camera);
            const intersects = raycaster.intersectObjects(interactiveMeshes);

            if (intersects.length > 0) {
              const hitMesh = intersects[0].object;
              if (hoveredBook !== hitMesh && (!hitMesh.userData.isFloating)) {
                hoveredBook = hitMesh;
                document.body.style.cursor = 'pointer';
              }
            } else {
              if (hoveredBook) {
                hoveredBook = null;
                document.body.style.cursor = 'default';
              }
            }
          });

          window.addEventListener('click', (e) => {
            // Ignore click if user clicked on UI overlay
            if (e.target.closest('.chat-dock') || e.target.closest('.project-inspection-sheet') || e.target.closest('.top-bar') || e.target.closest('.mobile-bottom-tabs')) {
              return;
            }

            raycaster.setFromCamera(mouse, camera);
            const intersects = raycaster.intersectObjects(interactiveMeshes);

            if (intersects.length > 0) {
              const hitBook = intersects[0].object.userData;
              extractBook(hitBook);
              addChatMessage('user', `Muéstrame el tomo de "${hitBook.project.title}"`);
              addBotResponse(`¡Excelente elección! Acabo de extraer del estante el volumen correspondiente a **${hitBook.project.title}**. Podés ver los detalles de arquitectura en la ficha.`);
            } else {
              // Clicked in empty room space: if a book is open and clicked far away, dismiss it
              if (activeFloatingBook && !e.target.closest('#project-sheet')) {
                returnBook(activeFloatingBook);
              }
            }
          });

          /* =====================================================================
             Chatbot Logic & Command Query Resolver
             ===================================================================== */
          const chatMessagesEl = document.getElementById('chat-messages');
          const chatFormEl = document.getElementById('chat-form');
          const chatInputEl = document.getElementById('chat-input');

          function addChatMessage(sender, text) {
            const msgDiv = document.createElement('div');
            msgDiv.className = `msg ${sender}`;
            msgDiv.innerHTML = text;
            chatMessagesEl.appendChild(msgDiv);
            chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
          }

          function addBotResponse(text, delay = 350) {
            // Show typing indicator
            const typingDiv = document.createElement('div');
            typingDiv.className = 'msg bot msg-typing';
            typingDiv.innerHTML = '<span></span><span></span><span></span>';
            chatMessagesEl.appendChild(typingDiv);
            chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;

            setTimeout(() => {
              typingDiv.remove();
              addChatMessage('bot', text);
            }, delay);
          }

          window.selectProjectFromChat = function(projId) {
            const bookData = interactiveBooks.find(b => b.project.id === projId);
            if (!bookData) return;

            // Extract selected book to front of camera
            extractBook(bookData);
            addChatMessage('user', `Ver tomo: "${bookData.project.title}"`);
            addBotResponse(`Extrayendo **${bookData.project.title}** hacia la mesa de lectura... Podés ver la arquitectura en la ficha.`);
          };

          function handleProjectQuery(query) {
            const q = query.toLowerCase().trim();
            const words = q.split(/\s+/).filter(w => w.length > 1);

            // Helper to evaluate project match against query string
            function matchScore(p) {
              const fullText = `${p.title} ${p.spineTitle} ${p.category} ${p.subtitle} ${p.description} ${p.stack.join(' ')}`.toLowerCase();
              
              // Exact full phrase
              if (fullText.includes(q)) return 2;

              // All individual words present
              if (words.length > 1 && words.every(w => fullText.includes(w))) return 1.5;

              // Any word present (for broad search)
              if (words.length > 1 && words.some(w => fullText.includes(w))) return 1;

              return 0;
            }

            // First try strict match (exact phrase or all words)
            let matches = PROJECTS_CATALOG.filter(p => matchScore(p) >= 1.5);

            // If no strict match, try broad match (at least 1 word)
            if (matches.length === 0 && words.length > 1) {
              matches = PROJECTS_CATALOG.filter(p => matchScore(p) >= 1);
            }

            // Fallback domain keyword mapping
            if (matches.length === 0) {
              if (q.includes('aws') || q.includes('cloud') || q.includes('serverless')) {
                matches = PROJECTS_CATALOG.filter(p => 
                  p.category.includes('CLOUD') || 
                  p.stack.some(s => s.toLowerCase().includes('aws') || s.toLowerCase().includes('serverless')) ||
                  p.description.toLowerCase().includes('aws') || p.description.toLowerCase().includes('serverless')
                );
              } else if (q.includes('python') || q.includes('data') || q.includes('lake')) {
                matches = PROJECTS_CATALOG.filter(p => 
                  p.category.includes('DATA') || 
                  p.stack.some(s => s.toLowerCase().includes('python') || s.toLowerCase().includes('duckdb'))
                );
              } else if (q.includes('ia') || q.includes('ai') || q.includes('agent') || q.includes('agente')) {
                matches = PROJECTS_CATALOG.filter(p => p.category.includes('ARTIFICIAL') || p.stack.includes('LLMs'));
              } else if (q.includes('iot') || q.includes('edge') || q.includes('raspberry') || q.includes('rust')) {
                matches = PROJECTS_CATALOG.filter(p => p.category.includes('IOT') || p.stack.includes('Rust'));
              } else if (q.includes('k8s') || q.includes('micro') || q.includes('docker') || q.includes('go')) {
                matches = PROJECTS_CATALOG.filter(p => p.category.includes('DEVOPS') || p.stack.includes('Kubernetes') || p.stack.includes('Docker'));
              } else if (q.includes('fintech') || q.includes('ledger') || q.includes('java')) {
                matches = PROJECTS_CATALOG.filter(p => p.category.includes('FINTECH') || p.stack.includes('Java 21'));
              }
            }

            if (matches.length === 0) {
              addBotResponse(`He revisado los estantes pero no encontré tomos para "${query}". Probá buscando por **AWS**, **Python**, **IA**, **IoT**, o hacé click directamente sobre cualquier lomo.`);
            } else if (matches.length === 1) {
              // Single match: directly extract and animate forward
              const matched = matches[0];
              const bookData = interactiveBooks.find(b => b.project.id === matched.id);
              if (bookData) {
                extractBook(bookData);
                addBotResponse(`Buscando en la estantería... Encontré el tomo de **${matched.title}** (${matched.category}). Flotando hacia la pantalla para su inspección.`);
              }
            } else {
              // Multiple matches: DO NOT bring any book forward yet until user selects one!
              let optionsHtml = `<div class="chat-project-options">`;
              matches.forEach(proj => {
                const hex = '#' + proj.color.toString(16).padStart(6, '0');
                const shortStack = proj.stack.slice(0, 3).join(', ');
                optionsHtml += `
                  <button class="chat-project-btn" onclick="window.selectProjectFromChat('${proj.id}')">
                    <span class="btn-spine-dot" style="background:${hex};"></span>
                    <div class="btn-info">
                      <span class="btn-title">${proj.title}</span>
                      <span class="btn-desc">${proj.category} &bull; ${shortStack}</span>
                    </div>
                    <span class="btn-arrow">&rarr;</span>
                  </button>
                `;
              });
              optionsHtml += `</div>`;

              addBotResponse(`Encontré **${matches.length} tomos** sobre ese tema. Seleccioná cuál querés inspeccionar para que se acerque a la mesa:${optionsHtml}`);
            }
          }

          chatFormEl.addEventListener('submit', (e) => {
            e.preventDefault();
            const val = chatInputEl.value.trim();
            if (!val) return;
            addChatMessage('user', val);
            chatInputEl.value = '';
            handleProjectQuery(val);
          });

          // Quick filter chips click handler
          document.querySelectorAll('.chip-btn').forEach(btn => {
            btn.addEventListener('click', () => {
              const query = btn.getAttribute('data-query');
              addChatMessage('user', query);
              handleProjectQuery(query);
            });
          });

          /* =====================================================================
             Day / Night Theme Controller & Camera Reset
             ===================================================================== */
          const themeToggleBtn = document.getElementById('theme-toggle');
          const themeIconEl = document.getElementById('theme-icon');
          const themeLabelEl = document.getElementById('theme-label');
          let isNightMode = false;

          themeToggleBtn.addEventListener('click', () => {
            isNightMode = !isNightMode;
            document.body.classList.toggle('night-mode', isNightMode);

            if (isNightMode) {
              themeIconEl.innerHTML = '&#9790;'; // Moon symbol
              themeLabelEl.textContent = 'Modo Día';
              LightingState.applyTheme(true);
            } else {
              themeIconEl.innerHTML = '&#9788;'; // Sun symbol
              themeLabelEl.textContent = 'Modo Noche';
              LightingState.applyTheme(false);
            }
          });

          document.getElementById('reset-cam-btn').addEventListener('click', () => {
            new TWEEN.Tween(camera.position)
              .to({ x: initialCameraPos.x, y: initialCameraPos.y, z: initialCameraPos.z }, 900)
              .easing(TWEEN.Easing.Cubic.Out)
              .start();

            new TWEEN.Tween(controls.target)
              .to({ x: initialLookAt.x, y: initialLookAt.y, z: initialLookAt.z }, 900)
              .easing(TWEEN.Easing.Cubic.Out)
              .start();
          });

          /* =====================================================================
             Window Resizing & Render Loop
             ===================================================================== */
          function handleWindowResize() {
            const isMobile = window.innerWidth <= 860;
            camera.aspect = window.innerWidth / window.innerHeight;
            camera.fov = isMobile ? 54 : 46;
            camera.updateProjectionMatrix();
            renderer.setSize(window.innerWidth, window.innerHeight);

            if (isMobile) {
              controls.target.set(0, 1.92, 0);
            } else {
              controls.target.set(0, 1.8, 0);
            }
          }
          window.addEventListener('resize', handleWindowResize);
          handleWindowResize();

          const clock = new THREE.Clock();

          function renderLoop() {
            requestAnimationFrame(renderLoop);
            const elapsedTime = clock.getElapsedTime();

            // Update Tween animations
            TWEEN.update();

            // Update Lighting flickers (candle effect at night)
            LightingState.updateFlicker(elapsedTime);

            // Subtle breathing floating motion on active floating book
            if (activeFloatingBook && activeFloatingBook.isFloating) {
              activeFloatingBook.mesh.position.y += Math.sin(elapsedTime * 2.2) * 0.0008;
              activeFloatingBook.mesh.rotation.z += Math.cos(elapsedTime * 1.8) * 0.0004;
            }

            controls.update();

            // Hard Boundary Guard: Mathematically prevent the camera from exiting the room
            camera.position.x = THREE.MathUtils.clamp(camera.position.x, -5.2, 5.2);
            camera.position.y = THREE.MathUtils.clamp(camera.position.y, 1.1, 4.2);
            camera.position.z = THREE.MathUtils.clamp(camera.position.z, -0.4, 5.7);

            renderer.render(scene, camera);
          }

          renderLoop();
  // ----- VERBATIM END -----
}
