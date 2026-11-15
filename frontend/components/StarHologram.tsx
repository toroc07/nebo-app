"use client";
// The wall tablet of the observation room shows the object being observed as a slowly spinning
// 3D model. It is an artist's impression built from the object's type and temperature (colour,
// size, bands, disk, companion), not SPHEREx data, and the caption says so.
import { Canvas, useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import type { Target } from "@/lib/api";
import s from "./starHologram.module.css";

type Look = {
  label: string;
  deep: string; // colour of the dim cells / bands
  hot: string; // colour of the bright cells
  glow: string;
  radius: number;
  cells: number; // granulation scale
  bands: number; // 0 = granulation only; > 0 = latitude bands (brown dwarfs)
  limb: number; // limb darkening exponent
  emit: number;
  halo: number; // strength of the glow around the body
  disk?: string; // colour of a dusty disk (young star)
  companion?: { deep: string; hot: string }; // second brown dwarf
  pulse?: boolean; // Mira pulsation
};

// Colours follow each object's temperature: a ~3200 K red dwarf looks orange, a T dwarf
// magenta (sodium and potassium absorb the green), a 250 K Y dwarf barely glows at all.
const LOOKS: Record<string, Look> = {
  "barnards-star": {
    label: "Red dwarf · M4 · ~3200 K",
    deep: "#d9773e",
    hot: "#ffd2a8",
    glow: "#ffae78",
    radius: 0.85,
    cells: 5,
    bands: 0,
    limb: 0.55,
    emit: 1.05,
    halo: 0.55,
  },
  "eps-indi-b": {
    label: "Brown dwarf pair · T1 + T6 · ~1300 / 900 K",
    deep: "#2a0c1a",
    hot: "#a8406a",
    glow: "#8a2a50",
    radius: 0.8,
    cells: 3,
    bands: 14,
    limb: 0.8,
    emit: 1,
    halo: 0.6,
    companion: { deep: "#1a0812", hot: "#6e2448" },
  },
  "wise-0855": {
    label: "Coldest brown dwarf · Y · ~250 K",
    deep: "#0d0a10",
    hot: "#43383a",
    glow: "#2a1a20",
    radius: 0.9,
    cells: 2.5,
    bands: 10,
    limb: 0.9,
    emit: 1,
    halo: 0.25,
  },
  "rw-aurigae": {
    label: "Young star with a disk · K · ~4500 K",
    deep: "#e2a466",
    hot: "#fff2de",
    glow: "#ffd9a8",
    radius: 0.7,
    cells: 6,
    bands: 0,
    limb: 0.45,
    emit: 1.25,
    halo: 1,
    disk: "#c98a52",
  },
  "r-draconis": {
    label: "Pulsating red giant · Mira · ~2600 K",
    deep: "#8a2408",
    hot: "#ffa060",
    glow: "#ff7a3a",
    radius: 1.1,
    cells: 2.2,
    bands: 0,
    limb: 0.5,
    emit: 1.15,
    halo: 1,
    pulse: true,
  },
};

function lookFor(target: Target | null): Look | null {
  if (!target) return null;
  if (LOOKS[target.slug]) return LOOKS[target.slug];
  if (target.kind.includes("brown_dwarf")) return LOOKS["wise-0855"];
  if (target.kind.includes("variable")) return LOOKS["r-draconis"];
  return LOOKS["barnards-star"];
}

const vertex = /* glsl */ `
  varying vec3 vPos;
  varying vec3 vNormal;
  varying vec3 vView;
  void main() {
    vPos = position;
    vNormal = normalize(normalMatrix * normal);
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vView = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv;
  }
`;

// Surface: fractal noise fixed to the body (so the spin shows it), optional latitude bands,
// limb darkening towards the edge.
const surface = /* glsl */ `
  uniform vec3 uDeep;
  uniform vec3 uHot;
  uniform float uCells;
  uniform float uBands;
  uniform float uLimb;
  uniform float uEmit;
  uniform float uTime;
  varying vec3 vPos;
  varying vec3 vNormal;
  varying vec3 vView;
  float hash(vec3 p) {
    p = fract(p * 0.3183099 + 0.1);
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
  }
  float noise(vec3 x) {
    vec3 i = floor(x);
    vec3 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return mix(
      mix(mix(hash(i), hash(i + vec3(1, 0, 0)), f.x),
          mix(hash(i + vec3(0, 1, 0)), hash(i + vec3(1, 1, 0)), f.x), f.y),
      mix(mix(hash(i + vec3(0, 0, 1)), hash(i + vec3(1, 0, 1)), f.x),
          mix(hash(i + vec3(0, 1, 1)), hash(i + vec3(1, 1, 1)), f.x), f.y), f.z);
  }
  float fbm(vec3 p) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 5; i++) {
      v += a * noise(p);
      p *= 2.03;
      a *= 0.5;
    }
    return v;
  }
  void main() {
    vec3 p = normalize(vPos);
    float n = fbm(p * uCells + vec3(0.0, uTime * 0.04, 0.0));
    float pattern = n;
    if (uBands > 0.0) {
      float bands = sin(p.y * uBands + n * 4.0) * 0.5 + 0.5;
      pattern = mix(n, bands, 0.65);
    }
    float mu = clamp(dot(vNormal, vView), 0.0, 1.0);
    vec3 col = mix(uDeep, uHot, smoothstep(0.25, 0.8, pattern));
    col *= mix(0.25, 1.0, pow(mu, uLimb)) * uEmit;
    gl_FragColor = vec4(col, 1.0);
  }
`;

// Halo: a slightly larger back-facing shell that brightens towards the rim.
const halo = /* glsl */ `
  uniform vec3 uGlow;
  uniform float uStrength;
  varying vec3 vNormal;
  varying vec3 vView;
  void main() {
    float rim = pow(clamp(0.72 - dot(vNormal, vView), 0.0, 1.0), 2.2);
    gl_FragColor = vec4(uGlow, rim * uStrength);
  }
`;

// Disk: brighter near the star, fading outwards, with faint rings.
const diskShader = /* glsl */ `
  uniform vec3 uGlow;
  varying vec3 vPos;
  void main() {
    float r = length(vPos.xy);
    float t = smoothstep(2.6, 1.3, r) * smoothstep(1.2, 1.35, r);
    float rings = 0.75 + 0.25 * sin(r * 22.0);
    gl_FragColor = vec4(uGlow, t * rings * 0.7);
  }
`;

function Body({
  deep,
  hot,
  look,
  radius,
}: {
  deep: string;
  hot: string;
  look: Look;
  radius: number;
}) {
  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: vertex,
        fragmentShader: surface,
        uniforms: {
          uDeep: { value: new THREE.Color(deep) },
          uHot: { value: new THREE.Color(hot) },
          uCells: { value: look.cells },
          uBands: { value: look.bands },
          uLimb: { value: look.limb },
          uEmit: { value: look.emit },
          uTime: { value: 0 },
        },
      }),
    [deep, hot, look],
  );
  const glow = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: vertex,
        fragmentShader: halo,
        uniforms: {
          uGlow: { value: new THREE.Color(look.glow) },
          uStrength: { value: look.halo },
        },
        side: THREE.BackSide,
        blending: THREE.AdditiveBlending,
        transparent: true,
        depthWrite: false,
      }),
    [look],
  );
  useEffect(
    () => () => {
      material.dispose();
      glow.dispose();
    },
    [material, glow],
  );
  useFrame((_, dt) => {
    material.uniforms.uTime.value += dt;
  });
  return (
    <group>
      <mesh material={material}>
        <sphereGeometry args={[radius, 64, 48]} />
      </mesh>
      <mesh material={glow} scale={1.28}>
        <sphereGeometry args={[radius, 48, 32]} />
      </mesh>
    </group>
  );
}

function Model({ look, spin }: { look: Look; spin: boolean }) {
  const body = useRef<THREE.Group>(null);
  const orbit = useRef<THREE.Group>(null);
  const time = useRef(0);
  const disk = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: vertex,
        fragmentShader: diskShader,
        uniforms: { uGlow: { value: new THREE.Color(look.disk ?? look.glow) } },
        side: THREE.DoubleSide,
        blending: THREE.AdditiveBlending,
        transparent: true,
        depthWrite: false,
      }),
    [look],
  );
  useEffect(() => () => disk.dispose(), [disk]);
  useFrame((_, dt) => {
    if (!spin) return;
    time.current += dt;
    // Spin on the object's own axis, tilted a little towards the viewer.
    if (body.current) body.current.rotation.y += dt * 0.45;
    if (orbit.current) orbit.current.rotation.y += dt * 0.6;
    if (look.pulse && body.current)
      body.current.scale.setScalar(1 + 0.05 * Math.sin(time.current * 1.4));
  });
  const radius = look.companion ? look.radius * 0.8 : look.radius;
  return (
    <group rotation={[0.35, 0, 0.25]}>
      <group ref={body}>
        <Body deep={look.deep} hot={look.hot} look={look} radius={radius} />
      </group>
      {look.disk && (
        <mesh material={disk} rotation={[Math.PI / 2, 0, 0]}>
          <ringGeometry args={[1.2, 2.6, 96, 1]} />
        </mesh>
      )}
      {look.companion && (
        <group ref={orbit}>
          <group position={[1.35, 0.1, 0]}>
            <Body
              deep={look.companion.deep}
              hot={look.companion.hot}
              look={look}
              radius={look.radius * 0.5}
            />
          </group>
        </group>
      )}
    </group>
  );
}

/** The original screen: a wireframe globe, for fields that are not a catalogued object. */
function Wireframe({ spin }: { spin: boolean }) {
  const ref = useRef<THREE.Mesh>(null);
  useFrame((_, dt) => {
    if (spin && ref.current) ref.current.rotation.y += dt * 0.3;
  });
  return (
    <mesh ref={ref} rotation={[0.35, 0, 0.25]}>
      <sphereGeometry args={[1, 18, 12]} />
      <meshBasicMaterial color="#3fd2ff" wireframe transparent opacity={0.8} />
    </mesh>
  );
}

export default function StarHologram({
  target,
  reduced,
}: {
  target: Target | null;
  reduced: boolean;
}) {
  const [supported, setSupported] = useState(false);
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl2") ?? c.getContext("webgl");
    setSupported(!!gl);
    gl?.getExtension("WEBGL_lose_context")?.loseContext();
    const onVisibility = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);
  const look = lookFor(target);
  // The tablet is small: one short visible line; the full description is for screen readers.
  const caption = target ? target.name : "Custom field";
  const description = target
    ? `Artist's impression of ${target.name} (${look?.label ?? ""}), not SPHEREx data.`
    : "Custom field: no catalogued object to show.";
  return (
    <div className={s.hologram}>
      {supported && (
        <Canvas
          className={s.canvas}
          aria-hidden="true"
          frameloop={visible && !reduced ? "always" : "demand"}
          dpr={[1, 1.5]}
          gl={{ alpha: true, antialias: true }}
          camera={{ position: [0, 0.35, 5.4], fov: 38 }}
        >
          {look ? (
            <Model key={target?.slug} look={look} spin={!reduced} />
          ) : (
            <Wireframe spin={!reduced} />
          )}
        </Canvas>
      )}
      <p className={s.caption} aria-hidden="true">
        <span>{caption}</span>
        <small>{look ? "Illustration" : "No catalogued object"}</small>
      </p>
      <p className={s.srOnly}>{description}</p>
    </div>
  );
}
