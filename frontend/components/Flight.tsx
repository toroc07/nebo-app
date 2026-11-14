"use client";
import { Canvas, useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
function Stars() {
  const mesh = useRef<THREE.Points>(null);
  const positions = useMemo(
    () =>
      new Float32Array(
        Array.from({ length: 180 }, (_, i) => {
          const n = Math.sin(i * 127.1 + 31.7) * 43758.5453;
          return (n - Math.floor(n) - 0.5) * 20;
        }),
      ),
    [],
  );
  useFrame((_, dt) => {
    if (mesh.current) mesh.current.position.z += dt * 12;
  });
  return (
    <points ref={mesh}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
      </bufferGeometry>
      <pointsMaterial color="#edc181" size={0.04} transparent opacity={0.6} />
    </points>
  );
}
export default function Flight({ trigger }: { trigger: number }) {
  const [active, setActive] = useState(false),
    [supported, setSupported] = useState(false);
  useEffect(() => {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl2");
    setSupported(!!gl && window.innerWidth >= 768);
    gl?.getExtension("WEBGL_lose_context")?.loseContext();
  }, []);
  useEffect(() => {
    setActive(true);
    const id = setTimeout(() => setActive(false), 450);
    return () => clearTimeout(id);
  }, [trigger]);
  useEffect(() => {
    const hide = () => {
      if (document.hidden) setActive(false);
    };
    document.addEventListener("visibilitychange", hide);
    return () => document.removeEventListener("visibilitychange", hide);
  }, []);
  if (!supported) return null;
  return (
    <div
      className="flight"
      aria-hidden="true"
      style={{ opacity: active ? 1 : 0 }}
    >
      <Canvas
        frameloop={active ? "always" : "never"}
        dpr={1}
        gl={{ alpha: true, antialias: false }}
        camera={{ position: [0, 0, 10] }}
      >
        <Stars key={trigger} />
      </Canvas>
    </div>
  );
}
